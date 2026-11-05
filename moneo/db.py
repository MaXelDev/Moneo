"""Stockage SQLite local et règles métier. Ce module ne dépend pas de GTK."""

import hashlib
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .dates import add_months, iter_days

APPLICATION_ID = 0x4D4F4E45  # « MONE » : identifie une base Monéo
SCHEMA_VERSION = 1
PALETTE_SIZE = 8

SCHEMA = """
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE categories (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL COLLATE NOCASE UNIQUE,
    kind         TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    color        INTEGER NOT NULL DEFAULT 0,
    budget_cents INTEGER CHECK (budget_cents IS NULL OR budget_cents > 0)
);
CREATE TABLE recurring (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    frequency    TEXT NOT NULL CHECK (frequency IN ('weekly', 'monthly', 'yearly')),
    start_date   TEXT NOT NULL,
    occurrences  INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE transactions (
    id           INTEGER PRIMARY KEY,
    date         TEXT NOT NULL,
    label        TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    recurring_id INTEGER REFERENCES recurring(id) ON DELETE SET NULL,
    import_key   TEXT UNIQUE
);
CREATE INDEX transactions_date ON transactions(date);
CREATE INDEX transactions_category ON transactions(category_id);
CREATE TABLE goals (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    target_cents INTEGER NOT NULL CHECK (target_cents > 0),
    saved_cents  INTEGER NOT NULL DEFAULT 0 CHECK (saved_cents >= 0),
    deadline     TEXT
);
"""

DEFAULT_CATEGORIES = (
    ("Courses", "expense"),
    ("Logement", "expense"),
    ("Transport", "expense"),
    ("Abonnements", "expense"),
    ("Restaurants", "expense"),
    ("Loisirs", "expense"),
    ("Santé", "expense"),
    ("Salaire", "income"),
    ("Autres revenus", "income"),
)

# Classement d'une opération : une catégorie décide de son camp, ce qui fait
# qu'un remboursement réduit les dépenses au lieu de compter comme un revenu.
IS_INCOME = "(c.kind = 'income' OR (c.kind IS NULL AND t.amount_cents > 0))"
IS_EXPENSE = "(c.kind = 'expense' OR (c.kind IS NULL AND t.amount_cents < 0))"


class BackupError(Exception):
    """Le fichier choisi n'est pas une sauvegarde Monéo valide."""


@dataclass(frozen=True)
class ImportedTransaction:
    date: date
    label: str
    amount_cents: int
    bank_id: str | None = None


@dataclass(frozen=True)
class ImportResult:
    added: int = 0
    duplicates: int = 0
    reconciled: int = 0


def fold_text(text: str) -> str:
    """Retire accents et majuscules, pour une recherche tolérante."""
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char)
    )
    return without_accents.casefold()


def normalize_label(label: str) -> str:
    """Rend comparables « CB MONOPRIX 12/03 » et « Cb Monoprix 28/03 »."""
    without_digits = re.sub(r"[\d/.\-_*#:]+", " ", fold_text(label))
    return " ".join(without_digits.split())


