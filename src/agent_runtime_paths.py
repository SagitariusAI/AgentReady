"""Neutral runtime-path foundation for the AgentReady Factory.

This is the *foundation* layer: the canonical per-repo coordination-store identity used by the
coordination engine, the commit guard, report-submit, and any other durable subsystem. It depends on
nothing else in the Factory (stdlib only) so every consumer can sit above it without a cycle.

The store-identity algorithm is byte-identical to PowerShell `Get-AgentStateRoot`
(`bin/agent-coordination-lib.ps1` L12-36) and to `agent_report_submit_lib.write.state_root` — proven by
`smoke/agent_runtime_paths_parity_smoke.py`. The digest keys on the **git common dir** (not the worktree
path), so a task started in a worktree and one in the main tree resolve to the *same* store.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or (Path.home() / ".agentready"))
COORDINATION_ROOT = AGENTREADY_HOME / "coordination"
WORKTREE_ROOT = AGENTREADY_HOME / "worktrees"

# The coordination store layout (PowerShell Initialize-AgentState L95-108).
STORE_SUBDIRS = (
    "tasks", "events", "task-reports", "handoffs",
    "decisions", "locks", "versions", "reviews", "worktrees",
)


def resolve_repo(repo: str | Path | None = None) -> Path:
    return Path(repo or os.getcwd()).expanduser().resolve(strict=False)


def git_common_dir(repo: Path) -> Path | None:
    """Resolved git common dir, or None outside a git repo (mirrors `git rev-parse --git-common-dir`)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common = out.stdout.strip()
    if not common:
        return None
    path = Path(common)
    if not path.is_absolute():
        path = repo / path
    return path.resolve(strict=False)


def repo_name(repo: Path) -> str:
    """Repo name = the dir that owns the .git common dir (worktree-stable), else the path leaf.

    Mirrors PowerShell `Get-AgentCoordinationRepoName` / the repoName branch of `Get-AgentStateRoot`.
    """
    common = git_common_dir(repo)
    if common and common.name.lower() == ".git":
        return common.parent.name
    return repo.name or "repo"


def state_root(repo: str | Path | None = None) -> Path:
    """The per-repo coordination store: `<COORDINATION_ROOT>/<repo_name>-<digest>`.

    digest = sha256(lowercased git-common-dir path)[:16]  — byte-identical to PowerShell and to
    agent_report_submit_lib.write.state_root.
    """
    repo = resolve_repo(repo)
    identity: Path = repo
    common = git_common_dir(repo)
    if common:
        identity = common
    digest = hashlib.sha256(str(identity).lower().encode("utf-8")).hexdigest()[:16]
    return COORDINATION_ROOT / f"{repo_name(repo)}-{digest}"


def worktree_root(repo: str | Path | None = None) -> Path:
    """Where this repo's external worktrees live (PowerShell pointer.json `worktree_root`)."""
    repo = resolve_repo(repo)
    return WORKTREE_ROOT / repo_name(repo)
