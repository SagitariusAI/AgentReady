# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_report_contract import repair_report_contracts


def test_repair_report_contracts_creates_latest_pointers_for_legacy_report_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "Repo"
    repo.mkdir()
    report_dir = repo / ".agent-reports" / "ci"
    report_dir.mkdir(parents=True)
    legacy_log = report_dir / "agent-ci-local-latest.log"
    legacy_log.write_text("Agent local CI: demo\nEXIT pytest tests = 0\n", encoding="utf-8")

    results = repair_report_contracts(repo, surfaces=["ci"])

    assert results[0]["surface"] == "ci"
    assert results[0]["status"] == "ok"
    assert (report_dir / "latest.md").exists()
    assert (report_dir / "latest.json").exists()
    payload = json.loads((report_dir / "latest.json").read_text(encoding="utf-8"))
    assert payload["primary"].endswith("agent-ci-local-latest.log")
    assert payload["surface"] == "ci"


def test_repair_report_contracts_preserves_existing_latest_json_semantics(tmp_path: Path) -> None:
    repo = tmp_path / "Repo"
    repo.mkdir()
    report_dir = repo / ".agent-reports" / "release-scorecard"
    report_dir.mkdir(parents=True)
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    latest_json.write_text(json.dumps({"overall": "PASS", "failures": 0}), encoding="utf-8")
    latest_md.write_text("# scorecard\n", encoding="utf-8")
    (report_dir / "scorecard.md").write_text("# older scorecard\n", encoding="utf-8")

    results = repair_report_contracts(repo, surfaces=["release-scorecard"])

    assert results[0]["status"] == "preserved"
    assert json.loads(latest_json.read_text(encoding="utf-8")) == {"overall": "PASS", "failures": 0}
