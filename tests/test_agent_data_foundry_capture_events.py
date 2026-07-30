# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_data_foundry_lib.capture_events import harvest_capture_events
from agent_data_foundry_lib.io_jsonl import read_jsonl
from factory_capture.governed import ACTIVE_ENV, auto_capture_current_process
from factory_capture.runner import run_command
from factory_capture.store import Store


def _store(repo: Path) -> Store:
    repo.mkdir(parents=True, exist_ok=True)
    store = Store(repo / ".factory_capture")
    store.init(repo_root=repo)
    return store


def test_capture_event_harvest_preserves_logs_lineage_and_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    store = _store(repo)
    event = run_command(
        store,
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        cwd=repo,
        workflow_lane="research",
        provenance={"source_type": "agentready_command_surface", "surface": "test"},
    )

    first = harvest_capture_events(tmp_path, capture_roots=[repo])
    second = harvest_capture_events(tmp_path, capture_roots=[repo])

    assert first["summary"]["captured"] == 1
    assert first["summary"]["research_command_rows"] == 1
    assert second["summary"]["skipped_existing"] == 1
    gold = read_jsonl(tmp_path / first["gold_path"])
    assert len(gold) == 1
    assert gold[0]["provenance_type"] == "CAPTURE_EVENT"
    lineage = gold[0]["source_lineage"]
    assert lineage["event_id"] == event["event_id"]
    bronze = json.loads((tmp_path / lineage["bronze_path"]).read_text(encoding="utf-8"))
    assert bronze["redacted_logs"] == {"stdout": "out\n", "stderr": "err\n"}
    assert bronze["event"]["stdout_sha256"] == event["stdout_sha256"]


def test_capture_event_harvest_keeps_cross_lane_out_of_research_gold(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    store = _store(repo)
    run_command(
        store,
        [sys.executable, "-c", "print('business')"],
        cwd=repo,
        workflow_lane="business",
    )
    result = harvest_capture_events(tmp_path, capture_roots=[repo])
    assert result["summary"]["captured"] == 1
    assert result["summary"]["cross_lane_rows"] == 1
    assert result["summary"]["research_command_rows"] == 0
    assert read_jsonl(tmp_path / result["gold_path"]) == []


def test_governed_surface_captures_exit_and_avoids_recursive_wrap(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    store = _store(repo)
    script = tmp_path / "surface.py"
    script.write_text(
        "import sys\nprint('surface-out')\nprint('surface-err', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FACTORY_CAPTURE_DIR", str(store.root))
    monkeypatch.delenv(ACTIVE_ENV, raising=False)
    exit_code = auto_capture_current_process(
        surface="agent-test",
        argv=[str(script)],
        cwd=repo,
    )
    assert exit_code == 7
    events = read_jsonl(store.events_path)
    assert len(events) == 1
    assert events[0]["provenance"]["surface"] == "agent-test"
    assert (store.root / events[0]["stdout_log"]).read_text(encoding="utf-8") == "surface-out\n"
    assert (store.root / events[0]["stderr_log"]).read_text(encoding="utf-8") == "surface-err\n"

    monkeypatch.setenv(ACTIVE_ENV, "1")
    assert auto_capture_current_process(surface="agent-test", argv=[str(script)], cwd=repo) is None
    assert len(read_jsonl(store.events_path)) == 1