def occurrence_date(start: date, frequency: str, index: int) -> date:
    if frequency == "weekly":
        return start + timedelta(weeks=index)
    months = index if frequency == "monthly" else index * 12
    return add_months(start, months, anchor_day=start.day)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.touch(mode=0o600, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            with self.conn:
                self.conn.executescript(
                    "BEGIN;"
                    + SCHEMA
                    + f"PRAGMA application_id = {APPLICATION_ID};"
                    + f"PRAGMA user_version = {SCHEMA_VERSION};"
                    + "COMMIT;"
                )
                for index, (name, kind) in enumerate(DEFAULT_CATEGORIES):
                    self.conn.execute(
                        "INSERT INTO categories (name, kind, color) VALUES (?, ?, ?)",
                        (name, kind, index % PALETTE_SIZE),
                    )
        elif version > SCHEMA_VERSION:
            raise BackupError("Cette base a été créée par une version plus récente de Monéo.")

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- Solde

    def has_opening_balance(self) -> bool:
        row = self.conn.execute("SELECT 1 FROM settings WHERE key = 'opening_balance'").fetchone()
        return row is not None

    def opening_balance(self) -> int:
        row = self.conn.execute("SELECT value FROM settings WHERE key = 'opening_balance'").fetchone()
        return int(row["value"]) if row else 0

    def set_current_balance(self, cents: int, today: date | None = None) -> None:
        """Déduit le solde de départ pour que le solde du jour vaille `cents`."""
        today = today or date.today()
        total = self.conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE date <= ?",
            (today.isoformat(),),
        ).fetchone()[0]
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES ('opening_balance', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(cents - total),),
            )

    def balance(self, as_of: date | None = None) -> int:
        as_of = as_of or date.today()
        total = self.conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE date <= ?",
            (as_of.isoformat(),),
        ).fetchone()[0]
        return self.opening_balance() + total

    def balance_series(self, start: date, end: date) -> list[tuple[date, int]]:
        """Solde en fin de journée pour chaque jour de start à end."""
        running = self.balance(start - timedelta(days=1))
        changes = {
            row["date"]: row["total"]
            for row in self.conn.execute(
                "SELECT date, SUM(amount_cents) AS total FROM transactions "
                "WHERE date BETWEEN ? AND ? GROUP BY date",
                (start.isoformat(), end.isoformat()),
            )
        }
        series = []
        for day in iter_days(start, end):
            running += changes.get(day.isoformat(), 0)
            series.append((day, running))
        return series

    # ----------------------------------------------------------- Catégories

    def categories(self, kind: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM categories"
        params: tuple = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        return self.conn.execute(query + " ORDER BY name COLLATE NOCASE", params).fetchall()

    def next_color(self) -> int:
        """Premier emplacement de couleur le moins utilisé, dans l'ordre fixe."""
        counts = [0] * PALETTE_SIZE
        for row in self.conn.execute("SELECT color FROM categories"):
            counts[row["color"] % PALETTE_SIZE] += 1
        return counts.index(min(counts))

    def save_category(self, category_id, name, kind, color, budget_cents) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Donne un nom à la catégorie.")
        if budget_cents is not None and budget_cents <= 0:
            raise ValueError("Le budget doit être supérieur à zéro.")
        if kind == "income":
            budget_cents = None
        try:
            with self.conn:
                if category_id is None:
                    self.conn.execute(
                        "INSERT INTO categories (name, kind, color, budget_cents) VALUES (?, ?, ?, ?)",
                        (name, kind, color, budget_cents),
                    )
                else:
                    self.conn.execute(
                        "UPDATE categories SET name = ?, kind = ?, color = ?, budget_cents = ? WHERE id = ?",
                        (name, kind, color, budget_cents, category_id),
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"La catégorie « {name} » existe déjà.") from error

    def delete_category(self, category_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    def category_usage(self, category_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,)
        ).fetchone()[0]

    # ------------------------------------------------------------ Opérations

    def save_transaction(self, transaction_id, day, label, amount_cents, category_id) -> int:
        """Enregistre une opération et renvoie le nombre d'opérations similaires classées.

        Choisir une catégorie pour une opération qui n'en avait pas classe aussi
        les autres opérations sans catégorie portant le même libellé.
        """
        label = label.strip()
        if not label:
            raise ValueError("Donne un libellé à l'opération.")
        if amount_cents == 0:
            raise ValueError("Le montant ne peut pas être nul.")
        with self.conn:
            if transaction_id is None:
                self.conn.execute(
                    "INSERT INTO transactions (date, label, amount_cents, category_id) VALUES (?, ?, ?, ?)",
                    (day.isoformat(), label, amount_cents, category_id),
                )
                return 0
            previous = self.conn.execute(
                "SELECT category_id FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            self.conn.execute(
                "UPDATE transactions SET date = ?, label = ?, amount_cents = ?, category_id = ? WHERE id = ?",
                (day.isoformat(), label, amount_cents, category_id, transaction_id),
            )
            if previous is None or previous["category_id"] is not None or category_id is None:
                return 0
            target = normalize_label(label)
            similar = [
                row["id"]
                for row in self.conn.execute(
                    "SELECT id, label FROM transactions WHERE category_id IS NULL"
                )
                if normalize_label(row["label"]) == target
            ]
            self.conn.executemany(
                "UPDATE transactions SET category_id = ? WHERE id = ?",
                [(category_id, row_id) for row_id in similar],
            )
            return len(similar)

    def delete_transaction(self, transaction_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    def transactions(
        self,
        start: date | None = None,
        end: date | None = None,
        search: str = "",
        category_id: int | None = None,
        uncategorized: bool = False,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        query = (
            "SELECT t.*, c.name AS category_name, c.color AS category_color, c.kind AS category_kind "
            "FROM transactions t LEFT JOIN categories c ON c.id = t.category_id WHERE 1 = 1"
        )
        params: list = []
        if start:
            query += " AND t.date >= ?"
            params.append(start.isoformat())
        if end:
            query += " AND t.date <= ?"
            params.append(end.isoformat())
        if category_id is not None:
            query += " AND t.category_id = ?"
            params.append(category_id)
        if uncategorized:
            query += " AND t.category_id IS NULL"
        query += " ORDER BY t.date DESC, t.id DESC"
        rows = self.conn.execute(query, params).fetchall()
        if search:
            # Filtré ici car LIKE ignore mal les accents hors ASCII.
            needle = fold_text(search.strip())
            rows = [
                row
                for row in rows
                if needle in fold_text(row["label"])
                or (row["category_name"] and needle in fold_text(row["category_name"]))
            ]
        return rows[:limit] if limit else rows

    def earliest_transaction_date(self) -> date | None:
        value = self.conn.execute("SELECT MIN(date) FROM transactions").fetchone()[0]
        return date.fromisoformat(value) if value else None

    def month_totals(self, start: date, end: date) -> tuple[int, int]:
        row = self.conn.execute(
            f"""SELECT
                COALESCE(SUM(CASE WHEN {IS_INCOME} THEN t.amount_cents END), 0) AS income,
                COALESCE(SUM(CASE WHEN {IS_EXPENSE} THEN -t.amount_cents END), 0) AS expense
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.date BETWEEN ? AND ?""",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return row["income"], row["expense"]

    def monthly_summary(self, start: date, end: date) -> dict[str, tuple[int, int]]:
        """Revenus et dépenses par mois (clé « AAAA-MM »)."""
        rows = self.conn.execute(
            f"""SELECT substr(t.date, 1, 7) AS month,
                COALESCE(SUM(CASE WHEN {IS_INCOME} THEN t.amount_cents END), 0) AS income,
                COALESCE(SUM(CASE WHEN {IS_EXPENSE} THEN -t.amount_cents END), 0) AS expense
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.date BETWEEN ? AND ? GROUP BY month""",
            (start.isoformat(), end.isoformat()),
        )
        return {row["month"]: (row["income"], row["expense"]) for row in rows}

    def category_spending(self, start: date, end: date) -> list[sqlite3.Row]:
        """Dépenses nettes par catégorie, de la plus grosse à la plus petite."""
        return self.conn.execute(
            f"""SELECT c.id, c.name, c.color, SUM(-t.amount_cents) AS spent
            FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.date BETWEEN ? AND ? AND {IS_EXPENSE}
            GROUP BY c.id HAVING spent > 0 ORDER BY spent DESC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def budget_status(self, start: date, end: date) -> list[sqlite3.Row]:
        """Catégories avec budget et leur dépense nette sur la période."""
        return self.conn.execute(
            """SELECT c.*, COALESCE(SUM(-t.amount_cents), 0) AS spent
            FROM categories c
            LEFT JOIN transactions t ON t.category_id = c.id AND t.date BETWEEN ? AND ?
            WHERE c.budget_cents IS NOT NULL AND c.kind = 'expense'
            GROUP BY c.id ORDER BY CAST(spent AS REAL) / c.budget_cents DESC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    # ---------------------------------------------------------------- Import

    def import_transactions(self, items: list[ImportedTransaction]) -> ImportResult:
        """Importe sans doublon, même si le même relevé est importé deux fois.

        Une opération déjà saisie à la main ou créée par une récurrence (même
        montant, à 3 jours près) est rapprochée au lieu d'être dupliquée.
        """
        known_categories = {
            normalize_label(row["label"]): row["category_id"]
            for row in self.conn.execute(
                "SELECT label, category_id FROM transactions "
                "WHERE category_id IS NOT NULL ORDER BY date, id"
            )
        }
        added = duplicates = reconciled = 0
        seen: dict[str, int] = {}
        with self.conn:
            for item in items:
                normalized = normalize_label(item.label)
                if item.bank_id:
                    key = f"bank:{item.bank_id}"
                else:
                    # Deux cafés identiques le même jour restent deux opérations :
                    # le rang dans le relevé fait partie de la clé.
                    base = f"{item.date.isoformat()}|{item.amount_cents}|{normalized}"
                    rank = seen.get(base, 0)
                    seen[base] = rank + 1
                    key = hashlib.sha256(f"{base}|{rank}".encode()).hexdigest()

                if self.conn.execute(
                    "SELECT 1 FROM transactions WHERE import_key = ?", (key,)
                ).fetchone():
                    duplicates += 1
                    continue

                match = self.conn.execute(
                    """SELECT id FROM transactions
                    WHERE import_key IS NULL AND amount_cents = ?
                      AND date BETWEEN ? AND ?
                    ORDER BY ABS(julianday(date) - julianday(?)), id LIMIT 1""",
                    (
                        item.amount_cents,
                        (item.date - timedelta(days=3)).isoformat(),
                        (item.date + timedelta(days=3)).isoformat(),
                        item.date.isoformat(),
                    ),
                ).fetchone()
                if match:
                    self.conn.execute(
                        "UPDATE transactions SET import_key = ?, date = ? WHERE id = ?",
                        (key, item.date.isoformat(), match["id"]),
                    )
                    reconciled += 1
                    continue

                self.conn.execute(
                    "INSERT INTO transactions (date, label, amount_cents, category_id, import_key) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        item.date.isoformat(),
                        item.label.strip(),
                        item.amount_cents,
                        known_categories.get(normalized),
                        key,
                    ),
                )
                added += 1
        return ImportResult(added, duplicates, reconciled)

    # ----------------------------------------------------------- Récurrences

    def recurring(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT r.*, c.name AS category_name, c.color AS category_color "
            "FROM recurring r LEFT JOIN categories c ON c.id = r.category_id "
            "ORDER BY r.active DESC, r.label COLLATE NOCASE"
        ).fetchall()

    @staticmethod
    def next_occurrence(row: sqlite3.Row) -> date:
        return occurrence_date(
            date.fromisoformat(row["start_date"]), row["frequency"], row["occurrences"]
        )

    def upcoming(self, days: int = 30, today: date | None = None) -> list[tuple[date, sqlite3.Row]]:
        today = today or date.today()
        limit = today + timedelta(days=days)
        items = []
        for row in self.recurring():
            if row["active"] and (day := self.next_occurrence(row)) <= limit:
                items.append((day, row))
        return sorted(items, key=lambda item: item[0])

    def save_recurring(self, recurring_id, label, amount_cents, category_id, frequency, next_date) -> None:
        label = label.strip()
        if not label:
            raise ValueError("Donne un libellé à cette opération.")
        if amount_cents == 0:
            raise ValueError("Le montant ne peut pas être nul.")
        with self.conn:
            if recurring_id is None:
                self.conn.execute(
                    "INSERT INTO recurring (label, amount_cents, category_id, frequency, start_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (label, amount_cents, category_id, frequency, next_date.isoformat()),
                )
                return
            # La prochaine date devient le nouveau point de départ du calendrier.
            self.conn.execute(
                "UPDATE recurring SET label = ?, amount_cents = ?, category_id = ?, "
                "frequency = ?, start_date = ?, occurrences = 0 WHERE id = ?",
                (label, amount_cents, category_id, frequency, next_date.isoformat(), recurring_id),
            )

    def delete_recurring(self, recurring_id: int) -> None:
        """Arrête la récurrence ; les opérations déjà créées sont conservées."""
        with self.conn:
            self.conn.execute("DELETE FROM recurring WHERE id = ?", (recurring_id,))

    def set_recurring_active(self, recurring_id: int, active: bool, today: date | None = None) -> None:
        """À la reprise, les échéances passées pendant la pause ne sont pas créées."""
        today = today or date.today()
        row = self.conn.execute("SELECT * FROM recurring WHERE id = ?", (recurring_id,)).fetchone()
        occurrences = row["occurrences"]
        if active and not row["active"]:
            start = date.fromisoformat(row["start_date"])
            while occurrence_date(start, row["frequency"], occurrences) < today:
                occurrences += 1
        with self.conn:
            self.conn.execute(
                "UPDATE recurring SET active = ?, occurrences = ? WHERE id = ?",
                (int(active), occurrences, recurring_id),
            )

    def generate_due(self, today: date | None = None) -> int:
        """Crée les opérations échues, y compris si l'appli n'a pas été ouverte."""
        today = today or date.today()
        created = 0
        with self.conn:
            for row in self.conn.execute(
                "SELECT * FROM recurring WHERE active = 1"
            ).fetchall():
                start = date.fromisoformat(row["start_date"])
                occurrences = row["occurrences"]
                while (day := occurrence_date(start, row["frequency"], occurrences)) <= today:
                    self.conn.execute(
                        "INSERT INTO transactions (date, label, amount_cents, category_id, recurring_id) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (day.isoformat(), row["label"], row["amount_cents"], row["category_id"], row["id"]),
                    )
                    occurrences += 1
                    created += 1
                if occurrences != row["occurrences"]:
                    self.conn.execute(
                        "UPDATE recurring SET occurrences = ? WHERE id = ?", (occurrences, row["id"])
                    )
        return created

    # -------------------------------------------------------------- Objectifs

    def goals(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM goals ORDER BY saved_cents >= target_cents, deadline IS NULL, deadline, name"
        ).fetchall()

    def total_saved(self) -> int:
        return self.conn.execute("SELECT COALESCE(SUM(saved_cents), 0) FROM goals").fetchone()[0]

    def save_goal(self, goal_id, name, target_cents, deadline) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Donne un nom à cet objectif.")
        if target_cents <= 0:
            raise ValueError("Le montant visé doit être supérieur à zéro.")
        iso = deadline.isoformat() if deadline else None
        with self.conn:
            if goal_id is None:
                self.conn.execute(
                    "INSERT INTO goals (name, target_cents, deadline) VALUES (?, ?, ?)",
                    (name, target_cents, iso),
                )
            else:
                self.conn.execute(
                    "UPDATE goals SET name = ?, target_cents = ?, deadline = ? WHERE id = ?",
                    (name, target_cents, iso, goal_id),
                )

    def adjust_goal(self, goal_id: int, delta_cents: int) -> None:
        row = self.conn.execute("SELECT saved_cents FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row["saved_cents"] + delta_cents < 0:
            raise ValueError("Tu ne peux pas retirer plus que le montant mis de côté.")
        with self.conn:
            self.conn.execute(
                "UPDATE goals SET saved_cents = saved_cents + ? WHERE id = ?", (delta_cents, goal_id)
            )

    def delete_goal(self, goal_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    # ------------------------------------------------------------ Sauvegarde

    def export_backup(self, destination: Path | str) -> None:
        """Copie cohérente de la base, écrite d'un bloc et lisible par toi seul."""
        destination = Path(destination)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.unlink(missing_ok=True)
        temporary.touch(mode=0o600)
        try:
            target = sqlite3.connect(temporary)
            try:
                self.conn.backup(target)
            finally:
                target.close()
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def restore_backup(self, source: Path | str) -> None:
        """Remplace toutes les données, après contrôle du fichier et copie de sécurité."""
        try:
            backup = sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True)
        except sqlite3.Error as error:
            raise BackupError("Ce fichier ne peut pas être ouvert.") from error
        try:
            try:
                application_id = backup.execute("PRAGMA application_id").fetchone()[0]
                version = backup.execute("PRAGMA user_version").fetchone()[0]
                integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
            except sqlite3.DatabaseError as error:
                raise BackupError("Ce fichier n'est pas une sauvegarde Monéo.") from error
            if application_id != APPLICATION_ID:
                raise BackupError("Ce fichier n'est pas une sauvegarde Monéo.")
            if version > SCHEMA_VERSION:
                raise BackupError("Cette sauvegarde vient d'une version plus récente de Monéo.")
            if integrity != "ok":
                raise BackupError("Cette sauvegarde est endommagée.")
            if str(self.path) != ":memory:":
                self.export_backup(self.path.with_name(self.path.name + ".avant-restauration"))
            backup.backup(self.conn)
        finally:
            backup.close()
