# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Neutral runtime-path foundation for the AgentReady Factory."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or (Path.home() / ".agentready"))


def _coordination_root() -> Path:
    """Where coordination stores live.

    A dedicated ``AGENTREADY_COORDINATION_ROOT`` override exists as a test seam: it
    lets the suite isolate the coordination store without moving ``AGENTREADY_HOME``
    (which also anchors repo-file lookups, so relocating it would break everything
    that reads them). It is unset in normal use, so behaviour is unchanged; the test
    suite sets it before this module is imported so the constant below resolves to a
    temporary directory instead of the user's real store.
    """
    override = os.environ.get("AGENTREADY_COORDINATION_ROOT", "").strip()
    if override:
        return Path(override)
    return AGENTREADY_HOME / "coordination"


COORDINATION_ROOT = _coordination_root()
WORKTREE_ROOT = AGENTREADY_HOME / "worktrees"


STORE_SUBDIRS = (
    "tasks", "events", "task-reports", "handoffs",
    "decisions", "locks", "versions", "reviews", "worktrees",
)

# Repository-owned declarations and machine-local receipts share the
# ``.agentready`` namespace. Keep this runtime set exact so tracked contracts
# such as ``ci.json`` remain visible to Git and work-state gates.
AGENTREADY_RUNTIME_PATHS = frozenset({".agentready/gate_status.json"})


def is_agentready_runtime_path(path: str | Path) -> bool:
    """Return whether a repository-relative path is generated runtime state."""
    normalized = str(path).strip().strip('"').replace("\\", "/")
    if " -> " in normalized:
        normalized = normalized.rsplit(" -> ", maxsplit=1)[-1].strip('"')
    return normalized.lower() in AGENTREADY_RUNTIME_PATHS


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

    The normalized name is stable across supported operating systems.
    """
    common = git_common_dir(repo)
    if common and common.name.lower() == ".git":
        return common.parent.name
    return repo.name or "repo"


def state_root(repo: str | Path | None = None) -> Path:
    """The per-repo coordination store: `<COORDINATION_ROOT>/<repo_name>-<digest>`.

    digest = sha256(lowercased git-common-dir path)[:16].
    """
    repo = resolve_repo(repo)
    identity: Path = repo
    common = git_common_dir(repo)
    if common:
        identity = common
    digest = hashlib.sha256(str(identity).lower().encode("utf-8")).hexdigest()[:16]
    return COORDINATION_ROOT / f"{repo_name(repo)}-{digest}"


def worktree_root(repo: str | Path | None = None) -> Path:
    """Return the configured external-worktree root for this repository."""
    repo = resolve_repo(repo)
    return WORKTREE_ROOT / repo_name(repo)
