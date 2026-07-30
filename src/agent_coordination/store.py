# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for store."""
from __future__ import annotations

import subprocess
from pathlib import Path

from agent_coordination.common import now_stamp, write_json
from agent_runtime_paths import STORE_SUBDIRS, repo_name, resolve_repo, state_root, worktree_root

_LOCAL_EXCLUDE_PATTERNS = (".agent-state/", ".agent-reports/", ".agentready/")
_EXCLUDE_HEADER = "# AgentReady local coordination/report state (machine-local, do not commit)"


def _git_dir(repo: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
                             check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    common = out.stdout.strip()
    if not common:
        return None
    path = Path(common)
    if not path.is_absolute():
        path = repo / path
    return path.resolve(strict=False)


def add_local_git_exclude(repo: Path) -> None:
    """Append AgentReady's machine-local dirs to .git/info/exclude (local, untracked — never a tracked file)."""
    git_dir = _git_dir(repo)
    if not git_dir:
        return
    info_dir = git_dir / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    exclude_path = info_dir / "exclude"
    existing = []
    if exclude_path.exists():
        existing = [line.strip() for line in exclude_path.read_text(encoding="utf-8", errors="replace").splitlines()]
    to_add = [p for p in _LOCAL_EXCLUDE_PATTERNS if p not in existing]
    if not to_add:
        return
    with exclude_path.open("a", encoding="utf-8") as handle:
        if _EXCLUDE_HEADER not in existing:
            handle.write(_EXCLUDE_HEADER + "\n")
        for pattern in to_add:
            handle.write(pattern + "\n")


_STATE_README = """# Agent State

This folder is the local coordination ledger for Codex, Claude, and future agents.

- `tasks/`: current and historical task records.
- `events/`: append-only task event streams.
- `task-reports/`: compact structured frontier-agent receipts and generated Markdown.
- `handoffs/`: agent handoff capsules.
- `decisions/`: durable decision notes.
- `locks/`: path claims for concurrent work.
- `versions/`: release/version records.
- `reviews/`: review records and evidence.
- `worktrees/`: pointers to external worktrees.

Do not delete this folder during normal cleanup. It is development memory.
"""


def ensure_state(repo: str | Path | None = None) -> Path:
    """Create the coordination store + local pointer. Returns the shared state root. Idempotent.

    Port of Initialize-AgentState (L88-158): 9 shared subdirs + .agent-state/pointer.json + READMEs +
    git exclude.
    """
    repo_root = resolve_repo(repo)
    # regression-path-misparse: reject a FILE masquerading as the repo
    # root (e.g. a space-separated `-Paths a b c` value spilling into the wrapper's positional
    # `-Repo`). Without this guard, mkdir('.agent-state') under a file crashed mid-init and no
    # coordination task record was written — a silent auditability gap.
    if repo_root.exists() and not repo_root.is_dir():
        raise NotADirectoryError(
            f"repo root must be a directory, got a file: {repo_root}. "
            "A file path likely leaked into the repository argument. "
            "Pass the repo with --repo <dir>; pass files via --paths as a comma-joined list "
            "or an explicit array (not space-separated positional values)."
        )
    state = state_root(repo_root)
    local_state = repo_root / ".agent-state"
    local_state.mkdir(parents=True, exist_ok=True)
    add_local_git_exclude(repo_root)
    state.mkdir(parents=True, exist_ok=True)
    for sub in STORE_SUBDIRS:
        (state / sub).mkdir(parents=True, exist_ok=True)
    write_json(local_state / "pointer.json", {
        "version": 1,
        "repo": str(repo_root),
        "shared_state": str(state),
        "worktree_root": str(worktree_root(repo_root)),
        "updated_at": now_stamp(),
    })
    index = state / "README.md"
    if not index.exists():
        index.write_text(_STATE_README, encoding="utf-8")
    (local_state / "README.md").write_text(
        "# Agent State Pointer\n\nThis repo uses shared AgentReady coordination state.\n\n"
        f"Shared state:\n\n```text\n{state}\n```\n\n"
        "Use:\n\n```powershell\nagent-task-status\nagent-history-search -Query \"<text>\"\n```\n",
        encoding="utf-8")
    return state


def state_dir(repo: str | Path | None = None, sub: str = "") -> Path:
    """Resolve a store subdirectory (does not create it). E.g. state_dir(repo, 'tasks')."""
    root = state_root(resolve_repo(repo))
    return root / sub if sub else root


def worktree_path(repo: str | Path | None, task_id: str) -> Path:
    """Where a task's isolated worktree lives — port of Get-AgentWorktreePath (L397-400)."""
    return worktree_root(resolve_repo(repo)) / task_id


# convenience re-exports for consumers
__all__ = ["ensure_state", "state_dir", "worktree_path", "add_local_git_exclude",
           "repo_name", "state_root", "resolve_repo", "worktree_root"]
