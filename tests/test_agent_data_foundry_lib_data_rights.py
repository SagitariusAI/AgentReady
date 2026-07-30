# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_lib.data_rights import DATASET_INTENDED_USES, data_rights_gate
from agent_data_foundry_lib.io_jsonl import append_jsonl


def _dataset(root: Path, rows: list[dict]) -> Path:
    p = root / "dataset.jsonl"
    append_jsonl(p, rows)
    return p


def test_intended_uses_allowlist():
    assert "internal_research" in DATASET_INTENDED_USES
    assert "commercial_sale" in DATASET_INTENDED_USES
    assert len(DATASET_INTENDED_USES) == 5


def test_gate_passes_clean_rows_for_internal_use(tmp_path: Path):
    rows = [{"fingerprint": f"r{i}", "data_rights": {
        "grade": "A_FACTORY_OWNED", "export_allowed": True, "commercial_sale_allowed": True,
        "requires_legal_review": False, "requires_owner_release": False,
        "data_need": "internal_research", "intended_use_allowlist": list(DATASET_INTENDED_USES),
    }} for i in range(3)]
    ds = _dataset(tmp_path, rows)
    report = data_rights_gate(tmp_path, dataset_path=ds, intended_use="internal_research")
    assert report["schema_version"] == "sf.data_rights_gate.v0.1"
    assert report["rows_seen"] == 3 and report["intended_use_recognized"] is True
    assert (ds.parent / "data_rights_gate_report.json").exists()


def test_gate_flags_unrecognized_use(tmp_path: Path):
    ds = _dataset(tmp_path, [{"fingerprint": "r1", "data_rights": {"grade": "A_FACTORY_OWNED"}}])
    report = data_rights_gate(tmp_path, dataset_path=ds, intended_use="not_a_real_use")
    assert report["intended_use_recognized"] is False and report["status"] == "FAIL"


def test_gate_tallies_quarantine_rows(tmp_path: Path):
    rows = [
        {"fingerprint": "r1", "data_rights": {"grade": "F_QUARANTINE"}},
        {"fingerprint": "r2", "data_rights": {"grade": "A_FACTORY_OWNED"}},
    ]
    ds = _dataset(tmp_path, rows)
    report = data_rights_gate(tmp_path, dataset_path=ds, intended_use="internal_research")
    assert report["quarantine_rows"] == 1
    assert report["grade_counts"].get("F_QUARANTINE") == 1
    written = json.loads((ds.parent / "data_rights_gate_report.json").read_text(encoding="utf-8"))
    assert written["quarantine_rows"] == 1


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.data_rights_gate is data_rights_gate
    assert adfl.data_rights_gate is data_rights_gate
    assert adfl.DATASET_INTENDED_USES is DATASET_INTENDED_USES
