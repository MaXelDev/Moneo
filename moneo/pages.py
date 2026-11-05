"""Les six pages de l'application. Chacune se reconstruit via refresh()."""

from datetime import date

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from .charts import BalanceChart, BarMark, IncomeExpenseChart
from .dates import (
    add_months,
    format_date,
    format_month,
    iter_months,
    month_end,
    month_start,
    months_between,
)
from .dialogs import (
    CategoryDialog,
    GoalAdjustDialog,
    GoalDialog,
    RecurringDialog,
    TransactionDialog,
)
from .money import format_amount
from .ui_common import (
    ColorDot,
    amount_label,
    budget_meter,
    caption,
    card,
    clear,
    empty_row,
    icon_button,
    page_shell,
    section,
)

FREQUENCY_LABELS = {"weekly": "Chaque semaine", "monthly": "Chaque mois", "yearly": "Chaque année"}
FREQUENCY_PER_MONTH = {"weekly": 52 / 12, "monthly": 1, "yearly": 1 / 12}


def transaction_row(window, row) -> Adw.ActionRow:
    day = date.fromisoformat(row["date"])
    category = row["category_name"] or "Sans catégorie"
    widget = Adw.ActionRow(
        title=row["label"],
        subtitle=f"{format_date(day)} · {category}",
        activatable=True,
        use_markup=False,
        title_lines=1,
    )
    widget.add_prefix(ColorDot(row["category_color"]))
    widget.add_suffix(amount_label(row["amount_cents"]))
    widget.connect("activated", lambda *_: TransactionDialog(window, row).present(window))
    return widget


class ListSection:
    """Groupe de lignes qu'on peut vider et remplir à chaque actualisation."""

    def __init__(self, title: str, subtitle: str | None = None):
        self.group = section(title, subtitle)
        self.rows: list[Gtk.Widget] = []

    def set_rows(self, rows) -> None:
        for row in self.rows:
            self.group.remove(row)
        self.rows = list(rows)
        for row in self.rows:
            self.group.add(row)


def stat_tile(title: str) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
    value = Gtk.Label(xalign=0)
    value.add_css_class("stat-value")
    note = caption("", wrap=True)
    note.set_max_width_chars(22)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(caption(title))
    box.append(value)
    box.append(note)
    return card(box), value, note


class OverviewPage:
    title = "Aperçu"
    icon = "go-home-symbolic"

    def __init__(self, window):
        self.window = window
        add = icon_button("list-add-symbolic", "Nouvelle opération (Ctrl+N)", action="win.new-transaction")
        self.widget, content = page_shell(self.title, end=[add])

        self.banner = Adw.Banner(
            title="Indique le solde de ton compte pour démarrer", button_label="Indiquer le solde"
        )
        self.banner.set_action_name("win.set-balance")
        content.append(self.banner)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.append(caption("Solde actuel"))
        self.balance = Gtk.Label(xalign=0, wrap=True)
        self.balance.add_css_class("hero-amount")
        hero.append(self.balance)
        self.available = caption("", wrap=True)
        hero.append(self.available)
        content.append(hero)

        tiles = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=12,
            row_spacing=12,
        )
        income, self.income, self.income_note = stat_tile("Revenus du mois")
        expense, self.expense, self.expense_note = stat_tile("Dépenses du mois")
        net, self.net, self.net_note = stat_tile("Épargné ce mois-ci")
        for tile in (income, expense, net):
            child = Gtk.FlowBoxChild(child=tile, focusable=False)
            tiles.append(child)
        content.append(tiles)

        self.budgets_group = section("Budgets du mois")
        self.budgets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.budgets_card = card(self.budgets_box)
        self.budgets_group.add(self.budgets_card)
        content.append(self.budgets_group)

        self.upcoming = ListSection("Prochaines échéances", "Les 30 prochains jours")
        content.append(self.upcoming.group)
        self.recent = ListSection("Dernières opérations")
        content.append(self.recent.group)

    def refresh(self):
        db = self.window.db
        today = date.today()
        self.banner.set_revealed(not db.has_opening_balance())

        balance = db.balance()
        reserved = db.total_saved()
        self.balance.set_label(format_amount(balance))
        self.available.set_label(
            f"Dont {format_amount(reserved)} réservés à tes objectifs, soit {format_amount(balance - reserved)} disponibles"
            if reserved
            else ""
        )
        self.available.set_visible(bool(reserved))

        start, end = month_start(today), month_end(today)
        income, expense = db.month_totals(start, end)
        previous_day = add_months(start, -1)
        _, previous_expense = db.month_totals(previous_day, month_end(previous_day))
        self.income.set_label(format_amount(income))
        self.income_note.set_label(format_month(today).capitalize())
        self.expense.set_label(format_amount(expense))
        self.expense_note.set_label(f"Mois dernier : {format_amount(previous_expense)}")
        self.net.set_label(format_amount(income - expense, signed=True))
        self.net_note.set_label("Revenus moins dépenses")

        clear(self.budgets_box)
        budgets = db.budget_status(start, end)
        for row in budgets[:4]:
            self.budgets_box.append(budget_meter(row))
        self.budgets_group.set_visible(bool(budgets))

        upcoming = db.upcoming(30, today)[:4]
        rows = []
        for day, item in upcoming:
            row = Adw.ActionRow(title=item["label"], subtitle=format_date(day), use_markup=False)
            row.add_prefix(ColorDot(item["category_color"]))
            row.add_suffix(amount_label(item["amount_cents"]))
            rows.append(row)
        self.upcoming.set_rows(rows)
        self.upcoming.group.set_visible(bool(rows))

        recent = db.transactions(end=today, limit=5)
        self.recent.set_rows(
            [transaction_row(self.window, row) for row in recent]
            or [empty_row("Aucune opération pour l'instant. Ajoute-en une avec le bouton +.")]
        )


