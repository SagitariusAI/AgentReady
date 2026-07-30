from __future__ import annotations

from agent_data_foundry_lib.logosone import (
    _LOGOSONE_LABEL_MAP,
    _logosone_grade,
    build_logosone_block,
)

_BLOCK_KEYS = {"schema_version", "pair_id", "pair_status", "sign", "grade", "lang",
               "anchors", "workflow_spine", "insufficiency", "overlay", "meta"}


def test_logosone_positive_block_fields() -> None:
    block = build_logosone_block({}, "SUPPORTED_CLAIM", {"evidence_claim": "paired"})
    assert set(block) == _BLOCK_KEYS
    assert block["schema_version"] == "sf.logosone_curriculum.v0.1"
    assert block["sign"] == "+" and block["anchors"] == ["EVIDENCE", "ROUNDTRIP"]
    assert block["pair_id"] == "logosone-pair-evidence_claim" and block["pair_status"] == "paired"
    assert block["insufficiency"] == {"kind": None, "repair_target": None}  # + has no insufficiency
    assert block["overlay"] == {"kind": "NONE", "notes": None}
    assert block["meta"] == {"curriculum": "LogosOne", "rights_scope": "internal_only", "source": "factory_dojo"}


def test_logosone_negative_insufficiency_and_unpaired() -> None:
    block = build_logosone_block({}, "CLAIM_WITHOUT_EVIDENCE", {})  # no pair status -> unpaired
    assert block["sign"] == "-" and block["pair_status"] == "unpaired"
    assert block["anchors"] == ["EVIDENCE", "BOOLEAN"]
    assert block["insufficiency"] == {"kind": "missing_evidence", "repair_target": "provide_evidence_receipts"}


def test_logosone_founder_correction_overrides_spine() -> None:
    row = {"human_correction_lineage": {"correction_source": "founder_override"}}
    block = build_logosone_block(row, "CLAIM_WITHOUT_EVIDENCE", {})
    assert block["workflow_spine"] == ["founder_correction", "rule_update", "future_guardrail"]


def test_logosone_grade_bands() -> None:
    assert _logosone_grade({}) == "G3"  # bare record
    one = {"signal_coverage": {"families": {"a": {"status": "present"}}}}
    assert _logosone_grade(one) == "G4"
    two = {"signal_coverage": {"families": {"a": {"status": "present"}, "b": {"status": "partial"}}}}
    assert _logosone_grade(two) == "G5"


def test_logosone_sign_mapping_stable_no_fabricated_positives() -> None:
    # exactly one label is "+"; the rest are "-" (sign mapping must not drift)
    plus = sorted(lbl for lbl, (sign, _a) in _LOGOSONE_LABEL_MAP.items() if sign == "+")
    assert plus == ["SUPPORTED_CLAIM"]


def test_logosone_reexported_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.build_logosone_block is build_logosone_block
    assert adf._LOGOSONE_LABEL_MAP is _LOGOSONE_LABEL_MAP
    assert adf._LOGOSONE_FAMILY["SUPPORTED_CLAIM"] == "evidence_claim"
