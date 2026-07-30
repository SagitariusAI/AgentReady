# Uninstall

Removing AgentReady does not automatically delete capture records, coordination ledgers, or hooks installed in other
repositories.

## 1. Remove optional Git hooks

In each repository where capture hooks were installed:

```powershell
Set-Location "C:\path\to\your-repository"
factory-capture hooks status
factory-capture hooks uninstall
```

AgentReady preserves and chains an existing non-AgentReady hook when installing its own hook. Confirm the resulting
hook state before deleting any backup hook file.

## 2. Back up records

Stop any capture watcher or process writing to AgentReady state. Copy any capture, coordination, or report records you
need to retain. See [Data retention, backup, and export](DATA_RETENTION_AND_EXPORT.md).

## 3. Remove the installed commands

For an installation created with `uv tool install`:

```powershell
uv tool uninstall agentready
```

For a development checkout, remove its `.venv` directory and then delete the source checkout when it is no longer
needed.

## 4. Remove runtime state

After verifying your backup, remove only the specific directories you no longer need:

- the target repository's `.factory_capture` directory, or the configured `FACTORY_CAPTURE_DIR`;
- the repository's ignored `.agent-state` pointer;
- the corresponding directory under `AGENTREADY_HOME\coordination`;
- generated `.agent-reports` directories.

Do not delete a broad user-profile or drive root. Resolve each path first and confirm that it belongs to the intended
repository.
