"""Montants : stockés en centimes entiers, jamais en flottants."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

NARROW_NBSP = " "
MINUS = "−"


def parse_amount(text: str) -> int:
    """Convertit un montant saisi ou importé en centimes.

    Accepte « 1 234,56 », « 1.234,56 », « 1,234.56 », « -12,5 », « 12,50- » et « 12 € ».
    Lève ValueError si le texte n'est pas un montant.
    """
    original = text
    cleaned = re.sub(r"[\s  '€]|EUR", "", text.strip(), flags=re.IGNORECASE)
    cleaned = cleaned.replace(MINUS, "-")

    negative = False
    if cleaned.endswith("-"):
        negative = True
        cleaned = cleaned[:-1]
    if cleaned.startswith(("-", "+")):
        negative = negative or cleaned[0] == "-"
        cleaned = cleaned[1:]

    if not re.fullmatch(r"[\d.,]*\d[\d.,]*", cleaned):
        raise ValueError(f"Montant invalide : {original!r}")

    # Le dernier séparateur est décimal, sauf s'il sépare clairement des milliers :
    # « 1.234 » vaut 1234 et « 1.234.567 » vaut 1234567, mais « 1,234 » reste 1,234.
    last_comma, last_dot = cleaned.rfind(","), cleaned.rfind(".")
    separator_pos = max(last_comma, last_dot)
    if separator_pos >= 0:
        integer, decimals = cleaned[:separator_pos], cleaned[separator_pos + 1 :]
        only_one_separator = cleaned.count(",") + cleaned.count(".") == 1
        if only_one_separator and cleaned[separator_pos] == "." and len(decimals) == 3:
            integer, decimals = integer + decimals, ""
        elif not only_one_separator and len(decimals) == 3 and cleaned.count(cleaned[separator_pos]) > 1:
            integer, decimals = integer + decimals, ""
        integer = integer.replace(",", "").replace(".", "")
        cleaned = f"{integer or '0'}.{decimals or '0'}"

    try:
        cents = (Decimal(cleaned) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise ValueError(f"Montant invalide : {original!r}") from error
    return -int(cents) if negative else int(cents)


def format_amount(cents: int, signed: bool = False, decimals: bool = True) -> str:
    """Formate des centimes à la française : « 1 234,56 € »."""
    absolute = abs(cents)
    if decimals:
        euros, remainder = divmod(absolute, 100)
        suffix = f",{remainder:02d}"
    else:
        euros, suffix = (absolute + 50) // 100, ""
    grouped = f"{euros:,}".replace(",", NARROW_NBSP)
    sign = MINUS if cents < 0 else ("+" if signed and cents > 0 else "")
    return f"{sign}{grouped}{suffix} €"


def input_amount(cents: int) -> str:
    """Valeur à préremplir dans un champ de saisie."""
    euros, remainder = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}{euros},{remainder:02d}"
