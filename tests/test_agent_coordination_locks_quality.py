from __future__ import annotations

import subprocess

import pytest

import agent_runtime_paths
from agent_coordination import locks, quality


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=str(r), capture_output=True, check=True)
    return r


# --------------------------------------------------------------------------- locks
def test_set_locks_writes_one_file_per_path(repo):
    task = {"id": "t1", "agent": "claude", "status": "claimed", "paths": ["src/a.py", "src/b.py"]}
    written = locks.set_locks(repo, task)
    assert len(written) == 2 and written[0] == locks.lock_hash("src/a.py")
    state = agent_runtime_paths.state_root(repo)
    import json
    lock = json.loads((state / "locks" / f"{written[0]}.json").read_text(encoding="utf-8"))
    assert lock["task_id"] == "t1" and lock["path"] == "src/a.py" and lock["agent"] == "claude"


def test_remove_locks_only_removes_owning_task(repo):
    locks.set_locks(repo, {"id": "t1", "agent": "a", "status": "claimed", "paths": ["src/a.py"]})
    locks.set_locks(repo, {"id": "t2", "agent": "b", "status": "claimed", "paths": ["src/b.py"]})
    removed = locks.remove_locks(repo, "t1")
    assert removed == 1
    state = agent_runtime_paths.state_root(repo)
    remaining = list((state / "locks").glob("*.json"))
    assert len(remaining) == 1  # t2's lock survives


def test_lock_hash_is_deterministic_16_hex():
    h = locks.lock_hash("src/x.py")
    assert h == locks.lock_hash("src/x.py") and len(h) == 16


# --------------------------------------------------------------------------- quality gates
def test_text_length_trims():
    assert quality.text_length("  hi  ") == 2 and quality.text_length(None) == 0


def test_task_start_quality_thresholds():
    issues = quality.task_start_quality(title="x", summary="short", paths=[])
    assert any("Title" in i for i in issues)
    assert any("Summary" in i for i in issues)
    assert any("Paths" in i for i in issues)
    assert quality.task_start_quality(title="Fix the data foundry split",
                                      summary="extract the controlled-case generators",
                                      paths=["src/a.py"]) == []


def test_task_start_quality_enforces_protected_intent():
    issues = quality.task_start_quality(title="Add a thing here please",
                                        summary="implement the requested change now",
                                        paths=["tests/test_x.py"])
    assert any("protected" in i.lower() for i in issues)


def test_claim_quality_requires_paths():
    assert quality.claim_quality([]) and quality.claim_quality(["src/a.py"]) == []


def test_handoff_quality_all_four_checks():
    issues = quality.handoff_quality({"summary": "", "paths": []}, summary="", evidence="", next_action="")
    assert len(issues) == 4
    ok = quality.handoff_quality(
        {"summary": "did the thing completely", "paths": ["src/a.py"]},
        summary="split the module into leaves", evidence="944 tests pass, byte-identical smoke",
        next_action="proceed to phase 2")
    assert ok == []


def test_quality_failure_message_format():
    msg = quality.quality_failure_message("Handoff", ["a", "b"], override="-AllowWeak")
    assert msg.startswith("Handoff quality gate failed:")
    assert "- a" in msg and "- b" in msg and "-AllowWeak" in msg
