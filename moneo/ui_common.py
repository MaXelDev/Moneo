"""Petites briques d'interface partagées par les pages et les formulaires."""

from datetime import date

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from .dates import format_date
from .money import format_amount
from .theme import slot_rgb

WARN_RATIO = 0.8


class ColorDot(Gtk.DrawingArea):
    """Pastille d'identité d'une catégorie, toujours à côté de son nom."""

    def __init__(self, slot: int | None, size: int = 12):
        super().__init__(content_width=size, content_height=size, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.slot = slot
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width, height):
        cr.set_source_rgb(*slot_rgb(self.slot))
        cr.arc(width / 2, height / 2, min(width, height) / 2, 0, 6.2832)
        cr.fill()


def amount_label(cents: int, signed: bool = True) -> Gtk.Label:
    """Montant aligné ; un revenu porte son signe en plus de la couleur."""
    label = Gtk.Label(label=format_amount(cents, signed=signed), valign=Gtk.Align.CENTER)
    label.add_css_class("numeric")
    if cents > 0 and signed:
        label.add_css_class("success")
    return label


def caption(text: str, wrap: bool = False) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0, wrap=wrap)
    label.add_css_class("dim-label")
    label.add_css_class("caption")
    return label


def page_shell(title: str, start=(), end=(), max_width: int = 820):
    """Page standard : barre de titre et contenu défilant, centré et limité en largeur."""
    header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title=title))
    for widget in start:
        header.pack_start(widget)
    for widget in end:
        header.pack_end(widget)
    content = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=24,
        margin_top=24,
        margin_bottom=32,
        margin_start=16,
        margin_end=16,
    )
    clamp = Adw.Clamp(maximum_size=max_width, child=content)
    scroller = Gtk.ScrolledWindow(child=clamp, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    toolbar = Adw.ToolbarView(content=scroller)
    toolbar.add_top_bar(header)
    return toolbar, content


def section(title: str, subtitle: str | None = None) -> Adw.PreferencesGroup:
    return Adw.PreferencesGroup(title=title, description=subtitle)


def clear(box: Gtk.Box) -> None:
    while child := box.get_first_child():
        box.remove(child)


def empty_row(text: str) -> Adw.ActionRow:
    row = Adw.ActionRow(title=text)
    row.add_css_class("dim-label")
    return row


def icon_button(icon: str, tooltip: str, action=None, callback=None) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    if action:
        button.set_action_name(action)
    if callback:
        button.connect("clicked", callback)
    return button


def confirm(parent, heading: str, body: str, action_label: str, on_confirm) -> None:
    """Confirmation d'une action difficile à annuler."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("confirm", action_label)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(_dialog, response):
        if response == "confirm":
            on_confirm()

    dialog.connect("response", on_response)
    dialog.present(parent)


class DateRow(Adw.ActionRow):
    """Ligne de formulaire avec un calendrier déroulant."""

    def __init__(self, title: str, value: date | None = None):
        super().__init__(title=title)
        self.value = value or date.today()
        self.calendar = Gtk.Calendar()
        self._select(self.value)
        self.calendar.connect("day-selected", self._on_day_selected)
        self.popover = Gtk.Popover(child=self.calendar)
        self.button = Gtk.MenuButton(
            label=format_date(self.value), popover=self.popover, valign=Gtk.Align.CENTER
        )
        self.button.add_css_class("flat")
        self.add_suffix(self.button)
        self.set_activatable_widget(self.button)

    def _select(self, day: date) -> None:
        self.calendar.select_day(GLib.DateTime.new_local(day.year, day.month, day.day, 0, 0, 0))

    def _on_day_selected(self, calendar):
        selected = calendar.get_date()
        self.value = date(selected.get_year(), selected.get_month(), selected.get_day_of_month())
        self.button.set_label(format_date(self.value))
        self.popover.popdown()


def budget_meter(row) -> Gtk.Box:
    """Où en est une catégorie par rapport à son budget du mois.

    L'état se lit dans le texte et l'icône, pas seulement dans la couleur de la barre.
    """
    spent, budget = max(0, row["spent"]), row["budget_cents"]
    ratio = spent / budget
    remaining = budget - spent

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    top = Gtk.Box(spacing=8)
    top.append(ColorDot(row["color"]))
    name = Gtk.Label(label=row["name"], xalign=0, hexpand=True, ellipsize=3)
    top.append(name)
    figures = Gtk.Label(label=f"{format_amount(spent)} sur {format_amount(budget)}")
    figures.add_css_class("numeric")
    top.append(figures)
    box.append(top)

    bar = Gtk.ProgressBar(fraction=min(1.0, ratio))
    bar.add_css_class("moneo-meter")
    box.append(bar)

    status = Gtk.Box(spacing=6)
    if ratio > 1:
        bar.add_css_class("moneo-over")
        status.append(Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=14))
        text = f"Dépassé de {format_amount(-remaining)}"
    elif ratio >= WARN_RATIO:
        bar.add_css_class("moneo-warn")
        text = f"Bientôt atteint : il reste {format_amount(remaining)}"
    else:
        text = f"Il reste {format_amount(remaining)}"
    status.append(caption(text))
    box.append(status)
    return box


def card(child: Gtk.Widget) -> Gtk.Box:
    wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    wrapper.add_css_class("card")
    wrapper.add_css_class("pad-card")
    wrapper.append(child)
    return wrapper
