# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from agent_data_foundry_lib.rights import (
    DATA_RIGHTS_GRADES,
    INCIDENT_NEED_MAP,
    data_rights_gate_row,
    default_data_need,
    default_data_rights,
    infer_data_need_from_incident,
    infer_data_rights_from_record,
    infer_model_origin_from_record,
    quarantine_data_rights_for_signal,
    validate_data_need,
    validate_data_rights,
)


def test_default_rights_are_restricted_use_and_locked_down() -> None:
    rights = default_data_rights()
    assert rights["grade"] == "A_INTERNAL_RESEARCH_ONLY"
    # conservative defaults: nothing external, both gates required
    assert rights["export_allowed"] is False
    assert rights["external_eval_allowed"] is False
    assert rights["external_training_allowed"] is False
    assert rights["commercial_sale_allowed"] is False
    assert rights["requires_legal_review"] is True
    assert rights["requires_owner_release"] is True
    assert validate_data_rights(rights) == []


def test_default_need_validates() -> None:
    assert validate_data_need(default_data_need()) == []
    assert "data_need.primary_need:invalid" in validate_data_need(default_data_need(primary_need="SELL_NOW"))
    assert "data_need.technical_value:invalid" in validate_data_need(default_data_need(technical_value="PRICELESS"))


def test_candidate_is_not_cleared_export_stays_false() -> None:
    # provider-neutral + product-shaped => external-eval CANDIDATE, but export is
    # still not granted: candidate != cleared.
    rights = infer_data_rights_from_record({
        "commercial_safety": {"provider_neutral": True, "release_eligible": True},
        "release_eligible": True,
    })
    assert rights["grade"] == "C_EXTERNAL_EVAL_CANDIDATE"
    assert rights["external_eval_allowed"] is True
    assert rights["export_allowed"] is False  # candidate, not cleared
    assert validate_data_rights(rights) == []


def test_external_training_candidate_requires_license_evidence() -> None:
    with_license = infer_data_rights_from_record({
        "commercial_safety": {"provider_neutral": True, "release_eligible": True},
        "release_eligible": True,
        "license_evidence_path": "10_intake/licenses/sample.json",
    })
    assert with_license["grade"] == "D_EXTERNAL_TRAINING_CANDIDATE"
    assert with_license["license_evidence_path"] == "10_intake/licenses/sample.json"
    assert validate_data_rights(with_license) == []
    # a D grade asserting external_training without evidence must fail validation
    forged = default_data_rights(grade="D_EXTERNAL_TRAINING_CANDIDATE", external_training_allowed=True)
    assert "data_rights.external_training_allowed:requires_license_evidence" in validate_data_rights(forged)


def test_no_fabricated_commercial_clearance() -> None:
    # commercial_sale_allowed without owner/legal clearance must not validate
    forged = default_data_rights(grade="D_EXTERNAL_TRAINING_CANDIDATE", commercial_sale_allowed=True)
    failures = validate_data_rights(forged)
    assert "data_rights.commercial_sale_allowed:requires_owner_and_legal_clearance" in failures


def test_secrets_and_raw_output_quarantine() -> None:
    rights = infer_data_rights_from_record({"commercial_safety": {"contains_secrets": True}})
    assert rights["grade"] == "F_QUARANTINE"
    assert rights["export_allowed"] is False and rights["external_eval_allowed"] is False
    raw = infer_data_rights_from_record({"commercial_safety": {"contains_raw_provider_output": True, "provider_neutral": True, "release_eligible": True}})
    assert raw["grade"] == "F_QUARANTINE"  # raw provider output forces quarantine even if provider-neutral


def test_quarantine_for_signal_is_remediation_only() -> None:
    rights = quarantine_data_rights_for_signal("historical_chat_segment_secret")
    assert rights["grade"] == "F_QUARANTINE"
    assert rights["allowed_uses"] == ["remediation", "redaction", "legal_review"]
    for field in ("export_allowed", "external_eval_allowed", "external_training_allowed", "commercial_sale_allowed"):
        assert rights[field] is False
    assert validate_data_rights(rights) == []


def test_model_name_never_inferred_from_unknown_agent() -> None:
    origin = infer_model_origin_from_record({"agent": "mystery-bot"})
    assert origin["provider"] == "unknown"
    assert origin["model_name"] == "mystery-bot"  # the agent label, never a real model identity
    assert origin["model_license_family"] == "unknown"
    assert origin["execution_mode"] == "unknown"
    # known agent maps to provider TOS, not a fabricated model name
    claude = infer_model_origin_from_record({"agent": "Claude"})
    assert claude["provider"] == "anthropic" and claude["model_license_family"] == "frontier_tos"


def test_controlled_case_is_not_model_generated() -> None:
    origin = infer_model_origin_from_record({"provenance_type": "CONTROLLED_CASE"})
    assert origin["provider"] == "agentready_factory"
    assert origin["model_license_family"] == "not_model_generated"
    assert origin["raw_output_included"] is False


def test_incident_need_map_drives_technical_value() -> None:
    assert infer_data_need_from_incident({"incident_type": "MISDIRECTED_VERIFICATION"})["technical_value"] == "CRITICAL"
    unknown = infer_data_need_from_incident({"incident_type": "SOMETHING_NEW"})
    assert unknown["primary_need"] == "FACTORY_DATASET_INTERNAL"
    assert validate_data_need(unknown) == []
    assert "DOCTRINE_DRIFT" in INCIDENT_NEED_MAP


def test_gate_row_candidate_fails_external_eval() -> None:
    # a grade-C candidate row (export_allowed=false) is NOT eligible for external_eval
    candidate = {
        "data_need": default_data_need(),
        "data_rights": infer_data_rights_from_record({
            "commercial_safety": {"provider_neutral": True, "release_eligible": True},
            "release_eligible": True,
        }),
    }
    ok, reason = data_rights_gate_row(candidate, "external_eval")
    assert ok is False and reason == "export_allowed_false"
    # the same row IS eligible for internal_research
    ok2, _ = data_rights_gate_row(candidate, "internal_research")
    assert ok2 is True


def test_gate_row_quarantine_blocks_internal_research() -> None:
    row = {"data_need": default_data_need(), "data_rights": quarantine_data_rights_for_signal("x")}
    ok, reason = data_rights_gate_row(row, "internal_research")
    assert ok is False and reason == "grade_F_quarantine_not_allowed"


def test_grades_catalogue_is_six_grades() -> None:
    assert DATA_RIGHTS_GRADES[0] == "A_INTERNAL_RESEARCH_ONLY"
    assert DATA_RIGHTS_GRADES[-1] == "F_QUARANTINE"
    assert len(DATA_RIGHTS_GRADES) == 6


def test_reexported_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.default_data_need is default_data_need
    assert adf.default_data_rights is default_data_rights
    assert adf.infer_data_need_from_incident is infer_data_need_from_incident
    assert adf.infer_data_rights_from_record is infer_data_rights_from_record
    assert adf.infer_model_origin_from_record is infer_model_origin_from_record
    assert adf.quarantine_data_rights_for_signal is quarantine_data_rights_for_signal
    assert adf.validate_data_need is validate_data_need
    assert adf.validate_data_rights is validate_data_rights
    assert adf.data_rights_gate_row is data_rights_gate_row
    assert adf.INCIDENT_NEED_MAP is INCIDENT_NEED_MAP
