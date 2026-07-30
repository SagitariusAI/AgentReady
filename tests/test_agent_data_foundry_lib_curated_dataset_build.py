# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.curated_dataset import curated_dataset_root
from agent_data_foundry_lib.curated_dataset_build import (
    SIGNAL_COVERAGE_FAMILIES,
    SIGNAL_COVERAGE_FAMILY_FIELDS,
    _record_has_field,
    build_curated_dataset,
    signal_coverage_report,
    source_signal_safety_report,
)
from agent_data_foundry_lib.gold_corpus import gold_jsonl_path
from agent_data_foundry_lib.io_jsonl import append_jsonl, read_jsonl


def _seed_gold(root: Path) -> None:
    rows = []
    for i in range(4):
        label = ["SUPPORTED_CLAIM", "UNSUPPORTED_PROMOTION"][i % 2]
        rows.append({
            "fingerprint": f"fp{i}", "source_id_hash": f"sid{i}", "incident_type": label,
            "verdict": "SAFE" if label == "SUPPORTED_CLAIM" else "BLOCK",
            "provenance_type": "NATURAL_RECEIPT",
            "input_view": {"claim": "c", "claim_type": "receipt_state_promotion"},
            "claim_evidence_alignment": {"claimed_target": "x", "actual_target": "x"},
            "evidence_profile": {"gate_evidence_present": True, "push_evidence_present": True, "evidence_count": 1},
            "gold_output": {"verdict": "ALLOW", "required_action": "y"},
        })
    append_jsonl(gold_jsonl_path(root), rows)


def test_signal_coverage_constants_consistent():
    assert isinstance(SIGNAL_COVERAGE_FAMILIES, list) and len(SIGNAL_COVERAGE_FAMILIES) >= 5
    # every coverage family has a field spec
    for fam in SIGNAL_COVERAGE_FAMILIES:
        assert fam in SIGNAL_COVERAGE_FAMILY_FIELDS


def test_record_has_field_nested_lookup():
    assert _record_has_field({"a": {"b": 1}}, "a.b") is True
    assert _record_has_field({"a": {}}, "a.b") is False
    assert _record_has_field({"x": 1}, "x") is True
    assert _record_has_field({}, "missing") is False


def test_build_curated_dataset_writes_dataset_and_reports(tmp_path: Path):
    _seed_gold(tmp_path)
    report = build_curated_dataset(tmp_path)
    assert isinstance(report, dict)
    dataset_file = curated_dataset_root(tmp_path) / "curated_dataset_internal.jsonl"
    assert dataset_file.exists()
    dataset_rows = read_jsonl(dataset_file)
    assert len(dataset_rows) == 4  # one per gold row, no fabrication
    # every Dataset row carries data_rights (graded, not fabricated)
    assert all("data_rights" in r for r in dataset_rows)


def test_coverage_and_safety_reports(tmp_path: Path):
    _seed_gold(tmp_path)
    build_curated_dataset(tmp_path)
    cov = signal_coverage_report(tmp_path)
    safety = source_signal_safety_report(tmp_path)
    assert isinstance(cov, dict) and isinstance(safety, dict)


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.build_curated_dataset is build_curated_dataset
    assert adf.signal_coverage_report is signal_coverage_report
    assert adf.build_signal_coverage.__module__ == "agent_data_foundry_lib.curated_dataset_build"
    assert adfl.source_signal_safety_report is source_signal_safety_report