class TransactionsPage:
    title = "Opérations"
    icon = "view-list-symbolic"

    def __init__(self, window):
        self.window = window
        self.month = month_start(date.today())
        self.filter_ids: list = []

        add = icon_button("list-add-symbolic", "Nouvelle opération (Ctrl+N)", action="win.new-transaction")
        import_button = icon_button(
            "document-open-symbolic", "Importer un relevé CSV ou OFX (Ctrl+I)", action="win.import"
        )
        self.widget, content = page_shell(self.title, end=[add, import_button])

        navigation = Gtk.Box(spacing=8)
        navigation.append(icon_button("go-previous-symbolic", "Mois précédent", callback=lambda *_: self._shift(-1)))
        self.month_label = Gtk.Label(hexpand=True)
        self.month_label.add_css_class("title-3")
        navigation.append(self.month_label)
        navigation.append(icon_button("go-next-symbolic", "Mois suivant", callback=lambda *_: self._shift(1)))
        content.append(navigation)
        self.navigation = navigation

        filters = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(
            hexpand=True, placeholder_text="Rechercher dans tous les mois"
        )
        self.search.connect("search-changed", lambda *_: self.refresh_list())
        filters.append(self.search)
        self.category_filter = Gtk.DropDown()
        self.category_handler = self.category_filter.connect(
            "notify::selected", lambda *_: self.refresh_list()
        )
        filters.append(self.category_filter)
        content.append(filters)

        self.summary = caption("")
        content.append(self.summary)
        self.list = ListSection("")
        content.append(self.list.group)

    def _shift(self, months):
        self.month = add_months(self.month, months)
        self.refresh_list()

    def refresh(self):
        selected = (
            self.filter_ids[self.category_filter.get_selected()] if self.filter_ids else "all"
        )
        categories = self.window.db.categories()
        self.filter_ids = ["all", "none"] + [c["id"] for c in categories]
        names = ["Toutes les catégories", "Sans catégorie"] + [c["name"] for c in categories]
        self.category_filter.handler_block(self.category_handler)
        self.category_filter.set_model(Gtk.StringList.new(names))
        self.category_filter.set_selected(
            self.filter_ids.index(selected) if selected in self.filter_ids else 0
        )
        self.category_filter.handler_unblock(self.category_handler)
        self.refresh_list()

    def refresh_list(self):
        db = self.window.db
        selected = self.filter_ids[self.category_filter.get_selected()]
        text = self.search.get_text().strip()
        # Rechercher ou filtrer « Sans catégorie » sert à retrouver : on regarde tous les mois.
        across_months = bool(text) or selected == "none"
        self.navigation.set_sensitive(not across_months)
        self.month_label.set_label(
            "Tous les mois" if across_months else format_month(self.month).capitalize()
        )
        rows = db.transactions(
            start=None if across_months else self.month,
            end=None if across_months else month_end(self.month),
            search=text,
            category_id=selected if isinstance(selected, int) else None,
            uncategorized=selected == "none",
        )
        total = sum(row["amount_cents"] for row in rows)
        count = len(rows)
        self.summary.set_label(
            f"{count} opération{'s' if count > 1 else ''} · total {format_amount(total, signed=True)}"
        )
        self.list.set_rows(
            [transaction_row(self.window, row) for row in rows]
            or [empty_row("Aucune opération ici.")]
        )


