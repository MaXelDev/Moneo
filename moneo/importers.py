"""Lecture des relevés bancaires CSV et OFX. Ce module ne dépend pas de GTK."""

import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from .db import ImportedTransaction
from .money import parse_amount

# Jour avant mois, comme dans les exports des banques françaises.
DATE_FORMATS = (
    "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y",
    "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d",
)
DELIMITERS = (";", "\t", ",", "|")
HEADER_SEARCH_ROWS = 30

DATE_WORDS = ("date operation", "date", "jour")
LABEL_WORDS = ("libelle", "intitule", "description", "designation", "detail", "nature", "memo", "label")
AMOUNT_WORDS = ("montant", "valeur eur", "amount", "somme")
DEBIT_WORDS = ("debit", "depense", "sortie")
CREDIT_WORDS = ("credit", "recette", "entree")


def decode(data: bytes) -> str:
    """Les banques françaises exportent souvent en Windows-1252 plutôt qu'en UTF-8."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_date(text: str) -> date:
    candidate = text.strip().strip('"')
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(candidate[:10], pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Date invalide : {text!r}")


def _simplify(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.casefold())
    return " ".join(
        "".join(char for char in stripped if not unicodedata.combining(char)).replace("'", " ").split()
    )


def _is_date(text: str) -> bool:
    try:
        parse_date(text)
        return True
    except ValueError:
        return False


def _detect_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()][:50]
    best, best_score = ";", (0, 0)
    for delimiter in DELIMITERS:
        widths = Counter(len(row) for row in csv.reader(lines, delimiter=delimiter) if len(row) >= 2)
        if not widths:
            continue
        width, frequency = max(widths.items(), key=lambda item: (item[1], item[0]))
        if (frequency, width) > best_score:
            best, best_score = delimiter, (frequency, width)
    return best


@dataclass
class CsvMapping:
    """Index de colonne pour chaque champ ; None si la colonne n'existe pas."""

    date: int | None = None
    label: int | None = None
    amount: int | None = None
    debit: int | None = None
    credit: int | None = None

    def is_complete(self) -> bool:
        has_amount = self.amount is not None or self.debit is not None or self.credit is not None
        return self.date is not None and self.label is not None and has_amount


@dataclass
class CsvFile:
    headers: list[str]
    rows: list[list[str]]
    mapping: CsvMapping = field(default_factory=CsvMapping)


def _find(headers: list[str], words: tuple[str, ...], taken: set[int]) -> int | None:
    for word in words:
        for index, header in enumerate(headers):
            if index not in taken and word in header:
                return index
    return None


def guess_mapping(headers: list[str]) -> CsvMapping:
    simplified = [_simplify(header) for header in headers]
    taken: set[int] = set()

    def pick(words):
        index = _find(simplified, words, taken)
        if index is not None:
            taken.add(index)
        return index

    mapping = CsvMapping()
    mapping.date = pick(DATE_WORDS)
    mapping.debit = pick(DEBIT_WORDS)
    mapping.credit = pick(CREDIT_WORDS)
    mapping.amount = pick(AMOUNT_WORDS)
    mapping.label = pick(LABEL_WORDS)
    return mapping


def read_csv(data: bytes) -> CsvFile:
    """Trouve le tableau d'opérations, même précédé de lignes d'en-tête de banque."""
    text = decode(data)
    delimiter = _detect_delimiter(text)
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise ValueError("Ce fichier ne contient aucune donnée.")

    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        mapping = guess_mapping(row)
        if len(row) >= 2 and mapping.date is not None and (
            mapping.amount is not None or mapping.debit is not None or mapping.credit is not None
        ):
            return CsvFile(row, rows[index + 1 :], mapping)

    # Pas de ligne de titres : on repère les colonnes d'après leur contenu.
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if len(row) >= 2 and any(_is_date(cell) for cell in row):
            headers = [f"Colonne {number + 1}" for number in range(len(row))]
            return CsvFile(headers, rows[index:], _guess_from_content(row))
    raise ValueError("Aucune colonne de date trouvée dans ce fichier.")


def _guess_from_content(row: list[str]) -> CsvMapping:
    mapping = CsvMapping()
    for index, cell in enumerate(row):
        if mapping.date is None and _is_date(cell):
            mapping.date = index
        elif mapping.amount is None and _looks_like_amount(cell):
            mapping.amount = index
        elif mapping.label is None and re.search(r"[^\W\d_]", cell):
            mapping.label = index
    return mapping


def _looks_like_amount(cell: str) -> bool:
    try:
        parse_amount(cell)
        return True
    except ValueError:
        return False


def _cell(row: list[str], index: int | None) -> str:
    return row[index] if index is not None and index < len(row) else ""


def parse_csv_rows(
    csv_file: CsvFile, mapping: CsvMapping
) -> tuple[list[ImportedTransaction], int]:
    """Renvoie les opérations lues et le nombre de lignes ignorées."""
    items: list[ImportedTransaction] = []
    skipped = 0
    for row in csv_file.rows:
        try:
            day = parse_date(_cell(row, mapping.date))
            label = _cell(row, mapping.label).strip()
            if not label:
                raise ValueError("Libellé vide")
            amount_text = _cell(row, mapping.amount)
            if amount_text:
                amount = parse_amount(amount_text)
            else:
                # Débit et crédit séparés : le signe vient de la colonne.
                debit, credit = _cell(row, mapping.debit), _cell(row, mapping.credit)
                amount = -abs(parse_amount(debit)) if debit else abs(parse_amount(credit))
            if amount == 0:
                raise ValueError("Montant nul")
        except ValueError:
            skipped += 1
            continue
        items.append(ImportedTransaction(day, label, amount))
    return items, skipped


def _ofx_value(block: str, tag: str) -> str:
    """Le SGML d'OFX 1.x ne ferme pas ses balises : la valeur va jusqu'au prochain « < »."""
    match = re.search(rf"<{tag}>\s*([^<\r\n]*)", block, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_ofx(data: bytes) -> tuple[list[ImportedTransaction], int]:
    """Renvoie les opérations lues et le nombre de blocs ignorés."""
    text = decode(data)
    blocks = re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|\Z)", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        raise ValueError("Aucune opération trouvée dans ce fichier OFX.")
    items: list[ImportedTransaction] = []
    skipped = 0
    for block in blocks:
        try:
            raw_date = _ofx_value(block, "DTPOSTED")[:8]
            day = datetime.strptime(raw_date, "%Y%m%d").date()
            amount = parse_amount(_ofx_value(block, "TRNAMT"))
            label = _ofx_value(block, "NAME") or _ofx_value(block, "MEMO")
            if not label or amount == 0:
                raise ValueError("Opération incomplète")
        except ValueError:
            skipped += 1
            continue
        items.append(ImportedTransaction(day, label, amount, _ofx_value(block, "FITID") or None))
    return items, skipped
