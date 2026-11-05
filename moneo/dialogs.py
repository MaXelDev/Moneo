"""Formulaires de saisie."""

from datetime import date
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from .dates import add_months, format_date
from .db import PALETTE_SIZE
from .importers import CsvMapping, parse_csv_rows, parse_ofx, read_csv
from .money import format_amount, input_amount, parse_amount
from .theme import COLOR_NAMES
from .ui_common import ColorDot, DateRow, confirm

FREQUENCIES = (("monthly", "Tous les mois"), ("weekly", "Toutes les semaines"), ("yearly", "Tous les ans"))


class FormDialog(Adw.Dialog):
    """Formulaire avec Annuler/Enregistrer ; une erreur de saisie s'affiche sans fermer."""

    save_label = "Enregistrer"

    def __init__(self, window, title: str):
        super().__init__(title=title, content_width=460)
        self.window = window
        self.db = window.db

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.save_button = Gtk.Button(label=self.save_label)
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)
        header.pack_end(self.save_button)

        self.page = Adw.PreferencesPage()
        self.toasts = Adw.ToastOverlay(child=self.page)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)
        self.set_default_widget(self.save_button)

    def group(self, title: str | None = None, description: str | None = None) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title, description=description)
        self.page.add(group)
        return group

    def entry(self, title: str, text: str = "") -> Adw.EntryRow:
        row = Adw.EntryRow(title=title, text=text, activates_default=True)
        return row

    def delete_button(self, label: str, callback) -> None:
        button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.add_css_class("pill")
        button.connect("clicked", callback)
        self.group().add(button)

    def _on_save(self, *_):
        try:
            self.save()
        except ValueError as error:
            self.toasts.add_toast(Adw.Toast(title=str(error), timeout=4))
            return
        self.close()
        self.window.refresh()

    def save(self) -> None:
        raise NotImplementedError

    def finish_delete(self, message: str) -> None:
        self.close()
        self.window.refresh()
        self.window.toast(message)


def _kind_toggle(active: str, labels=("Dépense", "Revenu")) -> Adw.ToggleGroup:
    group = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
    group.add(Adw.Toggle(name="expense", label=labels[0]))
    group.add(Adw.Toggle(name="income", label=labels[1]))
    group.set_active_name(active)
    return group


def _positive_amount(row: Adw.EntryRow, field: str = "le montant") -> int:
    text = row.get_text().strip()
    if not text:
        raise ValueError(f"Indique {field}.")
    try:
        cents = abs(parse_amount(text))
    except ValueError:
        raise ValueError(f"Ce montant n'est pas valide : {text}") from None
    if cents == 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    return cents


class _CategoryPicker:
    """Liste déroulante : d'abord le type d'opération choisi, puis les autres.

    Les autres restent accessibles pour un remboursement, qui entre de l'argent
    mais doit réduire les dépenses de sa catégorie.
    """

    def __init__(self, db, selected_id=None):
        self.db = db
        self.row = Adw.ComboRow(title="Catégorie")
        self.ids: list[int | None] = []
        self.selected_id = selected_id

    def rebuild(self, kind: str) -> None:
        categories = self.db.categories()
        ordered = [c for c in categories if c["kind"] == kind] + [c for c in categories if c["kind"] != kind]
        self.ids = [None] + [c["id"] for c in ordered]
        self.row.set_model(Gtk.StringList.new(["Sans catégorie"] + [c["name"] for c in ordered]))
        self.row.set_selected(self.ids.index(self.selected_id) if self.selected_id in self.ids else 0)

    def value(self) -> int | None:
        self.selected_id = self.ids[self.row.get_selected()]
        return self.selected_id


class _MoneyMovementDialog(FormDialog):
    """Champs communs à une opération et à une opération récurrente."""

    def __init__(self, window, title, amount=None, label="", category_id=None):
        super().__init__(window, title)
        kind = "income" if amount is not None and amount > 0 else "expense"
        self.kind = _kind_toggle(kind)
        self.amount = self.entry("Montant (€)", input_amount(abs(amount)) if amount else "")
        self.label = self.entry("Libellé", label)
        self.category = _CategoryPicker(self.db, category_id)
        self.category.rebuild(kind)
        self.kind.connect("notify::active-name", self._on_kind_changed)

        self.main_group = self.group()
        kind_row = Adw.ActionRow(title="Type")
        kind_row.add_suffix(self.kind)
        self.main_group.add(kind_row)
        self.main_group.add(self.amount)
        self.main_group.add(self.label)
        self.main_group.add(self.category.row)

    def _on_kind_changed(self, *_):
        self.category.value()
        self.category.rebuild(self.kind.get_active_name())

    def signed_amount(self) -> int:
        cents = _positive_amount(self.amount)
        return cents if self.kind.get_active_name() == "income" else -cents


