import tempfile
import unittest
from datetime import date
from pathlib import Path

from moneo.dates import add_months
from moneo.db import BackupError, Database, ImportedTransaction
from moneo.importers import guess_mapping, parse_csv_rows, parse_date, parse_ofx, read_csv
from moneo.money import format_amount, input_amount, parse_amount


class MoneyTests(unittest.TestCase):
    def test_parse_formats(self):
        cases = {
            "12": 1200,
            "12,5": 1250,
            "12.50": 1250,
            "1 234,56": 123456,
            "1 234,56 €": 123456,
            "1.234,56": 123456,
            "1,234.56": 123456,
            "1.234.567": 123456700,
            "-12,50": -1250,
            "−12,50": -1250,
            "12,50-": -1250,
            "+7": 700,
            "0,005": 1,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), expected)

    def test_parse_rejects_garbage(self):
        for text in ("", "abc", "12a", ",", "--3", "1 2 x"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount(text)

    def test_format(self):
        self.assertEqual(format_amount(123456), "1 234,56 €")
        self.assertEqual(format_amount(-5), "−0,05 €")
        self.assertEqual(format_amount(100, signed=True), "+1,00 €")
        self.assertEqual(format_amount(149, decimals=False), "1 €")
        self.assertEqual(parse_amount(input_amount(-123456)), -123456)


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.courses = next(c["id"] for c in self.db.categories() if c["name"] == "Courses")
        self.salary = next(c["id"] for c in self.db.categories() if c["name"] == "Salaire")

    def test_set_current_balance_accounts_for_history(self):
        today = date(2026, 3, 15)
        self.db.save_transaction(None, date(2026, 3, 1), "Courses", -5000, self.courses)
        self.db.set_current_balance(100000, today)
        self.assertEqual(self.db.balance(today), 100000)
        self.assertEqual(self.db.opening_balance(), 105000)
        self.assertEqual(self.db.balance(date(2026, 2, 1)), 105000)

    def test_future_operations_do_not_change_todays_balance(self):
        today = date(2026, 3, 15)
        self.db.save_transaction(None, date(2026, 3, 20), "Plus tard", -5000, None)
        self.assertEqual(self.db.balance(today), 0)
        self.assertEqual(self.db.balance(date(2026, 3, 20)), -5000)

    def test_series_has_every_day(self):
        self.db.set_current_balance(1000, date(2026, 1, 1))
        self.db.save_transaction(None, date(2026, 1, 3), "x", -100, None)
        series = self.db.balance_series(date(2026, 1, 2), date(2026, 1, 4))
        self.assertEqual([v for _, v in series], [1000, 900, 900])

    def test_refund_reduces_spending_instead_of_counting_as_income(self):
        start, end = date(2026, 3, 1), date(2026, 3, 31)
        self.db.save_transaction(None, date(2026, 3, 2), "Achat", -10000, self.courses)
        self.db.save_transaction(None, date(2026, 3, 3), "Remboursement", 2500, self.courses)
        self.db.save_transaction(None, date(2026, 3, 4), "Paie", 200000, self.salary)
        self.assertEqual(self.db.month_totals(start, end), (200000, 7500))
        self.assertEqual(self.db.category_spending(start, end)[0]["spent"], 7500)

    def test_budget_status(self):
        self.db.save_category(self.courses, "Courses", "expense", 0, 30000)
        self.db.save_transaction(None, date(2026, 3, 2), "Achat", -33000, self.courses)
        self.db.save_transaction(None, date(2026, 4, 2), "Autre mois", -100, self.courses)
        rows = self.db.budget_status(date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual([(r["name"], r["spent"]) for r in rows], [("Courses", 33000)])

    def test_categorizing_applies_to_similar_uncategorized(self):
        self.db.save_transaction(None, date(2026, 3, 1), "CB MONOPRIX 01/03", -100, None)
        self.db.save_transaction(None, date(2026, 3, 8), "CB Monoprix 08/03", -200, None)
        self.db.save_transaction(None, date(2026, 3, 9), "CB AUTRE", -300, None)
        matches = self.db.transactions(search="01/03")
        self.assertEqual(len(matches), 1)
        first = matches[0]["id"]
        count = self.db.save_transaction(first, date(2026, 3, 1), "CB MONOPRIX 01/03", -100, self.courses)
        self.assertEqual(count, 1)
        self.assertEqual(len(self.db.transactions(uncategorized=True)), 1)

    def test_deleting_category_keeps_operations(self):
        self.db.save_transaction(None, date(2026, 3, 2), "Achat", -100, self.courses)
        self.db.delete_category(self.courses)
        rows = self.db.transactions()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["category_id"])

    def test_duplicate_category_is_refused(self):
        with self.assertRaises(ValueError):
            self.db.save_category(None, "courses", "expense", 0, None)

    def test_search_ignores_accents_and_case(self):
        self.db.save_transaction(None, date(2026, 3, 2), "Théâtre", -100, None)
        self.assertEqual(len(self.db.transactions(search="theatre")), 1)


class RecurringTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def labels_and_dates(self):
        return sorted(row["date"] for row in self.db.transactions())

    def test_catches_up_and_does_not_repeat(self):
        self.db.save_recurring(None, "Loyer", -80000, None, "monthly", date(2026, 1, 5))
        self.assertEqual(self.db.generate_due(date(2026, 3, 10)), 3)
        self.assertEqual(self.db.generate_due(date(2026, 3, 10)), 0)
        self.assertEqual(self.labels_and_dates(), ["2026-01-05", "2026-02-05", "2026-03-05"])

    def test_day_31_stays_anchored_through_short_months(self):
        self.db.save_recurring(None, "Paie", 100, None, "monthly", date(2026, 1, 31))
        self.db.generate_due(date(2026, 3, 31))
        self.assertEqual(self.labels_and_dates(), ["2026-01-31", "2026-02-28", "2026-03-31"])

    def test_weekly_and_yearly(self):
        self.db.save_recurring(None, "Hebdo", -1, None, "weekly", date(2026, 1, 1))
        self.db.save_recurring(None, "Annuel", -1, None, "yearly", date(2024, 2, 29))
        self.db.generate_due(date(2026, 1, 15))
        self.assertEqual(
            self.labels_and_dates(),
            ["2024-02-29", "2025-02-28", "2026-01-01", "2026-01-08", "2026-01-15"],
        )

    def test_deleted_generated_operation_does_not_come_back(self):
        self.db.save_recurring(None, "Loyer", -80000, None, "monthly", date(2026, 1, 5))
        self.db.generate_due(date(2026, 1, 10))
        self.db.delete_transaction(self.db.transactions()[0]["id"])
        self.assertEqual(self.db.generate_due(date(2026, 1, 11)), 0)

    def test_pause_skips_missed_occurrences(self):
        self.db.save_recurring(None, "Loyer", -80000, None, "monthly", date(2026, 1, 5))
        rule = self.db.recurring()[0]["id"]
        self.db.set_recurring_active(rule, False)
        self.assertEqual(self.db.generate_due(date(2026, 3, 10)), 0)
        self.db.set_recurring_active(rule, True, date(2026, 3, 10))
        self.assertEqual(self.db.next_occurrence(self.db.recurring()[0]), date(2026, 4, 5))
        self.assertEqual(self.db.generate_due(date(2026, 3, 10)), 0)

    def test_deleting_rule_keeps_past_operations(self):
        self.db.save_recurring(None, "Loyer", -80000, None, "monthly", date(2026, 1, 5))
        self.db.generate_due(date(2026, 1, 10))
        self.db.delete_recurring(self.db.recurring()[0]["id"])
        self.assertEqual(len(self.db.transactions()), 1)

    def test_add_months_helper(self):
        self.assertEqual(add_months(date(2026, 12, 15), 1), date(2027, 1, 15))
        self.assertEqual(add_months(date(2026, 1, 15), -1), date(2025, 12, 15))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_french_csv_with_preamble_cp1252(self):
        data = (
            "Compte courant;FR76 1234\n"
            "Solde au 31/03;1 000,00\n"
            "\n"
            "Date opération;Libellé;Débit;Crédit\n"
            "02/03/2026;CB Café;3,50;\n"
            "03/03/2026;Virement Salaire;;2 100,00\n"
            "Total;;3,50;2 100,00\n"
        ).encode("cp1252")
        parsed = read_csv(data)
        self.assertEqual(parsed.headers[0], "Date opération")
        items, skipped = parse_csv_rows(parsed, parsed.mapping)
        self.assertEqual(
            [(i.date, i.label, i.amount_cents) for i in items],
            [
                (date(2026, 3, 2), "CB Café", -350),
                (date(2026, 3, 3), "Virement Salaire", 210000),
            ],
        )
        self.assertEqual(skipped, 1)

    def test_signed_amount_comma_delimiter(self):
        parsed = read_csv(b'date,description,amount\n2026-03-02,Coffee,"-3.50"\n')
        items, skipped = parse_csv_rows(parsed, parsed.mapping)
        self.assertEqual(items[0].amount_cents, -350)
        self.assertEqual(skipped, 0)

    def test_csv_without_headers(self):
        parsed = read_csv("02/03/2026;CB Café;-3,50\n03/03/2026;Boulangerie;-1,20\n".encode())
        items, _ = parse_csv_rows(parsed, parsed.mapping)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].label, "Boulangerie")

    def test_csv_with_no_dates_is_rejected(self):
        with self.assertRaises(ValueError):
            read_csv(b"a;b\n1;2\n")

    def test_valeur_date_column_is_not_taken_for_the_amount(self):
        mapping = guess_mapping(["Date", "Date de valeur", "Libellé", "Montant"])
        self.assertEqual((mapping.date, mapping.label, mapping.amount), (0, 2, 3))

    def test_ambiguous_dates_are_day_first(self):
        self.assertEqual(parse_date("03/04/2026"), date(2026, 4, 3))

    def test_ofx_sgml(self):
        data = (
            "OFXHEADER:100\nDATA:OFXSGML\n\n<OFX><BANKTRANLIST>"
            "<STMTTRN>\n<TRNTYPE>DEBIT\n<DTPOSTED>20260302120000\n<TRNAMT>-3,50\n"
            "<FITID>A1\n<NAME>CB CAFE\n</STMTTRN>"
            "<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260303<TRNAMT>2100.00<FITID>A2<MEMO>SALAIRE</STMTTRN>"
            "</BANKTRANLIST></OFX>"
        ).encode()
        items, skipped = parse_ofx(data)
        self.assertEqual(skipped, 0)
        self.assertEqual(
            [(i.date, i.label, i.amount_cents, i.bank_id) for i in items],
            [
                (date(2026, 3, 2), "CB CAFE", -350, "A1"),
                (date(2026, 3, 3), "SALAIRE", 210000, "A2"),
            ],
        )

    def test_reimport_is_idempotent_but_keeps_identical_same_day_operations(self):
        items = [
            ImportedTransaction(date(2026, 3, 2), "Café", -200),
            ImportedTransaction(date(2026, 3, 2), "Café", -200),
        ]
        first = self.db.import_transactions(items)
        self.assertEqual((first.added, first.duplicates), (2, 0))
        second = self.db.import_transactions(items)
        self.assertEqual((second.added, second.duplicates), (0, 2))
        self.assertEqual(len(self.db.transactions()), 2)

    def test_recurring_operation_is_reconciled_not_duplicated(self):
        self.db.save_recurring(None, "Loyer", -80000, None, "monthly", date(2026, 3, 5))
        self.db.generate_due(date(2026, 3, 5))
        result = self.db.import_transactions(
            [ImportedTransaction(date(2026, 3, 6), "VIR SEPA PROPRIETAIRE", -80000)]
        )
        self.assertEqual((result.added, result.reconciled), (0, 1))
        rows = self.db.transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Loyer")
        self.assertEqual(rows[0]["date"], "2026-03-06")

    def test_import_reuses_known_category(self):
        courses = next(c["id"] for c in self.db.categories() if c["name"] == "Courses")
        self.db.save_transaction(None, date(2026, 2, 1), "CB MONOPRIX 01/02", -100, courses)
        self.db.import_transactions([ImportedTransaction(date(2026, 3, 1), "CB MONOPRIX 01/03", -250)])
        latest = self.db.transactions()[0]
        self.assertEqual(latest["category_id"], courses)


class GoalAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = Database(self.dir / "moneo.db")
        self.addCleanup(self.db.close)

    def test_goal_cannot_go_negative(self):
        self.db.save_goal(None, "Vacances", 150000, date(2027, 7, 1))
        goal = self.db.goals()[0]["id"]
        self.db.adjust_goal(goal, 10000)
        with self.assertRaises(ValueError):
            self.db.adjust_goal(goal, -20000)
        self.assertEqual(self.db.total_saved(), 10000)

    def test_backup_restore_roundtrip(self):
        self.db.save_transaction(None, date(2026, 3, 1), "Avant", -100, None)
        backup = self.dir / "sauvegarde.db"
        self.db.export_backup(backup)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.db.save_transaction(None, date(2026, 3, 2), "Après", -100, None)
        self.db.restore_backup(backup)
        self.assertEqual([r["label"] for r in self.db.transactions()], ["Avant"])
        self.assertTrue((self.dir / "moneo.db.avant-restauration").exists())
        # La base reste utilisable après restauration.
        self.db.save_transaction(None, date(2026, 3, 3), "Encore", -100, None)

    def test_restore_rejects_other_files_and_keeps_data(self):
        self.db.save_transaction(None, date(2026, 3, 1), "Gardée", -100, None)
        other = self.dir / "autre.txt"
        other.write_text("pas une base de données, juste du texte " * 50)
        with self.assertRaises(BackupError):
            self.db.restore_backup(other)
        self.assertEqual(len(self.db.transactions()), 1)

    def test_database_file_is_private(self):
        self.assertEqual((self.dir / "moneo.db").stat().st_mode & 0o777, 0o600)

    def test_data_persists_across_reopen(self):
        self.db.save_transaction(None, date(2026, 3, 1), "Persistante", -100, None)
        reopened = Database(self.dir / "moneo.db")
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.transactions()), 1)
        self.assertEqual(len(reopened.categories()), 9)


if __name__ == "__main__":
    unittest.main()
