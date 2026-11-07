# Data Quality Guardrails

A small, dependency-free Python and SQLite pipeline for checking incoming transaction CSVs before their data is used in reporting. Invalid rows are isolated with machine-readable diagnostic flags; only passing rows enter the validated table. This makes the validated table the safe source for downstream dashboard models, rather than allowing raw data to flow directly into executive reporting.

## Checks included

- Required values for `transaction_id`, `borrower_id`, `amount`, and `timestamp`.
- Numeric, finite, non-negative transaction amounts (zero is allowed).
- ISO-8601 timestamps in the half-open range 2000-01-01 through 2100-01-01. The timestamp is retained as supplied; `Z` and timezone offsets are accepted.
- Extra CSV fields are marked as malformed.
- Processing duration measured against a configurable request SLA.

Rows with one or more failures are written to `data_quality_exceptions` with the original row as JSON and an `error_flags` JSON array. Passing rows are written to `validated_transactions`. Both tables are created from `schema.sql` in the selected SQLite database. A missing required CSV header stops the run before records are loaded.

## Run

Requires Python 3.9+ and uses only the standard library.

```bash
python pipeline.py data/incoming_transactions.csv --database data/quality.sqlite --sla-seconds 5
```

The command prints JSON counts and SLA status. It exits with status 0 when the SLA is met, 1 when processing exceeds the SLA, and 2 for an input/database error. SLA timing covers pipeline setup, validation, and database writes; it is a processing-time check, not an end-to-end upstream request latency measurement.

Expected CSV header:

```csv
transaction_id,borrower_id,amount,timestamp
```

## Inspect the results

```sql
SELECT transaction_id, borrower_id, amount, timestamp
FROM validated_transactions;

SELECT source_file, source_row, raw_record, error_flags, detected_at
FROM data_quality_exceptions
ORDER BY detected_at DESC;
```

Point dashboard transformations only at `validated_transactions`. Monitor rejected-record counts and the exception flags as a separate operational signal; investigate and correct exceptions at the source before reprocessing. Do not silently drop exceptions or treat the exception table as dashboard input.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover required borrower IDs, negative amounts, malformed and out-of-range timestamps, accepted rows, exception routing, and summary counts.

## Production considerations

This starter is intentionally lightweight. Agree with data owners on the timestamp range and SLA threshold before deployment. For production, add access controls and retention for raw exception data, alerting on SLA breaches or rejection-rate thresholds, source batch identifiers/idempotency, and integration with the warehouse's native exception table and orchestration platform. Keep thresholds and dashboard gates visible and version-controlled so data owners can audit changes.