class TransactionDialog(_MoneyMovementDialog):
    def __init__(self, window, row=None, initial_date: date | None = None):
        title = "Modifier l'opération" if row else "Nouvelle opération"
        super().__init__(
            window,
            title,
            row["amount_cents"] if row else None,
            row["label"] if row else "",
            row["category_id"] if row else None,
        )
        self.row = row
        self.date = DateRow("Date", date.fromisoformat(row["date"]) if row else initial_date)
        self.main_group.add(self.date)
        if row:
            self.delete_button("Supprimer l'opération", self._on_delete)

    def save(self):
        similar = self.db.save_transaction(
            self.row["id"] if self.row else None,
            self.date.value,
            self.label.get_text(),
            self.signed_amount(),
            self.category.value(),
        )
        if similar:
            plural = "s" if similar > 1 else ""
            self.window.toast(f"{similar} autre{plural} opération{plural} similaire{plural} classée{plural} aussi")

    def _on_delete(self, *_):
        confirm(
            self,
            "Supprimer cette opération ?",
            f"« {self.row['label']} » sera définitivement supprimée et ton solde sera recalculé.",
            "Supprimer",
            self._do_delete,
        )

    def _do_delete(self):
        self.db.delete_transaction(self.row["id"])
        self.finish_delete("Opération supprimée")


class RecurringDialog(_MoneyMovementDialog):
    def __init__(self, window, row=None):
        title = "Modifier la récurrence" if row else "Nouvelle récurrence"
        super().__init__(
            window,
            title,
            row["amount_cents"] if row else None,
            row["label"] if row else "",
            row["category_id"] if row else None,
        )
        self.row = row
        self.frequency = Adw.ComboRow(
            title="Fréquence", model=Gtk.StringList.new([label for _, label in FREQUENCIES])
        )
        keys = [key for key, _ in FREQUENCIES]
        if row:
            self.frequency.set_selected(keys.index(row["frequency"]))
        self.main_group.add(self.frequency)
        self.date = DateRow("Prochaine échéance", self.db.next_occurrence(row) if row else None)
        self.main_group.add(self.date)
        if row:
            self.delete_button("Supprimer la récurrence", self._on_delete)

    def save(self):
        self.db.save_recurring(
            self.row["id"] if self.row else None,
            self.label.get_text(),
            self.signed_amount(),
            self.category.value(),
            FREQUENCIES[self.frequency.get_selected()][0],
            self.date.value,
        )

    def _on_delete(self, *_):
        confirm(
            self,
            "Supprimer cette récurrence ?",
            "Les opérations déjà créées sont conservées, mais aucune nouvelle ne sera ajoutée.",
            "Supprimer",
            self._do_delete,
        )

    def _do_delete(self):
        self.db.delete_recurring(self.row["id"])
        self.finish_delete("Récurrence supprimée")


