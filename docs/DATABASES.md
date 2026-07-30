# Database lifecycle

AgentReady ships with no database files, database dumps, populated indexes, seed records, event streams, or datasets.
A missing database is the expected first-run condition.

## First initialization

`factory-capture init` creates a new capture directory for the repository in the current working directory, unless
`FACTORY_CAPTURE_DIR` is set. It creates:

- `config.json`, containing local store metadata;
- `events.jsonl`, created when events are recorded and used as the durable event stream;
- `index.sqlite`, a local SQLite query index with an empty `events` table;
- local directories for logs, artifacts, sessions, and hook metadata.

Initialization creates the schema with zero captured events. The `--force` option refreshes initialization metadata;
it is not an erase command and must not be used as a substitute for deleting or migrating an existing store.

Some optional deterministic or data-processing features can use DuckDB when the `toolbox` extra is installed. They
must create their own runtime files from the current user's inputs; no DuckDB file is bundled.

## Release exclusions

The publication guard rejects:

- `*.db`, `*.sqlite`, `*.sqlite3`, and `*.duckdb`;
- SQL dumps, database exports, journals, and write-ahead logs;
- vector indexes and generated search data;
- JSONL event stores, captured datasets, runtime reports, and nested archives.

## Backup and removal

Stop processes using a store before copying it. Back up the complete capture directory so the JSONL record, SQLite
index, configuration, and related artifacts remain together. Store backups outside the source checkout.

To reset a capture store, first uninstall its Git hooks, preserve any records you need, and then remove the entire
runtime directory. Running an initializer over a populated store does not guarantee an empty database.

Never copy an operational database or event stream into the AgentReady source repository.
