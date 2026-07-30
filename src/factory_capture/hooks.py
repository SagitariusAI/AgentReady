# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Git hook install/uninstall for the current repo.

Installs post-commit / post-checkout / post-merge hooks that record a ``git_hook`` capture event.
Hooks are POSIX sh (git runs hooks through sh, even on Windows via Git's bundled shell) and NEVER
block the git operation — capture failures are swallowed with `|| true`. Existing user hooks are not
destroyed: a non-factory hook is backed up to ``<name>.factory-capture-backup`` and chained from ours,
so the user's hook still runs. Uninstall removes only our hooks and restores any backup."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

HOOK_NAMES = ("post-commit", "post-checkout", "post-merge")
MARKER = "# factory-capture-hook v0.1"
BACKUP_SUFFIX = ".factory-capture-backup"


def _hooks_dir(repo_root: Path) -> Path:
    return Path(repo_root) / ".git" / "hooks"


def _factory_capture_src() -> Path:
    """The directory that must be on PYTHONPATH to import factory_capture (i.e. its src root).

    Derived from this module's own location so the hook works when installed into ANY repo, not
    just the one where factory_capture's source happens to live.
    """
    return Path(__file__).resolve().parent.parent


def _script(repo_root: Path, hook_name: str, *, source_root: Path | None = None) -> str:
    # Bake the EXACT interpreter that installed the hook (sys.executable). Relying on a bare `python`
    # is fragile: git runs hooks through its bundled sh, and an inherited venv environment can make a
    # PATH-resolved `python` load the wrong stdlib. Forward slashes work for Windows and POSIX python;
    # sys.path is bootstrapped via `-c` (PYTHONPATH's separator differs by OS).
    python_exe = sys.executable.replace("\\", "/")
    src = str(source_root or _factory_capture_src()).replace("\\", "/")
    boot = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from factory_capture.cli import main; sys.exit(main(sys.argv[2:]))")
    backup = f'"$(dirname "$0")/{hook_name}{BACKUP_SUFFIX}"'
    return (
        "#!/bin/sh\n"
        f"{MARKER} {hook_name}\n"
        "# Installed by factory-capture. Records a git_hook event; never blocks git.\n"
        "# On Windows git runs this via its bundled sh; the interpreter path is baked at install time.\n"
        f'"{python_exe}" -c "{boot}" "{src}" hook {hook_name} >/dev/null 2>&1 || true\n'
        f"if [ -x {backup} ]; then {backup} \"$@\"; fi\n"
    )


def _is_ours(path: Path) -> bool:
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def install_hooks(repo_root: Path, *, source_root: Path | None = None) -> dict:
    """Install/refresh the factory-capture hooks. Returns {hook_name: action}."""
    hooks_dir = _hooks_dir(repo_root)
    if not hooks_dir.parent.exists():
        return {"error": "not a git repo (no .git directory)"}
    hooks_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for name in HOOK_NAMES:
        path = hooks_dir / name
        action = "installed"
        if path.exists() and not _is_ours(path):
            backup = path.with_name(name + BACKUP_SUFFIX)
            if not backup.exists():
                backup.write_bytes(path.read_bytes())  # preserve the user hook byte-for-byte
            action = "wrapped_existing"
        elif path.exists():
            action = "refreshed"
        # write LF-exact bytes: git runs hooks via sh, which rejects CRLF shebangs on POSIX/WSL
        path.write_bytes(_script(repo_root, name, source_root=source_root).encode("utf-8"))
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        results[name] = action
    return results


def uninstall_hooks(repo_root: Path) -> dict:
    """Remove only our hooks; restore any backed-up user hook. Returns {hook_name: action}."""
    hooks_dir = _hooks_dir(repo_root)
    results: dict[str, str] = {}
    for name in HOOK_NAMES:
        path = hooks_dir / name
        backup = path.with_name(name + BACKUP_SUFFIX)
        if path.exists() and _is_ours(path):
            if backup.exists():
                path.write_bytes(backup.read_bytes())  # restore the user hook byte-for-byte
                os.remove(backup)
                results[name] = "restored_backup"
            else:
                os.remove(path)
                results[name] = "removed"
        else:
            results[name] = "skipped" if not path.exists() else "left_user_hook"
    return results


def hooks_state(repo_root: Path) -> dict:
    """Which factory-capture hooks are currently installed."""
    hooks_dir = _hooks_dir(repo_root)
    return {name: (hooks_dir / name).exists() and _is_ours(hooks_dir / name) for name in HOOK_NAMES}