class CategoryDialog(FormDialog):
    def __init__(self, window, row=None):
        super().__init__(window, "Modifier la catégorie" if row else "Nouvelle catégorie")
        self.row = row
        self.name = self.entry("Nom", row["name"] if row else "")
        self.kind = _kind_toggle(row["kind"] if row else "expense")
        self.color = row["color"] if row else self.db.next_color()

        group = self.group()
        group.add(self.name)
        kind_row = Adw.ActionRow(title="Type")
        kind_row.add_suffix(self.kind)
        group.add(kind_row)
        group.add(self._color_row())

        self.budget_group = self.group(
            "Budget mensuel", "Laisse vide si tu ne veux pas de limite pour cette catégorie."
        )
        budget = row["budget_cents"] if row else None
        self.budget = self.entry("Limite par mois (€)", input_amount(budget) if budget else "")
        self.budget_group.add(self.budget)
        self.kind.connect("notify::active-name", self._on_kind_changed)
        self._on_kind_changed()

        if row:
            self.delete_button("Supprimer la catégorie", self._on_delete)

    def _color_row(self) -> Gtk.ListBoxRow:
        box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=PALETTE_SIZE,
            min_children_per_line=4,
            column_spacing=4,
            row_spacing=4,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        leader = None
        for slot in range(PALETTE_SIZE):
            button = Gtk.ToggleButton(
                child=ColorDot(slot, 18), active=slot == self.color, tooltip_text=COLOR_NAMES[slot]
            )
            button.add_css_class("flat")
            button.add_css_class("color-choice")
            button.update_property([Gtk.AccessibleProperty.LABEL], [COLOR_NAMES[slot]])
            if leader:
                button.set_group(leader)
            else:
                leader = button
            button.connect("toggled", self._on_color_toggled, slot)
            box.append(button)
        row = Gtk.ListBoxRow(activatable=False, child=box)
        return row

    def _on_color_toggled(self, button, slot):
        if button.get_active():
            self.color = slot

    def _on_kind_changed(self, *_):
        self.budget_group.set_visible(self.kind.get_active_name() == "expense")

    def save(self):
        text = self.budget.get_text().strip()
        budget = _positive_amount(self.budget) if text else None
        self.db.save_category(
            self.row["id"] if self.row else None,
            self.name.get_text(),
            self.kind.get_active_name(),
            self.color,
            budget,
        )

    def _on_delete(self, *_):
        count = self.db.category_usage(self.row["id"])
        body = (
            f"{count} opération{'s' if count > 1 else ''} passera{'ont' if count > 1 else ''} « Sans catégorie »."
            if count
            else "Aucune opération n'utilise cette catégorie."
        )
        confirm(self, f"Supprimer « {self.row['name']} » ?", body, "Supprimer", self._do_delete)

    def _do_delete(self):
        self.db.delete_category(self.row["id"])
        self.finish_delete("Catégorie supprimée")


class GoalDialog(FormDialog):
    def __init__(self, window, row=None):
        super().__init__(window, "Modifier l'objectif" if row else "Nouvel objectif")
        self.row = row
        self.name = self.entry("Nom", row["name"] if row else "")
        self.target = self.entry("Montant visé (€)", input_amount(row["target_cents"]) if row else "")
        deadline = date.fromisoformat(row["deadline"]) if row and row["deadline"] else None

        group = self.group()
        group.add(self.name)
        group.add(self.target)
        self.has_deadline = Adw.ExpanderRow(
            title="Date limite",
            subtitle="Calcule combien mettre de côté chaque mois",
            show_enable_switch=True,
            enable_expansion=deadline is not None,
        )
        self.deadline = DateRow("Date", deadline or add_months(date.today(), 12))
        self.has_deadline.add_row(self.deadline)
        group.add(self.has_deadline)
        if row:
            self.delete_button("Supprimer l'objectif", self._on_delete)

    def save(self):
        self.db.save_goal(
            self.row["id"] if self.row else None,
            self.name.get_text(),
            _positive_amount(self.target, "le montant visé"),
            self.deadline.value if self.has_deadline.get_enable_expansion() else None,
        )

    def _on_delete(self, *_):
        confirm(
            self,
            f"Supprimer « {self.row['name']} » ?",
            "Ton solde ne change pas : seul le suivi de cet objectif disparaît.",
            "Supprimer",
            self._do_delete,
        )

    def _do_delete(self):
        self.db.delete_goal(self.row["id"])
        self.finish_delete("Objectif supprimé")


class GoalAdjustDialog(FormDialog):
    def __init__(self, window, row):
        super().__init__(window, row["name"])
        self.row = row
        self.direction = _kind_toggle("income", ("Retirer", "Ajouter"))
        self.amount = self.entry("Montant (€)")
        group = self.group(
            None,
            f"Déjà mis de côté : {format_amount(row['saved_cents'])}. "
            "Cet argent reste sur ton compte, il est simplement réservé à cet objectif.",
        )
        direction_row = Adw.ActionRow(title="Action")
        direction_row.add_suffix(self.direction)
        group.add(direction_row)
        group.add(self.amount)

    def save(self):
        cents = _positive_amount(self.amount)
        delta = cents if self.direction.get_active_name() == "income" else -cents
        self.db.adjust_goal(self.row["id"], delta)


