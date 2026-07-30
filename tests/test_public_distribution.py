from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import agent_runtime_paths
from agent_coordination.store import ensure_state
from agent_publication_guard import scan_source
from factory_capture.store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    return path


def test_source_inventory_has_no_private_or_persistence_payloads():
    findings, count = scan_source(PROJECT_ROOT)
    assert count > 0
    assert findings == []


def test_import_all_public_modules_is_side_effect_free(tmp_path: Path):
    state = tmp_path / "state"
    before = sorted(path.relative_to(PROJECT_ROOT) for path in PROJECT_ROOT.rglob("*") if path.is_file())
    modules = [
        path.stem
        for path in (PROJECT_ROOT / "src").glob("*.py")
        if path.stem != "__init__"
    ]
    modules.extend(("agent_coordination", "factory_capture", "agent_data_foundry_lib"))
    code = "import importlib\n" + "\n".join(f"importlib.import_module({module!r})" for module in sorted(modules))
    env = {
        **os.environ,
        "AGENTREADY_HOME": str(state),
        "FACTORY_CAPTURE_DIR": str(state / "capture"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, check=True, timeout=60)
    after = sorted(path.relative_to(PROJECT_ROOT) for path in PROJECT_ROOT.rglob("*") if path.is_file())
    assert after == before
    assert not state.exists()


def test_factory_capture_initializes_a_new_empty_database(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    store = Store(tmp_path / "runtime" / ".factory_capture")
    assert not store.root.exists()
    result = store.init(repo_root=repo)
    assert result["created"] is True
    assert not store.events_path.exists()
    assert not list(store.logs_dir.iterdir())
    assert not list(store.artifacts_dir.iterdir())
    assert not list(store.sessions_dir.iterdir())
    with sqlite3.connect(store.index_path) as connection:
        assert connection.execute("select count(*) from events").fetchone()[0] == 0
    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    assert config["repo_root"] == str(repo)
    assert store.init(repo_root=repo)["already_existed"] is True


def test_coordination_initializes_empty_state_under_runtime_home(tmp_path: Path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", runtime / "coordination")
    monkeypatch.setattr(agent_runtime_paths, "WORKTREE_ROOT", runtime / "worktrees")
    state = ensure_state(repo)
    for name in agent_runtime_paths.STORE_SUBDIRS:
        assert list((state / name).iterdir()) == []
    assert not (repo / ".agentready" / "gate_status.json").exists()
    assert state.is_relative_to(runtime)
