# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from agent_data_foundry_lib.paired_curriculum import (
    _PAIRED_CURRICULUM_LABEL_MAP,
    _paired_curriculum_grade,
    build_paired_curriculum_block,
)

_BLOCK_KEYS = {"schema_version", "pair_id", "pair_status", "sign", "grade", "lang",
               "anchors", "workflow_spine", "insufficiency", "overlay", "meta"}


def test_paired_curriculum_positive_block_fields() -> None:
    block = build_paired_curriculum_block({}, "SUPPORTED_CLAIM", {"evidence_claim": "paired"})
    assert set(block) == _BLOCK_KEYS
    assert block["schema_version"] == "sf.paired_curriculum_curriculum.v0.1"
    assert block["sign"] == "+" and block["anchors"] == ["EVIDENCE", "ROUNDTRIP"]
    assert block["pair_id"] == "paired_curriculum-pair-evidence_claim" and block["pair_status"] == "paired"
    assert block["insufficiency"] == {"kind": None, "repair_target": None}  # + has no insufficiency
    assert block["overlay"] == {"kind": "NONE", "notes": None}
    assert block["meta"] == {"curriculum": "PairedCurriculum", "rights_scope": "restricted_use", "source": "curated_dataset"}


def test_paired_curriculum_negative_insufficiency_and_unpaired() -> None:
    block = build_paired_curriculum_block({}, "CLAIM_WITHOUT_EVIDENCE", {})  # no pair status -> unpaired
    assert block["sign"] == "-" and block["pair_status"] == "unpaired"
    assert block["anchors"] == ["EVIDENCE", "BOOLEAN"]
    assert block["insufficiency"] == {"kind": "missing_evidence", "repair_target": "provide_evidence_receipts"}


def test_paired_curriculum_owner_correction_overrides_spine() -> None:
    row = {"human_correction_lineage": {"correction_source": "owner_override"}}
    block = build_paired_curriculum_block(row, "CLAIM_WITHOUT_EVIDENCE", {})
    assert block["workflow_spine"] == ["owner_correction", "rule_update", "future_guardrail"]


def test_paired_curriculum_grade_bands() -> None:
    assert _paired_curriculum_grade({}) == "G3"  # bare record
    one = {"signal_coverage": {"families": {"a": {"status": "present"}}}}
    assert _paired_curriculum_grade(one) == "G4"
    two = {"signal_coverage": {"families": {"a": {"status": "present"}, "b": {"status": "partial"}}}}
    assert _paired_curriculum_grade(two) == "G5"


def test_paired_curriculum_sign_mapping_stable_no_fabricated_positives() -> None:
    # exactly one label is "+"; the rest are "-" (sign mapping must not drift)
    plus = sorted(lbl for lbl, (sign, _a) in _PAIRED_CURRICULUM_LABEL_MAP.items() if sign == "+")
    assert plus == ["SUPPORTED_CLAIM"]


def test_paired_curriculum_reexported_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.build_paired_curriculum_block is build_paired_curriculum_block
    assert adf._PAIRED_CURRICULUM_LABEL_MAP is _PAIRED_CURRICULUM_LABEL_MAP
    assert adf._PAIRED_CURRICULUM_FAMILY["SUPPORTED_CLAIM"] == "evidence_claim"
