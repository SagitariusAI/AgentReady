from __future__ import annotations

import subprocess

from factory_capture.hooks import HOOK_NAMES, MARKER, hooks_state, install_hooks, uninstall_hooks


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    return path


def test_install_creates_all_hooks_with_marker(tmp_path):
    repo = _git_repo(tmp_path / "r")
    result = install_hooks(repo)
    assert set(result) == set(HOOK_NAMES)
    state = hooks_state(repo)
    for name in HOOK_NAMES:
        hook = repo / ".git" / "hooks" / name
        assert hook.exists() and MARKER in hook.read_text(encoding="utf-8")
        assert state[name] is True


def test_install_reports_not_a_git_repo(tmp_path):
    assert "error" in install_hooks(tmp_path / "plain")


def test_install_backs_up_and_wraps_existing_user_hook(tmp_path):
    repo = _git_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho USER_HOOK\n", encoding="utf-8")
    result = install_hooks(repo)
    assert result["post-commit"] == "wrapped_existing"
    backup = repo / ".git" / "hooks" / "post-commit.factory-capture-backup"
    assert backup.exists() and "USER_HOOK" in backup.read_text(encoding="utf-8")
    # our hook chains to the backup so the user hook still runs
    assert "factory-capture-backup" in hook.read_text(encoding="utf-8")


def test_uninstall_removes_ours_and_restores_backup(tmp_path):
    repo = _git_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho USER_HOOK\n", encoding="utf-8")
    install_hooks(repo)
    result = uninstall_hooks(repo)
    assert result["post-commit"] == "restored_backup"
    assert "USER_HOOK" in hook.read_text(encoding="utf-8")
    assert MARKER not in hook.read_text(encoding="utf-8")
    # a hook with no prior backup is simply removed
    assert result["post-merge"] == "removed"
    assert not (repo / ".git" / "hooks" / "post-merge").exists()
    assert hooks_state(repo) == {name: False for name in HOOK_NAMES}


def test_uninstall_leaves_unrelated_user_hook(tmp_path):
    repo = _git_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho NOT_OURS\n", encoding="utf-8")
    result = uninstall_hooks(repo)
    assert result["post-commit"] == "left_user_hook"
    assert "NOT_OURS" in hook.read_text(encoding="utf-8")
