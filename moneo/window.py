"""Fenêtre principale : barre latérale, pages et actions de fichiers."""

from datetime import date
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, GObject, Gtk

from . import APP_ID, __version__
from .db import BackupError
from .dialogs import BalanceDialog, ImportDialog, TransactionDialog
from .pages import (
    CategoriesPage,
    GoalsPage,
    OverviewPage,
    RecurringPage,
    TransactionsPage,
    TrendsPage,
)
from .ui_common import confirm

NARROW_WIDTH = "max-width: 640sp"


class MoneoWindow(Adw.ApplicationWindow):
    def __init__(self, application, db):
        super().__init__(application=application, title="Monéo", default_width=1080, default_height=760)
        self.set_size_request(360, 480)
        self.db = db

        self.pages = [
            OverviewPage(self),
            TransactionsPage(self),
            TrendsPage(self),
            CategoriesPage(self),
            RecurringPage(self),
            GoalsPage(self),
        ]
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        for page in self.pages:
            self.stack.add_named(page.widget, page.title)

        self.content_page = Adw.NavigationPage(title=self.pages[0].title, child=self.stack)
        self.split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Monéo", child=self._build_sidebar()),
            content=self.content_page,
        )
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(NARROW_WIDTH))
        breakpoint_.add_setter(self.split, "collapsed", GObject.Value(bool, True))
        self.add_breakpoint(breakpoint_)

        self._install_actions()
        # Les couleurs des données changent avec le thème : tout est redessiné.
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.refresh())
        self.refresh()

    def _build_sidebar(self) -> Adw.ToolbarView:
        self.nav_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        for page in self.pages:
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            box.append(Gtk.Image(icon_name=page.icon))
            box.append(Gtk.Label(label=page.title, xalign=0))
            self.nav_list.append(Gtk.ListBoxRow(child=box))
        self.nav_list.select_row(self.nav_list.get_row_at_index(0))
        self.nav_list.connect("row-activated", self._on_nav_activated)

        menu = Gio.Menu()
        data = Gio.Menu()
        data.append("Importer un relevé…", "win.import")
        data.append("Corriger le solde…", "win.set-balance")
        menu.append_section(None, data)
        backup = Gio.Menu()
        backup.append("Créer une sauvegarde…", "win.backup")
        backup.append("Restaurer une sauvegarde…", "win.restore")
        menu.append_section(None, backup)
        about = Gio.Menu()
        about.append("À propos de Monéo", "win.about")
        menu.append_section(None, about)

        header = Adw.HeaderBar()
        header.pack_end(
            Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True, tooltip_text="Menu principal")
        )
        toolbar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.nav_list, vexpand=True))
        toolbar.add_top_bar(header)
        return toolbar

    def _on_nav_activated(self, _list, row):
        self.show_page(row.get_index())
        self.split.set_show_content(True)

    def show_page(self, index: int) -> None:
        page = self.pages[index]
        self.stack.set_visible_child_name(page.title)
        self.content_page.set_title(page.title)
        self.nav_list.select_row(self.nav_list.get_row_at_index(index))

    def _install_actions(self):
        for name, callback in (
            ("new-transaction", self._on_new_transaction),
            ("import", self._on_import),
            ("set-balance", self._on_set_balance),
            ("backup", self._on_backup),
            ("restore", self._on_restore),
            ("about", self._on_about),
        ):
            action = Gio.SimpleAction(name=name)
            action.connect("activate", callback)
            self.add_action(action)

    def refresh(self) -> None:
        # Vérifié à chaque actualisation : couvre le démarrage, une récurrence
        # déjà échue qu'on vient de créer et une fenêtre restée ouverte la nuit.
        created = self.db.generate_due()
        if created:
            plural = "s" if created > 1 else ""
            self.toast(f"{created} opération{plural} récurrente{plural} ajoutée{plural}")
        for page in self.pages:
            page.refresh()

    def refresh_later(self) -> None:
        GLib.idle_add(self._refresh_once)

    def _refresh_once(self):
        self.refresh()
        return GLib.SOURCE_REMOVE

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message, timeout=4))

    def _on_new_transaction(self, *_):
        TransactionDialog(self).present(self)

    def _on_set_balance(self, *_):
        BalanceDialog(self).present(self)

    # ---------------------------------------------------------------- Import

    def _on_import(self, *_):
        statements = Gtk.FileFilter(name="Relevés bancaires (CSV, OFX)")
        for pattern in ("*.csv", "*.CSV", "*.txt", "*.ofx", "*.OFX", "*.qfx"):
            statements.add_pattern(pattern)
        dialog = Gtk.FileDialog(title="Importer un relevé", default_filter=statements)
        dialog.open(self, None, self._on_import_file)

    def _on_import_file(self, dialog, result):
        path = self._finish_file_dialog(dialog.open_finish, result)
        if path:
            self.import_file(path)

    def import_file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
            ImportDialog(self, path, data).present(self)
        except (OSError, ValueError) as error:
            self.toast(f"Import impossible : {error}")

    def _finish_file_dialog(self, finish, result) -> Path | None:
        try:
            file = finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.toast(f"Erreur : {error.message}")
            return None
        return Path(file.get_path()) if file else None

    # ------------------------------------------------------------ Sauvegarde

    def _on_backup(self, *_):
        dialog = Gtk.FileDialog(
            title="Créer une sauvegarde",
            initial_name=f"moneo-sauvegarde-{date.today().isoformat()}.db",
        )
        dialog.save(self, None, self._on_backup_file)

    def _on_backup_file(self, dialog, result):
        path = self._finish_file_dialog(dialog.save_finish, result)
        if not path:
            return
        try:
            self.db.export_backup(path)
            self.toast(f"Sauvegarde créée : {path.name}")
        except Exception as error:  # noqa: BLE001 : toute erreur doit être signalée
            self.toast(f"Sauvegarde impossible : {error}")

    def _on_restore(self, *_):
        dialog = Gtk.FileDialog(title="Restaurer une sauvegarde")
        dialog.open(self, None, self._on_restore_file)

    def _on_restore_file(self, dialog, result):
        path = self._finish_file_dialog(dialog.open_finish, result)
        if path:
            confirm(
                self,
                "Remplacer toutes tes données ?",
                f"Le contenu de « {path.name} » remplacera tes données actuelles. "
                "Une copie de sécurité de ces données sera d'abord gardée à côté de ta base.",
                "Restaurer",
                lambda: self._restore(path),
            )

    def _restore(self, path: Path) -> None:
        try:
            self.db.restore_backup(path)
        except BackupError as error:
            self.toast(str(error))
            return
        self.refresh()
        self.toast("Sauvegarde restaurée")

    def _on_about(self, *_):
        Adw.AboutDialog(
            application_name="Monéo",
            application_icon=APP_ID,
            version=__version__,
            comments="Gère ton argent simplement : tes données restent sur ton ordinateur.",
        ).present(self)
