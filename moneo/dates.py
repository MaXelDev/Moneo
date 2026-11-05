"""Dates et mois, sans dépendre de la locale du système."""

import calendar
from datetime import date, timedelta

MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
SHORT_MONTHS = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)


def add_months(day: date, months: int, anchor_day: int | None = None) -> date:
    """Ajoute des mois en ramenant au dernier jour si le mois est plus court."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    wanted = anchor_day if anchor_day is not None else day.day
    return date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def months_between(start: date, end: date) -> int:
    """Nombre de mois calendaires de start à end (peut être négatif)."""
    return (end.year - start.year) * 12 + end.month - start.month


def iter_months(start: date, end: date):
    """Premier jour de chaque mois de start à end inclus."""
    current = month_start(start)
    while current <= end:
        yield current
        current = add_months(current, 1)


def iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def format_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def format_long(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def format_month(day: date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


def format_short_month(day: date, with_year: bool = False) -> str:
    label = SHORT_MONTHS[day.month - 1]
    return f"{label} {day.year % 100:02d}" if with_year else label
