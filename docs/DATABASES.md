# Database lifecycle

The distribution contains no database files, dumps, populated indexes, or seed records.

When a feature needs SQLite or DuckDB state, it creates a new database at runtime and applies its code-defined schema.
The application must tolerate a missing database as the normal first-run condition.

Release archives reject:

- `*.db`, `*.sqlite`, `*.sqlite3`, and `*.duckdb`;
- SQL dumps and database exports;
- vector indexes and generated search cabinets;
- JSONL event stores, captured datasets, and runtime reports.

Back up runtime data separately. Never copy a production database into a source checkout.
