"""Deterministic git-state capture via the `git` CLI (stdlib subprocess only).

Captures repo root, branch, HEAD commit, dirty flag, and changed/staged/untracked files. The remote
is sanitized (credentials stripped) and hashed — a credential-bearing URL is never stored. Every git
call degrades gracefully: a non-git directory or missing git yields empty/false fields, not an error.
No imports from siblings (leaf)."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


def _git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(repo_root), capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def find_repo_root(start: Path | None = None) -> Path:
    start = Path(start or Path.cwd())
    top = _git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else start.resolve()


def is_git_repo(path: Path) -> bool:
    return _git(path, "rev-parse", "--is-inside-work-tree") == "true"


def _sanitize_remote(url: str) -> dict:
    if not url:
        return {"remote_sanitized": "", "remote_sha256": ""}
    # strip any user:pass@ credentials before storing
    sanitized = re.sub(r"://[^/@]*@", "://", url)
    digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16]
    return {"remote_sanitized": sanitized, "remote_sha256": digest}


def _parse_porcelain(porcelain: str) -> tuple[list[str], list[str], list[str]]:
    changed, staged, untracked = [], [], []
    for line in porcelain.splitlines():
        if not line or len(line) < 3:
            continue
        index_status, path = line[0], line[3:]
        if line.startswith("??"):
            untracked.append(path)
            continue
        changed.append(path)
        if index_status not in (" ", "?"):
            staged.append(path)
    return changed, staged, untracked


def capture_git_state(repo_root: Path | None = None) -> dict:
    """Snapshot of the repo's git state. All fields present even outside a git repo."""
    repo_root = find_repo_root(repo_root)
    if not is_git_repo(repo_root):
        return {
            "branch": "", "commit": "", "dirty": False, "is_git_repo": False,
            "changed_files": [], "staged_files": [], "untracked_files": [],
            "remote_sanitized": "", "remote_sha256": "",
        }
    porcelain = _git(repo_root, "status", "--porcelain")
    changed, staged, untracked = _parse_porcelain(porcelain)
    state = {
        "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git(repo_root, "rev-parse", "HEAD"),
        "dirty": bool(porcelain.strip()),
        "is_git_repo": True,
        "changed_files": sorted(changed),
        "staged_files": sorted(staged),
        "untracked_files": sorted(untracked),
    }
    state.update(_sanitize_remote(_git(repo_root, "remote", "get-url", "origin")))
    return state
