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

Session re-entry receipts are stored below this root in `session-reentry`,
unless `AGENTREADY_SESSION_REENTRY_DIR` is set.

### `AGENTREADY_AUTHORITY_REMOTE`

Optional Git remote name or URL used by `agent-session-reentry`. When set, the
current local branch must exist at that authority with the exact same commit.
When omitted, the receipt records an explicit `local-only` source posture.

### `AGENTREADY_HARNESS_FILES`

Optional platform-separated list of additional local configuration files to
include by hash in the session fingerprint. File content is never copied into
the receipt.

### `AGENTREADY_REENTRY_REQUIRED`

Set to `1` in an installed commit hook to require a valid Claude/Codex re-entry
receipt at the commit boundary.

### `FACTORY_CAPTURE_DIR`

Overrides the capture store for the repository in the current working directory. Use an absolute path:

```powershell
$env:FACTORY_CAPTURE_DIR = "C:\Users\sample-user\AgentReadyCapture\example-project"
```

If it is not set, capture data is written to:

```text
<target-repository>\.factory_capture
```

## Repository CI and environment setup

A repository can replace, prepend, or append AgentReady's detected CI steps in
`.agentready/ci.json`. Commands are argv arrays rather than shell strings. A
repository that needs a locked dependency profile or generated native bindings
can also declare an idempotent `setup` array:

```json
{
  "version": 1,
  "mode": "replace",
  "setup": [
    {
      "name": "locked development environment",
      "argv": ["uv", "sync", "--frozen", "--group", "dev"]
    }
  ],
  "steps": [
    {
      "name": "project tests",
      "argv": ["{repo_python}", "-m", "pytest", "-q"]
    }
  ]
}
```

AgentReady runs setup before admitting an AgentReady-created worktree and again
before the repository gate. Gate commands are resolved after setup, so
`{repo_python}` uses `.venv\Scripts\python.exe` on Windows or
`.venv/bin/python` on POSIX when setup creates that environment. The first
setup failure aborts the gate. A newly-created worktree is removed and no task,
lock, event, or worktree pointer is recorded; an existing verified worktree is
preserved for diagnosis but is not admitted. Worktree setup refusal exits with
code 7.

The ``.agentready`` directory is a mixed namespace, not disposable runtime
state. AgentReady excludes only the generated
``.agentready/gate_status.json`` receipt in Git's local exclude. Tracked
declarations such as ``.agentready/ci.json`` remain visible to ``git status``
and work-state gates. Coordination initialization atomically and idempotently
migrates the legacy broad ``.agentready/`` exclusion to the exact receipt path.

## Repository-local state

`agent-coordination coordination-init` creates an ignored `.agent-state` pointer in the target repository and records
the corresponding shared state path. Capture initialization creates an ignored `.factory_capture` directory unless
`FACTORY_CAPTURE_DIR` is set. Verification commands may create ignored `.agent-reports` output.

These directories are local runtime state. Do not add them to source control or a release archive.

## Credentials and integrations

The public core has no credential configuration. Do not place secrets in configuration files, command examples, test
fixtures, or documentation. A downstream integration should read its own secrets from an operating-system credential
store or another user-controlled mechanism and should remain disabled unless explicitly configured.