class TrendsPage:
    title = "Suivi"
    icon = "x-office-spreadsheet-symbolic"
    PERIODS = (("3", "3 mois"), ("6", "6 mois"), ("12", "1 an"), ("all", "Tout"))

    def __init__(self, window):
        self.window = window
        self.widget, content = page_shell(self.title)

        self.period = Adw.ToggleGroup(halign=Gtk.Align.START)
        for name, label in self.PERIODS:
            self.period.add(Adw.Toggle(name=name, label=label))
        self.period.set_active_name("6")
        self.period.connect("notify::active-name", lambda *_: self.refresh())
        content.append(self.period)

        self.balance_chart = BalanceChart()
        self.balance_group = section("Évolution du solde")
        self.balance_group.add(card(self.balance_chart))
        content.append(self.balance_group)

        self.flow_chart = IncomeExpenseChart()
        self.flow_group = section("Revenus et dépenses par mois")
        self.flow_group.add(card(self.flow_chart))
        content.append(self.flow_group)

        self.categories_group = section("Dépenses par catégorie")
        self.categories = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.categories_group.add(card(self.categories))
        content.append(self.categories_group)

        self.table = Gtk.Grid(column_spacing=20, row_spacing=8, margin_top=8, margin_bottom=8)
        table_scroller = Gtk.ScrolledWindow(
            child=self.table,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
        )
        expander = Gtk.Expander(label="Voir le détail mois par mois", child=table_scroller)
        content.append(expander)

    def _range(self, today):
        name = self.period.get_active_name()
        end = today
        if name == "all":
            earliest = self.window.db.earliest_transaction_date() or today
            return month_start(min(earliest, today)), end
        return add_months(month_start(today), -(int(name) - 1)), end

    def refresh(self):
        db = self.window.db
        today = date.today()
        start, end = self._range(today)

        series = db.balance_series(start, end)
        self.balance_chart.set_points(series)

        summary = db.monthly_summary(start, month_end(end))
        months = [
            (month, *summary.get(month.strftime("%Y-%m"), (0, 0)))
            for month in iter_months(start, end)
        ]
        self.flow_chart.set_months(months)
        self._fill_categories(db.category_spending(start, end))
        self._fill_table(months, series)

    def _fill_categories(self, rows):
        clear(self.categories)
        if not rows:
            self.categories.append(caption("Aucune dépense sur cette période."))
            return
        total = sum(row["spent"] for row in rows)
        peak = rows[0]["spent"]
        for row in rows:
            line = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            top = Gtk.Box(spacing=8)
            top.append(ColorDot(row["color"]))
            top.append(Gtk.Label(label=row["name"] or "Sans catégorie", xalign=0, hexpand=True, ellipsize=3))
            value = Gtk.Label(label=f"{format_amount(row['spent'])} · {row['spent'] / total:.0%}".replace("%", " %"))
            value.add_css_class("numeric")
            top.append(value)
            line.append(top)
            line.append(BarMark(row["spent"] / peak))
            self.categories.append(line)

    def _fill_table(self, months, series):
        while child := self.table.get_first_child():
            self.table.remove(child)
        for column, title in enumerate(("Mois", "Revenus", "Dépenses", "Épargné", "Solde en fin de mois")):
            head = Gtk.Label(label=title, xalign=0 if column == 0 else 1)
            head.add_css_class("table-head")
            self.table.attach(head, column, 0, 1, 1)
        closing = {}
        for day, value in series:
            closing[day.strftime("%Y-%m")] = value
        for index, (month, income, expense) in enumerate(reversed(months), start=1):
            cells = (
                format_month(month).capitalize(),
                format_amount(income),
                format_amount(expense),
                format_amount(income - expense, signed=True),
                format_amount(closing.get(month.strftime("%Y-%m"), 0)),
            )
            for column, text in enumerate(cells):
                cell = Gtk.Label(label=text, xalign=0 if column == 0 else 1)
                cell.add_css_class("numeric")
                self.table.attach(cell, column, index, 1, 1)


