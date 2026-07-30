from __future__ import annotations

import json
import subprocess

import pytest

import agent_runtime_paths
from agent_coordination import store


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    # Redirect coordination so tests never touch an installed AgentReady state store.
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=str(r), capture_output=True, check=True)
    return r


def test_ensure_state_creates_full_layout(repo):
    state = store.ensure_state(repo)
    for sub in agent_runtime_paths.STORE_SUBDIRS:
        assert (state / sub).is_dir()
    assert (state / "README.md").exists()
    assert state.parent == agent_runtime_paths.COORDINATION_ROOT


def test_ensure_state_writes_pointer(repo):
    store.ensure_state(repo)
    pointer = json.loads((repo / ".agent-state" / "pointer.json").read_text(encoding="utf-8"))
    assert pointer["version"] == 1
    assert pointer["repo"] == str(agent_runtime_paths.resolve_repo(repo))
    assert "coordination" in pointer["shared_state"] and pointer["worktree_root"]


def test_ensure_state_registers_git_exclude(repo):
    store.ensure_state(repo)
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".agent-state/" in exclude and ".agentready/" in exclude


def test_ensure_state_is_idempotent(repo):
    a = store.ensure_state(repo)
    b = store.ensure_state(repo)
    assert a == b
    # exclude not duplicated on the second run
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count(".agent-state/") == 1


def test_ensure_state_rejects_file_as_repo_root(tmp_path, monkeypatch):
    """Regression: FACTORY-ANOMALY-20260620-claim-helper-path-misparse.

    A file path leaking into the repo root (e.g. a space-separated `-Paths a b c` value
    spilling into the wrapper's positional `-Repo`) must be rejected with a clear error
    BEFORE any state is created -- not crash mid-`mkdir` with `.agent-state` under a file
    (which silently aborted task-start, leaving no coordination task record).
    """
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    leaked = tmp_path / "stage_forge_deploy_tarball.sh"
    leaked.write_text("echo x", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="must be a directory"):
        store.ensure_state(leaked)
    # must not have created a .agent-state under/!beside the file
    assert not (leaked / ".agent-state").exists()
