#!/usr/bin/env python3
"""Validate transaction CSV rows and route failures to SQLite exceptions."""

import argparse
import csv
import json
import sqlite3
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED_COLUMNS = ("transaction_id", "borrower_id", "amount", "timestamp")
MIN_TIMESTAMP = datetime(2000, 1, 1)
MAX_TIMESTAMP = datetime(2100, 1, 1)


def parse_timestamp(value):
    """Parse an ISO-8601 timestamp (including a trailing Z) to a datetime."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def validate_record(row):
    """Return diagnostic flags for a raw CSV record; an empty list means valid."""
    flags = []
    if not isinstance(row, dict):
        return ["invalid_record_shape"]

    for column in REQUIRED_COLUMNS:
        value = row.get(column)
        if value is None or not str(value).strip():
            flags.append(f"missing_{column}")

    amount_text = row.get("amount")
    if amount_text is not None and str(amount_text).strip():
        try:
            amount = Decimal(str(amount_text).strip())
            if not amount.is_finite():
                flags.append("invalid_amount")
            elif amount < 0:
                flags.append("negative_amount")
        except InvalidOperation:
            flags.append("invalid_amount")

    timestamp_text = row.get("timestamp")
    if timestamp_text is not None and str(timestamp_text).strip():
        try:
            timestamp = parse_timestamp(str(timestamp_text))
            # Compare naive values consistently; preserve the original source value.
            comparable = timestamp.replace(tzinfo=None)
            if not MIN_TIMESTAMP <= comparable < MAX_TIMESTAMP:
                flags.append("timestamp_out_of_range")
        except (ValueError, OverflowError):
            flags.append("invalid_timestamp")

    return flags


def initialize_database(connection, schema_path=None):
    schema = Path(schema_path) if schema_path else Path(__file__).with_name("schema.sql")
    connection.executescript(schema.read_text(encoding="utf-8"))


def process_csv(input_path, database_path, sla_seconds=5.0, schema_path=None):
    """Validate the CSV, persist valid rows and exceptions, and return a run summary."""
    started = time.monotonic()
    counts = {"records_read": 0, "records_accepted": 0, "records_rejected": 0}
    connection = sqlite3.connect(database_path)
    try:
        initialize_database(connection, schema_path)
        with open(input_path, newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ValueError("Input CSV is empty or has no header")
            missing_columns = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
            if missing_columns:
                raise ValueError("Missing required CSV columns: " + ", ".join(missing_columns))

            for row in reader:
                counts["records_read"] += 1
                # DictReader stores surplus fields under a None key; capture these as malformed.
                flags = validate_record(row)
                if None in row:
                    flags.append("unexpected_extra_fields")
                raw_json = json.dumps(row, sort_keys=True)
                if flags:
                    connection.execute(
                        "INSERT INTO data_quality_exceptions "
                        "(source_file, source_row, raw_record, error_flags) VALUES (?, ?, ?, ?)",
                        (str(input_path), reader.line_num, raw_json, json.dumps(sorted(set(flags)))),
                    )
                    counts["records_rejected"] += 1
                else:
                    connection.execute(
                        "INSERT INTO validated_transactions "
                        "(transaction_id, borrower_id, amount, timestamp, source_file, source_row) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (row["transaction_id"].strip(), row["borrower_id"].strip(),
                         str(Decimal(row["amount"].strip())), row["timestamp"].strip(),
                         str(input_path), reader.line_num),
                    )
                    counts["records_accepted"] += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    elapsed = time.monotonic() - started
    counts.update({
        "elapsed_seconds": round(elapsed, 6),
        "sla_seconds": sla_seconds,
        "sla_met": elapsed <= sla_seconds,
    })
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Incoming CSV with transaction data")
    parser.add_argument("--database", default="data_quality.sqlite", help="SQLite database path")
    parser.add_argument("--sla-seconds", type=float, default=5.0,
                        help="Maximum permitted processing time (default: 5 seconds)")
    args = parser.parse_args(argv)
    if args.sla_seconds < 0:
        parser.error("--sla-seconds must be non-negative")
    try:
        summary = process_csv(args.input_csv, args.database, args.sla_seconds)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0 if summary["sla_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
