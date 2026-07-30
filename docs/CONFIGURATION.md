# Configuration

AgentReady is local-first and works without an account, API key, or remote service.

## Environment variables

### `AGENTREADY_HOME`

Sets the user-level state root used by coordination and worktree features.

```powershell
$env:AGENTREADY_HOME = "C:\Users\sample-user\AgentReadyState"
```

If it is not set, the default is:

```text
%USERPROFILE%\.agentready
```

Coordination state is placed under `coordination`, and AgentReady-created worktrees are placed under `worktrees`.
Repository identity is derived from the resolved Git common directory so linked worktrees share the correct ledger.

### `FACTORY_CAPTURE_DIR`

Overrides the capture store for the repository in the current working directory. Use an absolute path:

```powershell
$env:FACTORY_CAPTURE_DIR = "C:\Users\sample-user\AgentReadyCapture\example-project"
```

If it is not set, capture data is written to:

```text
<target-repository>\.factory_capture
```

## Repository-local state

`agent-coordination coordination-init` creates an ignored `.agent-state` pointer in the target repository and records
the corresponding shared state path. Capture initialization creates an ignored `.factory_capture` directory unless
`FACTORY_CAPTURE_DIR` is set. Verification commands may create ignored `.agent-reports` output.

These directories are local runtime state. Do not add them to source control or a release archive.

## Credentials and integrations

The public core has no credential configuration. Do not place secrets in configuration files, command examples, test
fixtures, or documentation. A downstream integration should read its own secrets from an operating-system credential
store or another user-controlled mechanism and should remain disabled unless explicitly configured.
