"""Graphiques dessinés avec Cairo, pour suivre le thème GNOME sans dépendance."""

import math
from datetime import date
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
gi.require_foreign("cairo")
from gi.repository import Gtk, PangoCairo

from .dates import format_long, format_month, format_short_month
from .money import MINUS, NARROW_NBSP, format_amount
from .theme import SLOT_PRIMARY, SLOT_SECONDARY, slot_rgb

BAR_MAX = 24
BAR_RADIUS = 4
LINE_WIDTH = 2
MUTED = 0.7
GRID = 0.1
BASELINE = 0.28


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """Graduations rondes couvrant low..high (en euros)."""
    if high <= low:
        high = low + 1
    raw = (high - low) / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value < high + step * 0.999:
        ticks.append(round(value, 6))
        value += step
    return ticks


def axis_label(euros: float, compact: bool) -> str:
    sign = MINUS if euros < 0 else ""
    magnitude = abs(euros)
    if compact:
        thousands = magnitude / 1000
        text = f"{thousands:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{sign}{text}{NARROW_NBSP}k€"
    return f"{sign}{int(round(magnitude)):,}".replace(",", NARROW_NBSP) + f"{NARROW_NBSP}€"


class Chart(Gtk.DrawingArea):
    """Base commune : texte, couleurs du thème et suivi du pointeur."""

    def __init__(self, height: int):
        super().__init__(hexpand=True, content_height=height)
        self.pointer: tuple[float, float] | None = None
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _on_motion(self, _controller, x, y):
        self.pointer = (x, y)
        self.queue_draw()

    def _on_leave(self, _controller):
        self.pointer = None
        self.queue_draw()

    def ink(self, cr, alpha: float = 1.0) -> None:
        color = self.get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha * alpha)

    def layout(self, text: str, bold: bool = False):
        layout = self.create_pango_layout(None)
        weight = ' weight="bold"' if bold else ""
        layout.set_markup(f'<span size="small" font_features="tnum"{weight}>{escape(text)}</span>')
        return layout

    def text(self, cr, text: str, x: float, y: float, align: str = "left", alpha: float = MUTED, bold=False):
        layout = self.layout(text, bold)
        width, height = layout.get_pixel_size()
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        self.ink(cr, alpha)
        cr.move_to(x, y - height / 2)
        PangoCairo.show_layout(cr, layout)

    def hairline(self, cr, x1, y1, x2, y2, alpha: float = GRID) -> None:
        self.ink(cr, alpha)
        cr.set_line_width(1)
        cr.move_to(round(x1) + 0.5, round(y1) + 0.5)
        cr.line_to(round(x2) + 0.5, round(y2) + 0.5)
        cr.stroke()

    def y_axis(self, cr, ticks, to_y, width, left):
        """Grille horizontale et graduations ; une seule échelle par graphique."""
        compact = max(abs(ticks[0]), abs(ticks[-1])) >= 10000
        for tick in ticks:
            y = to_y(tick)
            self.hairline(cr, left, y, width, y, BASELINE if tick == 0 else GRID)
            self.text(cr, axis_label(tick, compact), left - 8, y, "right")

    def axis_width(self, ticks) -> int:
        compact = max(abs(ticks[0]), abs(ticks[-1])) >= 10000
        return max(self.layout(axis_label(t, compact)).get_pixel_size()[0] for t in ticks) + 12

    def tooltip(self, cr, lines, anchor_x, anchor_y, width, height):
        """Infobulle : la première ligne en gras, placée du côté où il reste de la place."""
        layouts = [self.layout(line, index == 0) for index, line in enumerate(lines)]
        sizes = [layout.get_pixel_size() for layout in layouts]
        box_w = max(size[0] for size in sizes) + 20
        box_h = sum(size[1] for size in sizes) + 16 + 2 * (len(lines) - 1)
        x = anchor_x + 12 if anchor_x + 12 + box_w <= width else anchor_x - 12 - box_w
        x = max(0, x)
        y = min(max(0, anchor_y - box_h / 2), max(0, height - box_h))

        self.ink(cr, 1)
        _rounded(cr, x, y, box_w, box_h, 8)
        cr.fill()
        color = self.get_color()
        # Texte en couleur inverse, lisible dans les deux thèmes.
        inverse = 1.0 if (color.red + color.green + color.blue) / 3 < 0.5 else 0.08
        cr.set_source_rgb(inverse, inverse, inverse)
        line_y = y + 8
        for layout, size in zip(layouts, sizes):
            cr.move_to(x + 10, line_y)
            PangoCairo.show_layout(cr, layout)
            line_y += size[1] + 2

    def _draw(self, _area, cr, width, height):
        self.draw(cr, width, height)

    def draw(self, cr, width, height):
        raise NotImplementedError