class CategoriesPage:
    title = "Catégories"
    icon = "view-grid-symbolic"

    def __init__(self, window):
        self.window = window
        add = icon_button("list-add-symbolic", "Nouvelle catégorie", callback=self._on_add)
        self.widget, content = page_shell(self.title, end=[add])
        self.budgets_group = section(
            "Budgets du mois", "Clique sur une catégorie de la liste pour modifier sa limite."
        )
        self.budgets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.budgets_group.add(card(self.budgets))
        content.append(self.budgets_group)
        self.expense = ListSection("Dépenses")
        content.append(self.expense.group)
        self.income = ListSection("Revenus")
        content.append(self.income.group)

    def _on_add(self, *_):
        CategoryDialog(self.window).present(self.window)

    def _row(self, category):
        budget = category["budget_cents"]
        widget = Adw.ActionRow(
            title=category["name"],
            subtitle=f"Limite : {format_amount(budget)} par mois" if budget else "",
            activatable=True,
            use_markup=False,
        )
        widget.add_prefix(ColorDot(category["color"]))
        widget.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        widget.connect("activated", lambda *_: CategoryDialog(self.window, category).present(self.window))
        return widget

    def refresh(self):
        db = self.window.db
        today = date.today()
        clear(self.budgets)
        budgets = db.budget_status(month_start(today), month_end(today))
        for row in budgets:
            self.budgets.append(budget_meter(row))
        self.budgets_group.set_visible(bool(budgets))
        self.expense.set_rows(
            [self._row(c) for c in db.categories("expense")] or [empty_row("Aucune catégorie de dépense.")]
        )
        self.income.set_rows(
            [self._row(c) for c in db.categories("income")] or [empty_row("Aucune catégorie de revenu.")]
        )


class RecurringPage:
    title = "Récurrences"
    icon = "media-playlist-repeat-symbolic"

    def __init__(self, window):
        self.window = window
        add = icon_button("list-add-symbolic", "Nouvelle récurrence", callback=self._on_add)
        self.widget, content = page_shell(self.title, end=[add])
        tile, self.monthly, self.monthly_note = stat_tile("Charges fixes par mois")
        content.append(tile)
        self.list = ListSection(
            "Opérations récurrentes", "Elles sont ajoutées automatiquement à chaque échéance."
        )
        content.append(self.list.group)

    def _on_add(self, *_):
        RecurringDialog(self.window).present(self.window)

    def _row(self, item):
        db = self.window.db
        details = FREQUENCY_LABELS[item["frequency"]]
        if item["active"]:
            details += f" · prochaine le {format_date(db.next_occurrence(item))}"
        else:
            details += " · en pause"
        if item["category_name"]:
            details += f" · {item['category_name']}"
        widget = Adw.ActionRow(title=item["label"], subtitle=details, activatable=True, use_markup=False)
        widget.add_prefix(ColorDot(item["category_color"]))
        widget.add_suffix(amount_label(item["amount_cents"]))
        switch = Gtk.Switch(active=bool(item["active"]), valign=Gtk.Align.CENTER, tooltip_text="Activer ou mettre en pause")
        switch.update_property([Gtk.AccessibleProperty.LABEL], [f"Activer {item['label']}"])
        switch.connect("notify::active", self._on_toggled, item["id"])
        widget.add_suffix(switch)
        widget.connect("activated", lambda *_: RecurringDialog(self.window, item).present(self.window))
        return widget

    def _on_toggled(self, switch, _param, recurring_id):
        self.window.db.set_recurring_active(recurring_id, switch.get_active())
        # Hors du signal : la reconstruction retire l'interrupteur en cours d'utilisation.
        self.window.refresh_later()

    def refresh(self):
        items = self.window.db.recurring()
        fixed = sum(
            -item["amount_cents"] * FREQUENCY_PER_MONTH[item["frequency"]]
            for item in items
            if item["active"] and item["amount_cents"] < 0
        )
        self.monthly.set_label(format_amount(round(fixed)))
        self.monthly_note.set_label("Dépenses récurrentes actives, ramenées au mois")
        self.list.set_rows(
            [self._row(item) for item in items]
            or [empty_row("Ajoute ton loyer, ton salaire ou tes abonnements avec le bouton +.")]
        )


