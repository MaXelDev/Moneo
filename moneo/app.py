"""Point d'entrée de l'application GTK."""

from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from . import APP_ID
from .db import Database
from .theme import load_css
from .window import MoneoWindow


def database_path() -> Path:
    return Path(GLib.get_user_data_dir()) / "moneo" / "moneo.db"


class MoneoApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.db: Database | None = None
        self.set_accels_for_action("win.new-transaction", ["<Control>n"])
        self.set_accels_for_action("win.import", ["<Control>i"])
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_css(Gdk.Display.get_default())
        GLib.set_application_name("Monéo")
        self.db = Database(database_path())

    def do_activate(self):
        window = self.get_active_window() or MoneoWindow(self, self.db)
        window.present()

    def do_shutdown(self):
        if self.db:
            self.db.close()
        Adw.Application.do_shutdown(self)


def main() -> int:
    return MoneoApplication().run(None)
