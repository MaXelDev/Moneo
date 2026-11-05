"""Couleurs des données, validées sur les surfaces de cartes Adwaita.

Un même emplacement désigne la même teinte dans les deux thèmes ; l'ordre est fixe
car il garantit la séparation des couleurs voisines pour les daltoniens.
"""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")
COLOR_NAMES = ("Bleu", "Orange", "Turquoise", "Jaune", "Rose", "Vert", "Violet", "Rouge")

SLOT_PRIMARY = 0
SLOT_SECONDARY = 1

CSS = """
.hero-amount { font-size: 48px; font-weight: 700; }
.stat-value { font-size: 22px; font-weight: 700; }
.pad-card { padding: 16px; }
.sidebar-title { font-weight: 700; }

progressbar.moneo-meter > trough,
progressbar.moneo-meter > trough > progress { min-height: 8px; border-radius: 4px; }
progressbar.moneo-warn > trough > progress { background-color: var(--warning-bg-color); }
progressbar.moneo-over > trough > progress { background-color: var(--error-bg-color); }
progressbar.moneo-good > trough > progress { background-color: var(--success-bg-color); }

.color-choice { min-width: 32px; min-height: 32px; padding: 4px; }
.table-head { font-weight: 700; }
"""


def is_dark() -> bool:
    return Adw.StyleManager.get_default().get_dark()


def slot_rgb(slot: int | None) -> tuple[float, float, float]:
    """Couleur d'un emplacement ; None donne le gris « sans catégorie »."""
    if slot is None:
        return (0.54, 0.53, 0.51)
    value = (DARK if is_dark() else LIGHT)[slot % len(LIGHT)]
    return tuple(int(value[index : index + 2], 16) / 255 for index in (1, 3, 5))


def load_css(display) -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
