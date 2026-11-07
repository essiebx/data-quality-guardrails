import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline import process_csv, validate_record


class ValidationTests(unittest.TestCase):
    def test_missing_borrower_negative_amount_and_bad_timestamp(self):
        flags = validate_record({
            "transaction_id": "t-1", "borrower_id": " ", "amount": "-2.50",
            "timestamp": "not-a-date",
        })
        self.assertEqual(set(flags), {"missing_borrower_id", "negative_amount", "invalid_timestamp"})

    def test_valid_iso_timestamp_and_zero_amount(self):
        self.assertEqual(validate_record({
            "transaction_id": "t-2", "borrower_id": "b-2", "amount": "0",
            "timestamp": "2025-01-02T03:04:05Z",
        }), [])

    def test_out_of_range_timestamp(self):
        flags = validate_record({
            "transaction_id": "t-3", "borrower_id": "b-3", "amount": "10",
            "timestamp": "1999-12-31T23:59:59",
        })
        self.assertIn("timestamp_out_of_range", flags)

    def test_routes_bad_rows_and_keeps_good_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "incoming.csv"
            db_path = root / "quality.sqlite"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["transaction_id", "borrower_id", "amount", "timestamp"])
                writer.writeheader()
                writer.writerow({"transaction_id": "ok", "borrower_id": "b1", "amount": "12.30", "timestamp": "2025-01-01T00:00:00Z"})
                writer.writerow({"transaction_id": "bad", "borrower_id": "", "amount": "-3", "timestamp": "2025-01-01T00:00:00Z"})

            summary = process_csv(csv_path, db_path, sla_seconds=10)
            self.assertEqual(summary["records_read"], 2)
            self.assertEqual(summary["records_accepted"], 1)
            self.assertEqual(summary["records_rejected"], 1)
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM validated_transactions").fetchone()[0], 1)
                flags = connection.execute("SELECT error_flags FROM data_quality_exceptions").fetchone()[0]
                self.assertIn("missing_borrower_id", flags)
                self.assertIn("negative_amount", flags)


if __name__ == "__main__":
    unittest.main()