def _rounded(cr, x, y, width, height, radius):
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()


def _column(cr, x, top, width, bottom):
    """Colonne : bout de donnée arrondi, base carrée sur la ligne de base."""
    radius = min(BAR_RADIUS, width / 2, bottom - top)
    cr.new_sub_path()
    cr.move_to(x, bottom)
    cr.line_to(x, top + radius)
    cr.arc(x + radius, top + radius, radius, math.pi, 1.5 * math.pi)
    cr.arc(x + width - radius, top + radius, radius, 1.5 * math.pi, 0)
    cr.line_to(x + width, bottom)
    cr.close_path()


class BalanceChart(Chart):
    """Évolution du solde : une série, donc pas de légende (le titre la nomme)."""

    def __init__(self):
        super().__init__(240)
        self.points: list[tuple[date, int]] = []

    def set_points(self, points) -> None:
        self.points = points
        self.queue_draw()

    def draw(self, cr, width, height):
        if not self.points:
            return
        values = [value / 100 for _, value in self.points]
        ticks = nice_ticks(min(0, min(values)), max(0, max(values)))
        left = self.axis_width(ticks)
        top, bottom = 12, height - 28
        right = width - 8  # place pour le point final et son anneau

        low, high = ticks[0], ticks[-1]
        to_y = lambda euros: bottom - (euros - low) / (high - low) * (bottom - top)
        count = len(self.points)
        to_x = lambda index: left + (index / max(1, count - 1)) * (right - left)

        self.y_axis(cr, ticks, to_y, right, left)
        self._x_labels(cr, to_x, height, left, right)

        red, green, blue = slot_rgb(SLOT_PRIMARY)
        baseline = to_y(max(low, 0))
        if count > 1:
            cr.move_to(to_x(0), baseline)
            for index, value in enumerate(values):
                cr.line_to(to_x(index), to_y(value))
            cr.line_to(to_x(count - 1), baseline)
            cr.close_path()
            cr.set_source_rgba(red, green, blue, 0.10)
            cr.fill()

            cr.set_line_width(LINE_WIDTH)
            cr.set_line_join(1)  # arrondi
            cr.set_line_cap(1)
            cr.set_source_rgb(red, green, blue)
            for index, value in enumerate(values):
                cr.line_to(to_x(index), to_y(value))
            cr.stroke()

        hover = None
        if self.pointer and left <= self.pointer[0] <= right + 8:
            hover = round((self.pointer[0] - left) / max(1, right - left) * (count - 1))
            hover = max(0, min(count - 1, hover))

        # Le dernier point porte sa valeur : c'est le solde d'aujourd'hui.
        end_x, end_y = to_x(count - 1), to_y(values[-1])
        self._dot(cr, end_x, end_y, (red, green, blue))
        if hover is None:
            # Au-dessus des points qu'il recouvre, ou en dessous s'il manque de place.
            label = format_amount(self.points[-1][1])
            label_width = self.layout(label, True).get_pixel_size()[0]
            covered = [
                to_y(value)
                for index, value in enumerate(values)
                if to_x(index) >= end_x - label_width - 8
            ]
            label_y = min(covered) - 14
            if label_y < 8:
                label_y = max(covered) + 14
            self.text(cr, label, end_x - 4, label_y, "right", 1.0, True)
        else:
            x, y = to_x(hover), to_y(values[hover])
            self.hairline(cr, x, top, x, bottom, BASELINE)
            self._dot(cr, x, y, (red, green, blue))
            day, value = self.points[hover]
            self.tooltip(cr, [format_long(day), format_amount(value)], x, y, width, height)

    def _x_labels(self, cr, to_x, height, left, right):
        starts = [i for i, (day, _) in enumerate(self.points) if day.day == 1]
        with_year = self.points[0][0].year != self.points[-1][0].year
        sample = self.layout(format_short_month(self.points[0][0], with_year)).get_pixel_size()[0]
        room = max(1, int((right - left) / (sample + 20)))
        step = max(1, math.ceil(len(starts) / room))
        for index in starts[::step]:
            x = to_x(index)
            align = "left" if x < left + sample / 2 else "center"
            self.text(cr, format_short_month(self.points[index][0], with_year), x, height - 10, align)

    def _dot(self, cr, x, y, rgb):
        """Point de 8 px entouré d'un anneau de la couleur de fond."""
        cr.save()
        cr.set_operator(0)  # CLEAR : l'anneau laisse voir la carte, quel que soit le thème
        cr.arc(x, y, 6, 0, 2 * math.pi)
        cr.fill()
        cr.restore()
        cr.set_source_rgb(*rgb)
        cr.arc(x, y, 4, 0, 2 * math.pi)
        cr.fill()