class BalanceDialog(FormDialog):
    def __init__(self, window):
        super().__init__(window, "Solde du compte")
        known = self.db.has_opening_balance()
        self.balance = self.entry(
            "Solde actuel (€)", input_amount(self.db.balance()) if known else ""
        )
        group = self.group(
            None,
            "Indique le solde affiché aujourd'hui par ta banque. "
            "Monéo en déduit les soldes passés à partir de tes opérations.",
        )
        group.add(self.balance)

    def save(self):
        text = self.balance.get_text().strip()
        if not text:
            raise ValueError("Indique le solde de ton compte.")
        try:
            cents = parse_amount(text)
        except ValueError:
            raise ValueError(f"Ce montant n'est pas valide : {text}") from None
        self.db.set_current_balance(cents)


NO_COLUMN = "Aucune"


class ImportDialog(FormDialog):
    """Vérifie les colonnes et l'aperçu avant d'importer un relevé CSV ou OFX."""

    save_label = "Importer"
    PREVIEW_ROWS = 5

    def __init__(self, window, path: Path, data: bytes):
        super().__init__(window, f"Importer {path.name}")
        self.csv_file = None
        self.items = []
        self.skipped = 0
        self.combos: dict[str, Adw.ComboRow] = {}

        if path.suffix.lower() in (".ofx", ".qfx"):
            self.items, self.skipped = parse_ofx(data)
        else:
            self.csv_file = read_csv(data)
            self._build_mapping()

        self.preview = self.group("Aperçu")
        self.preview_rows: list[Gtk.Widget] = []
        self._update_preview()

    def _build_mapping(self) -> None:
        group = self.group(
            "Colonnes du fichier",
            "Monéo les a repérées seul. Corrige-les si l'aperçu n'est pas bon.",
        )
        options = [NO_COLUMN] + [h or f"Colonne {i + 1}" for i, h in enumerate(self.csv_file.headers)]
        mapping = self.csv_file.mapping
        for field, title in (
            ("date", "Date"),
            ("label", "Libellé"),
            ("amount", "Montant"),
            ("debit", "Débit"),
            ("credit", "Crédit"),
        ):
            combo = Adw.ComboRow(title=title, model=Gtk.StringList.new(options))
            index = getattr(mapping, field)
            combo.set_selected(0 if index is None else index + 1)
            combo.connect("notify::selected", lambda *_: self._update_preview())
            self.combos[field] = combo
            group.add(combo)

    def _current_mapping(self) -> CsvMapping:
        values = {}
        for field, combo in self.combos.items():
            selected = combo.get_selected()
            values[field] = None if selected == 0 else selected - 1
        return CsvMapping(**values)

    def _update_preview(self) -> None:
        if self.csv_file is not None:
            mapping = self._current_mapping()
            if mapping.is_complete():
                self.items, self.skipped = parse_csv_rows(self.csv_file, mapping)
            else:
                self.items, self.skipped = [], 0

        for row in self.preview_rows:
            self.preview.remove(row)
        self.preview_rows = []

        count = len(self.items)
        plural = "s" if count > 1 else ""
        description = f"{count} opération{plural} trouvée{plural}"
        if self.skipped:
            description += f", {self.skipped} ligne{'s' if self.skipped > 1 else ''} ignorée{'s' if self.skipped > 1 else ''} (date, libellé ou montant illisible)"
        self.preview.set_description(description + ".")
        self.save_button.set_sensitive(count > 0)

        for item in self.items[: self.PREVIEW_ROWS]:
            row = Adw.ActionRow(title=item.label, subtitle=format_date(item.date), title_lines=1, use_markup=False)
            amount = Gtk.Label(label=format_amount(item.amount_cents, signed=True))
            amount.add_css_class("numeric")
            row.add_suffix(amount)
            self.preview.add(row)
            self.preview_rows.append(row)

    def save(self):
        result = self.db.import_transactions(self.items)
        parts = [f"{result.added} ajoutée{'s' if result.added > 1 else ''}"]
        if result.reconciled:
            parts.append(f"{result.reconciled} rapprochée{'s' if result.reconciled > 1 else ''}")
        if result.duplicates:
            parts.append(f"{result.duplicates} déjà présente{'s' if result.duplicates > 1 else ''}")
        self.window.toast("Import terminé : " + ", ".join(parts))
