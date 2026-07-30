# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_lib.harvest import (
    COORDINATION_ELIGIBLE_STATUSES,
    COORDINATION_HARVEST_SCHEMA,
    EXPORT_FOLDERS,
    build_data_foundry,
    evidence_text,
    harvest_coordination_records,
    metadata,
    rejection_reasons,
)


def _write_receipt(root: Path, name: str, payload: dict) -> None:
    p = root / "coordination" / "repoA" / "task-reports" / "t1" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_harvest_constants_stable():
    assert COORDINATION_HARVEST_SCHEMA == "agentready.data_foundry.coordination_harvest.v1"
    assert COORDINATION_ELIGIBLE_STATUSES == {"completed", "closed", "handoff"}
    assert "instruction_jsonl" in EXPORT_FOLDERS


def test_evidence_text_and_rejection_reasons():
    assert isinstance(evidence_text({"evidence": [{"path": "x"}]}), str)
    reasons = rejection_reasons({"quality": {"score": 0}}, 50)
    assert isinstance(reasons, list)


def test_metadata_shape():
    md = metadata({"receipt_id": "r1", "intent": "do x"})
    assert isinstance(md, dict)


def test_harvest_coordination_records_writes_shelf(tmp_path: Path):
    # a completed receipt with evidence -> harvested into the silver/gold shelf
    _write_receipt(tmp_path, "r1", {
        "receipt_id": "r1", "status": "completed", "repo": r"C:\Factory",
        "outcome": "did x", "evidence": [{"path": "src/x.py"}], "quality": {"passed": True},
    })
    result = harvest_coordination_records(tmp_path, coordination_root=tmp_path / "coordination")
    assert isinstance(result, dict) and "summary" in result


def test_build_data_foundry_runs(tmp_path: Path):
    _write_receipt(tmp_path, "r1", {
        "receipt_id": "r1", "status": "completed", "repo": r"C:\Factory", "work_product_policy": "company_owned_internal_reuse",
        "outcome": "did x", "evidence": [{"path": "src/x.py"}], "quality": {"passed": True, "score": 90},
        "artifact_type": "code", "intent": "ship", "dataset_format": "instruction_jsonl",
    })
    result = build_data_foundry(tmp_path)
    assert isinstance(result, dict)


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.build_data_foundry is build_data_foundry
    assert adf.harvest_coordination_records is harvest_coordination_records
    assert adfl.build_data_foundry is build_data_foundry
