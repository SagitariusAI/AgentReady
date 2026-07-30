# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Work-state gates — the mechanical enforcement of the constitution.

A 'complete' handoff (or a push) over a dirty or gate-red/stale tree must be
REFUSED; a 'wip' handoff is allowed but labelled incomplete. The gate's own
marker dir never counts as dirty.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent_workstate as ws  # noqa: E402


def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True)
    return str(r)


def _commit(repo, name="f.txt", text="x"):
    (Path(repo) / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "c"], check=True, capture_output=True)


def test_dirty_tree_blocks_complete_allows_wip(tmp_path):
    repo = _repo(tmp_path)
    (Path(repo) / "a.txt").write_text("a", encoding="utf-8")  # uncommitted
    assert ws.evaluate_handoff(repo, "complete")["allow"] is False
    wip = ws.evaluate_handoff(repo, "wip")
    assert wip["allow"] is True
    assert "INCOMPLETE" in wip["label"]


def test_clean_no_marker_allows_complete_with_note(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo)
    v = ws.evaluate_handoff(repo, "complete")
    assert v["allow"] is True
    assert any("could not be verified" in r for r in v["reasons"])  # honest note, not a block


def test_green_marker_at_head_allows_complete(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo)
    ws.write_gate_marker(repo, "pass", "full_sweep")
    v = ws.evaluate_handoff(repo, "complete")
    assert v["allow"] is True and v["gate"]["green"] is True
    # the marker itself must NOT make the tree look dirty
    assert ws.tree_state(repo)["clean"] is True


def test_stale_or_failed_gate_blocks_complete(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo)
    ws.write_gate_marker(repo, "pass", "full_sweep")  # green @ c1
    _commit(repo, name="b.txt")                       # HEAD moves -> marker stale
    v = ws.evaluate_handoff(repo, "complete")
    assert v["allow"] is False
    assert any("STALE" in r or "NOT green" in r for r in v["reasons"])
    # an explicit fail also blocks
    ws.write_gate_marker(repo, "fail", "full_sweep")
    assert ws.evaluate_handoff(repo, "complete")["allow"] is False


def test_push_gate_requires_clean_tree_and_green_at_head(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo)
    ws.write_gate_marker(repo, "pass", "full_sweep")
    assert ws.main(["push-gate", "--repo", repo]) == 0            # green @ HEAD
    # Generated or forgotten dirt is not silently shipped around the release
    # boundary: clean+green is the hard pre-push contract.
    (Path(repo) / "d.txt").write_text("d", encoding="utf-8")
    assert ws.main(["push-gate", "--repo", repo]) == 5
    (Path(repo) / "d.txt").unlink()
    # but a NEW commit makes the marker stale -> refuse (HEAD no longer swept).
    _commit(repo, name="e.txt")
    assert ws.main(["push-gate", "--repo", repo]) == 5


def test_handoff_complete_scopes_dirty_to_claimed_paths(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo)
    ws.write_gate_marker(repo, "pass", "full_sweep")
    # another lane leaves an unrelated file uncommitted
    (Path(repo) / "other_lane.txt").write_text("x", encoding="utf-8")
    # my claimed path is clean -> complete OK despite the other lane's dirt
    assert ws.evaluate_handoff(repo, "complete", paths=["mine.py"])["allow"] is True
    # if MY claimed path is dirty -> blocked
    (Path(repo) / "mine.py").write_text("dirty", encoding="utf-8")
    assert ws.evaluate_handoff(repo, "complete", paths=["mine.py"])["allow"] is False
