from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.adjudication import (
    HUMAN_CORRECTION_CARRY_FIELDS,
    carry_human_correction_fields,
    claim_evidence_alignment,
    commercial_safety_flags,
    ensure_natural_provenance_fields,
    gold_coordination_row,
    gold_output,
    natural_provenance_fields,
    receipt_evidence_profile,
    receipt_gold_row,
    receipt_source_id,
    safe_segment,
    silver_coordination_row,
    state_transition,
    task_evidence_profile,
    task_fingerprint,
    task_source_id,
    task_verdict,
)


def test_commercial_safety_defaults_unchanged():
    assert commercial_safety_flags() == {
        "provider_neutral": True, "contains_raw_provider_output": False, "contains_secrets": False,
        "contains_internal_paths": False, "contains_third_party_code": False, "release_eligible": True,
    }


def test_natural_provenance_defaults_and_ensure():
    npf = natural_provenance_fields()
    assert npf["provenance_type"] == "NATURAL_RECEIPT" and npf["source_model_output_used"] is False
    # ensure_ only fills NATURAL/None rows; a CONTROLLED_CASE row is left untouched
    assert ensure_natural_provenance_fields({"provenance_type": "CONTROLLED_CASE"})["provenance_type"] == "CONTROLLED_CASE"
    assert ensure_natural_provenance_fields({"x": 1})["provenance_type"] == "NATURAL_RECEIPT"


def test_task_verdict_bar():
    assert task_verdict({"blockers": ["b"]})[:2] == ("NEEDS_HUMAN", "COMPLETION_BY_DEFERRAL")
    assert task_verdict({"evidence": ["gate pass", "push to main"]})[:2] == ("SAFE", "SUPPORTED_CLAIM")
    assert task_verdict({"evidence": ["note"]})[:2] == ("SUSPICIOUS", "CLAIM_WITHOUT_EVIDENCE")


def test_task_evidence_profile_signals():
    p = task_evidence_profile({"evidence": ["pytest passed", "git push origin"], "blockers": []})
    assert p["has_gate_signal"] is True and p["has_push_signal"] is True and p["has_blockers"] is False


def test_gold_output_verdict_mapping_verbatim():
    assert gold_output("SAFE", "X", "")["verdict"] == "ALLOW"
    assert gold_output("BLOCK", "COMPLETION_BY_DEFERRAL", "")["verdict"] == "HUMAN_REVIEW"
    assert gold_output("BLOCK", "UNSUPPORTED_PROMOTION", "")["verdict"] == "BLOCK"
    assert gold_output("BLOCK", "OTHER", "")["required_action"] == "REJECT_PROMOTION"
    assert "gate and delivery evidence" in gold_output("SAFE", "X", "")["model_should_learn"]


def test_state_transition_promotion_allowed_only_when_safe():
    safe = state_transition({"evidence": ["gate pass", "push"]}, "SAFE", "SUPPORTED_CLAIM")
    assert safe["promotion_allowed"] is True and safe["promotion_denial_reason"] == ""
    blk = state_transition({"blockers": ["b"]}, "NEEDS_HUMAN", "COMPLETION_BY_DEFERRAL")
    assert blk["promotion_allowed"] is False and blk["promotion_denial_reason"]


def test_claim_evidence_alignment_shape():
    a = claim_evidence_alignment({"evidence": ["gate"]}, "BLOCK", "CLAIM_WITHOUT_EVIDENCE")
    assert a["claim_type"] == "governed_task_state_transition" and a["claim_supported"] is False
    assert a["agent_corrected_only_after_evidence"] is False


def test_source_id_and_fingerprint_deterministic():
    assert receipt_source_id({"receipt_id": "r1"}, "SUPPORTED_CLAIM") == "receipt/r1/SUPPORTED_CLAIM"
    sid = task_source_id("repo-1", {"id": "t1"}, Path("x/y.json"))
    assert sid == "repo-1/t1"
    fp1 = task_fingerprint(sid, {"id": "t1"})
    fp2 = task_fingerprint(sid, {"id": "t1"})
    assert fp1 == fp2 and len(fp1) == 64  # sha256, stable


def test_receipt_gold_row_fields_and_schema():
    receipt = {"receipt_id": "r1", "outcome": "did x", "evidence": [{"path": "src/x.py"}],
               "quality": {"passed": True}, "repo": r"C:\Factory"}
    row = receipt_gold_row(receipt, "SUPPORTED_CLAIM", "SAFE", "ok")
    assert row["schema_version"] == "sf.product_incident.v0.2"
    assert row["incident_type"] == "SUPPORTED_CLAIM" and row["verdict"] == "SAFE"
    assert row["provenance_type"] == "NATURAL_RECEIPT"  # from natural_provenance_fields
    for key in ("claim_evidence_alignment", "state_transition", "gold_output", "commercial_safety",
                "evidence_profile", "source_signals", "input_view"):
        assert key in row, key
    assert row["commercial_safety"]["provider_neutral"] is True


def test_gold_coordination_row_carries_human_correction():
    task = {"id": "t1", "status": "completed", "evidence": ["gate pass", "push"],
            "founder_override_reason": "verified push receipt"}
    row = gold_coordination_row("sid", "fp", task)
    assert row["schema_version"] == "sf.product_incident.v0.2"
    assert row["founder_override_reason"] == "verified push receipt"  # carried verbatim
    assert "founder_override_reason" in HUMAN_CORRECTION_CARRY_FIELDS


def test_silver_row_and_safe_segment():
    row = silver_coordination_row("repo", Path("x/y.json"), "sid", "fp", {"id": "t1", "status": "completed"})
    assert row["schema_version"] == "agentready.data_foundry.coordination_silver.v1"
    assert row["source_id"] == "sid" and "captured_at" in row
    assert safe_segment("a/b c") == "a_b_c" and safe_segment("") == "unknown"


def test_carry_human_correction_only_present_fields():
    out = carry_human_correction_fields({"a": 1}, {"human_correction": "x", "review_decision": "", "unrelated": "y"})
    assert out["human_correction"] == "x" and "review_decision" not in out and "unrelated" not in out


def test_receipt_evidence_profile_gate_from_quality():
    p = receipt_evidence_profile({"evidence": [1], "quality": {"passed": True}, "promotion_blockers": []})
    assert p["gate_evidence_present"] is True and p["blockers_present"] is False


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    # the 8-name external surface is re-exported from agent_data_foundry
    assert adf.receipt_gold_row is receipt_gold_row
    assert adf.gold_coordination_row is gold_coordination_row
    assert adf.silver_coordination_row is silver_coordination_row
    assert adf.commercial_safety_flags is commercial_safety_flags
    assert adf.ensure_natural_provenance_fields is ensure_natural_provenance_fields
    assert adf.task_source_id is task_source_id
    assert adf.task_fingerprint is task_fingerprint
    assert adf.safe_segment is safe_segment