class GoalsPage:
    title = "Objectifs"
    icon = "starred-symbolic"

    def __init__(self, window):
        self.window = window
        add = icon_button("list-add-symbolic", "Nouvel objectif", callback=self._on_add)
        self.widget, self.content = page_shell(self.title, end=[add])
        self.intro = caption(
            "L'argent mis de côté reste sur ton compte : il est simplement réservé à un objectif.",
            wrap=True,
        )
        self.content.append(self.intro)
        self.goals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.content.append(self.goals)

    def _on_add(self, *_):
        GoalDialog(self.window).present(self.window)

    def _advice(self, goal, today) -> tuple[str, bool]:
        remaining = goal["target_cents"] - goal["saved_cents"]
        if remaining <= 0:
            return "Objectif atteint", False
        text = f"Il reste {format_amount(remaining)}"
        if not goal["deadline"]:
            return text, False
        deadline = date.fromisoformat(goal["deadline"])
        if deadline < today:
            return f"{text} · échéance dépassée depuis le {format_date(deadline)}", True
        months = max(1, months_between(today, deadline))
        monthly = -(-remaining // months)
        return f"{text} · {format_amount(monthly)} par mois jusqu'au {format_date(deadline)}", False

    def _card(self, goal, today):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top = Gtk.Box(spacing=8)
        name = Gtk.Label(label=goal["name"], xalign=0, hexpand=True, ellipsize=3)
        name.add_css_class("heading")
        top.append(name)
        edit = icon_button("document-edit-symbolic", "Modifier l'objectif", callback=lambda *_: GoalDialog(self.window, goal).present(self.window))
        edit.add_css_class("flat")
        top.append(edit)
        adjust = Gtk.Button(label="Ajouter ou retirer")
        adjust.connect("clicked", lambda *_: GoalAdjustDialog(self.window, goal).present(self.window))
        top.append(adjust)
        box.append(top)

        ratio = goal["saved_cents"] / goal["target_cents"]
        figures = Gtk.Label(
            label=f"{format_amount(goal['saved_cents'])} sur {format_amount(goal['target_cents'])} · {min(ratio, 1):.0%}".replace("%", " %"),
            xalign=0,
        )
        figures.add_css_class("numeric")
        box.append(figures)
        bar = Gtk.ProgressBar(fraction=min(1.0, ratio))
        bar.add_css_class("moneo-meter")
        if ratio >= 1:
            bar.add_css_class("moneo-good")
        box.append(bar)

        advice, late = self._advice(goal, today)
        status = Gtk.Box(spacing=6)
        if ratio >= 1:
            status.append(Gtk.Image(icon_name="object-select-symbolic", pixel_size=14))
        elif late:
            status.append(Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=14))
        status.append(caption(advice, wrap=True))
        box.append(status)
        return card(box)

    def refresh(self):
        clear(self.goals)
        today = date.today()
        goals = self.window.db.goals()
        for goal in goals:
            self.goals.append(self._card(goal, today))
        if not goals:
            status = Adw.StatusPage(
                icon_name=self.icon,
                title="Aucun objectif",
                description="Crée ton premier objectif d'épargne, par exemple « Vacances : 1 500 € d'ici juillet ».",
            )
            create = Gtk.Button(label="Créer un objectif", halign=Gtk.Align.CENTER)
            create.add_css_class("suggested-action")
            create.add_css_class("pill")
            create.connect("clicked", self._on_add)
            status.set_child(create)
            self.goals.append(status)
