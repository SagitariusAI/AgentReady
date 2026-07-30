# Data retention, backup, and export

AgentReady does not upload or bundle runtime records. The operator who creates a capture store or coordination ledger
controls its retention.

## What to retain

- Capture records: the complete `.factory_capture` directory, or the directory selected by `FACTORY_CAPTURE_DIR`.
- Coordination records: the repository-specific directory under `%USERPROFILE%\.agentready\coordination`, or under
  the configured `AGENTREADY_HOME`.
- Generated evidence: any `.agent-reports` output that is required for an audit or release record.

The capture event stream is stored as JSONL and can be copied for line-oriented processing. The SQLite file is a
local query index, but it should be backed up with the event stream and configuration rather than treated as the only
record.

## Safe backup procedure

1. Stop capture watchers and other processes writing to the store.
2. Uninstall capture hooks if the repository is being retired.
3. Copy the complete runtime directory to a user-controlled backup location.
4. Verify the copy before deleting the original.

AgentReady does not define a universal retention period. Choose one that fits the sensitivity of the repository and
your legal, contractual, or organizational requirements.

## Publication boundary

Source releases contain only code, schemas, tests, documentation, and empty initialization behavior. The publication
guard rejects databases, event streams, datasets, reports, caches, archives, credentials, and model artifacts in the
source inventory. Keep backups and exports outside the source checkout.