class IncomeExpenseChart(Chart):
    """Revenus et dépenses par mois : colonnes groupées avec légende."""

    def __init__(self):
        super().__init__(270)
        self.months: list[tuple[date, int, int]] = []

    def set_months(self, months) -> None:
        self.months = months
        self.queue_draw()

    def _legend(self, cr, y) -> None:
        x = 0
        for label, slot in (("Revenus", SLOT_PRIMARY), ("Dépenses", SLOT_SECONDARY)):
            cr.set_source_rgb(*slot_rgb(slot))
            _rounded(cr, x, y - 5, 10, 10, 2)
            cr.fill()
            self.text(cr, label, x + 16, y, "left", 1.0)
            x += 16 + self.layout(label).get_pixel_size()[0] + 20

    def draw(self, cr, width, height):
        if not self.months:
            return
        self._legend(cr, 10)
        peak = max(max(income, expense) for _, income, expense in self.months) / 100
        ticks = nice_ticks(0, max(peak, 1))
        left = self.axis_width(ticks)
        top, bottom = 36, height - 28
        right = width - 4
        high = ticks[-1]
        to_y = lambda euros: bottom - euros / high * (bottom - top)
        self.y_axis(cr, ticks, to_y, right, left)

        count = len(self.months)
        band = (right - left) / count
        bar = max(2, min(BAR_MAX, (band - 8 - 2) / 2))
        with_year = self.months[0][0].year != self.months[-1][0].year
        label_width = self.layout(format_short_month(self.months[0][0], with_year)).get_pixel_size()[0]
        label_step = max(1, math.ceil((label_width + 12) / band))

        hover = None
        if self.pointer and left <= self.pointer[0] <= right:
            hover = min(count - 1, int((self.pointer[0] - left) / band))
            self.ink(cr, 0.06)
            cr.rectangle(left + hover * band, top, band, bottom - top)
            cr.fill()

        for index, (month, income, expense) in enumerate(self.months):
            center = left + band * (index + 0.5)
            for value, slot, x in (
                (income, SLOT_PRIMARY, center - bar - 1),
                (expense, SLOT_SECONDARY, center + 1),
            ):
                euros = max(0, value) / 100
                if euros > 0:
                    cr.set_source_rgb(*slot_rgb(slot))
                    # Une petite valeur reste visible sans être faussée à zéro.
                    _column(cr, x, min(to_y(euros), bottom - 1), bar, bottom)
                    cr.fill()
            if (count - 1 - index) % label_step == 0:
                self.text(cr, format_short_month(month, with_year), center, height - 10, "center")

        if hover is not None:
            month, income, expense = self.months[hover]
            self.tooltip(
                cr,
                [
                    format_month(month).capitalize(),
                    f"Revenus : {format_amount(income)}",
                    f"Dépenses : {format_amount(expense)}",
                    f"Épargné : {format_amount(income - expense, signed=True)}",
                ],
                left + band * (hover + 0.5) + bar,
                top + 50,
                width,
                height,
            )


class BarMark(Gtk.DrawingArea):
    """Barre horizontale d'une ligne de classement."""

    def __init__(self, fraction: float, slot: int = SLOT_PRIMARY):
        super().__init__(hexpand=True, content_height=8)
        self.fraction = max(0.0, min(1.0, fraction))
        self.slot = slot
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width, height):
        bar = max(4, width * self.fraction)
        cr.set_source_rgb(*slot_rgb(self.slot))
        radius = min(BAR_RADIUS, height / 2)
        cr.new_sub_path()
        cr.move_to(0, 0)
        cr.arc(bar - radius, radius, radius, -math.pi / 2, 0)
        cr.arc(bar - radius, height - radius, radius, 0, math.pi / 2)
        cr.line_to(0, height)
        cr.close_path()
        cr.fill()
