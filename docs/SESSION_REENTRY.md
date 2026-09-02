# Frontier-agent session re-entry

An agent handoff preserves context, but it does not prove that a new process is
using the same harness, has read urgent instructions, owns the active lane, or
is operating against the intended source authority. AgentReady therefore
provides an optional fail-closed mutation boundary for Claude and Codex.

Use it after an agent application, model, plugin, or harness update; after a new
session or context reset; or whenever behavior appears degraded.

## The transaction

1. Read and acknowledge urgent coordination messages.
2. Reconcile active and stale tasks.
3. Claim one exact task and inspect all dirty files.
4. Decide whether the local repository alone is authoritative, or configure an
   authority remote.
5. Explicitly acknowledge the operating rules, negative results, and source
   authority.
6. Issue a short-lived receipt bound to the agent, session, task, repository,
   exact task checkout, harness fingerprint, and expiry.

```powershell
$env:AGENTREADY_AGENT = "claude"
$env:AGENTREADY_AUTHORITY_REMOTE = "origin" # optional; exact current-branch parity is required

agent-session-reentry issue `
  --agent claude `
  --repo "C:\path\to\repository" `
  --session-id "<session-id-from-the-agent-hook>" `
  --task-id "<active-task-id>" `
  --ack-operating-rules `
  --ack-negative-results `
  --ack-source-control
```

Add `--ack-dirty` only after inspecting dirty paths and confirming that the
active task claims every one. A receipt is never issued when an urgent stop
remains unread, ownership is ambiguous, dirty work is unclaimed, the configured
authority remote differs from local HEAD, or the harness changed.

When the active task records a linked Git worktree, re-entry inspects that
worktree rather than the canonical checkout. The recorded path must be absolute,
available, the Git top level, attached to the same common repository identity,
and on the task's recorded branch. Missing, foreign, nested, or branch-mismatched
worktrees fail closed. The receipt records the selected checkout and verification
rejects a task that later points at a different worktree.

Without `AGENTREADY_AUTHORITY_REMOTE`, the source check is explicitly
`local-only`. This supports sovereign/offline work without pretending that a
hosted remote was verified.

Receipts live under `AGENTREADY_HOME/session-reentry` by default. Override that
location with `AGENTREADY_SESSION_REENTRY_DIR`. Receipt JSON stores hashes and
operational identifiers, not message bodies, source text, credentials, or user
data.

## Claude tool boundary

Claude Code hooks can surface the status at session start and deny mutating
tools until the session-specific receipt passes. Adapt this fragment to your
local Claude settings:

```json
{
  "env": { "AGENTREADY_AGENT": "claude" },
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "agent-session-reentry",
        "args": ["hook", "session-start", "--agent", "claude"]
      }]
    }],
    "PreToolUse": [{
      "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash|mcp__serena__write_memory|mcp__serena__edit_memory|mcp__serena__rename_memory|mcp__serena__delete_memory",
      "hooks": [{
        "type": "command",
        "command": "agent-session-reentry",
        "args": ["hook", "pre-tool-use", "--agent", "claude"]
      }]
    }]
  }
}
```

Merge this with existing settings; do not replace unrelated hooks. Before a
receipt, the bootstrap allowlist permits coordination inspection, the re-entry
command, and read-only Git inspection. It denies source or memory writes,
arbitrary scripts, pipelines, and pushes.

## Commit boundary

The commit guard independently verifies the latest valid receipt when the
operator enables enforcement:

```powershell
$env:AGENTREADY_REENTRY_REQUIRED = "1"
$env:AGENTREADY_AGENT = "claude" # or codex
agent-commit-guard --repo .
```

Place that command in a managed `pre-commit` hook if you want every real commit
to enforce re-entry. The tool hook remains the session-specific boundary; the
commit hook is defense in depth and binds the receipt to the covering task and
repository.

## Recovery

Do not delete or hand-edit receipts to bypass a blocker. Read the reported
reason, repair coordination or source authority, and issue a new receipt. A
harness change or expired receipt intentionally requires re-entry again.
