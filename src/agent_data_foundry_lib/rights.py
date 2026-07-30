# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Data rights / needs / grading helpers for the Agent Data Foundry."""
from __future__ import annotations

from typing import Any

from agent_data_foundry_lib.io_jsonl import as_dict, now_utc

DATA_NEED_PRIMARY_VALUES = [
    "FACTORY_DATASET_INTERNAL",
    "CLAIM_EVIDENCE_SENTINEL_TRAINING",
    "CLAIM_EVIDENCE_ALIGNMENT",
    "COMPLETION_INTEGRITY",
    "VAULT_CODE_MAPPING",
    "TEST_INTEGRITY",
    "TOOL_USE_DISCIPLINE",
    "RETRIEVAL_GROUNDING",
    "DOCTRINE_DRIFT_DETECTION",
    "REPAIR_ACTION_PLANNING",
    "EXTERNAL_EVAL_CANDIDATE",
    "EXTERNAL_TRAINING_CANDIDATE",
    "QUARANTINE_REVIEW",
]

TECHNICAL_VALUE_VALUES = [
    "NONE",
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]

DATA_RIGHTS_GRADES = [
    "A_INTERNAL_RESEARCH_ONLY",
    "B_INTERNAL_TRAINING_ALLOWED",
    "C_EXTERNAL_EVAL_CANDIDATE",
    "D_EXTERNAL_TRAINING_CANDIDATE",
    "E_RESTRICTED_DO_NOT_EXPORT",
    "F_QUARANTINE",
]

# incident_type -> (primary_need, technical_value). Unknown incidents fall back to
# FACTORY_DATASET_INTERNAL / MEDIUM.
INCIDENT_NEED_MAP = {
    "CLAIM_WITHOUT_EVIDENCE": ("CLAIM_EVIDENCE_ALIGNMENT", "HIGH"),
    "COMPLETION_BY_DEFERRAL": ("COMPLETION_INTEGRITY", "HIGH"),
    "UNSUPPORTED_PROMOTION": ("COMPLETION_INTEGRITY", "HIGH"),
    "VAULT_CODE_CONFUSION": ("VAULT_CODE_MAPPING", "HIGH"),
    "MISDIRECTED_VERIFICATION": ("CLAIM_EVIDENCE_ALIGNMENT", "CRITICAL"),
    "SUPPORTED_CLAIM": ("CLAIM_EVIDENCE_ALIGNMENT", "MEDIUM"),
    "TEST_THEATER": ("TEST_INTEGRITY", "HIGH"),
    "DOCTRINE_DRIFT": ("DOCTRINE_DRIFT_DETECTION", "CRITICAL"),
}


def default_data_need(
    primary_need: str = "FACTORY_DATASET_INTERNAL",
    technical_value: str = "MEDIUM",
    value_reason: str = "",
    secondary_needs: list[str] | None = None,
    future_model_should_learn: list[str] | None = None,
    recommended_internal_use: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "primary_need": primary_need,
        "secondary_needs": list(secondary_needs or []),
        "technical_value": technical_value,
        "value_reason": value_reason,
        "future_model_should_learn": list(future_model_should_learn or []),
        "recommended_internal_use": list(recommended_internal_use or ["internal_eval"]),
    }


def default_data_rights(
    grade: str = "A_INTERNAL_RESEARCH_ONLY",
    *,
    allowed_uses: list[str] | None = None,
    forbidden_uses: list[str] | None = None,
    export_allowed: bool = False,
    external_eval_allowed: bool = False,
    external_training_allowed: bool = False,
    commercial_sale_allowed: bool = False,
    requires_legal_review: bool = True,
    requires_owner_release: bool = True,
    provider_neutral: bool = False,
    raw_provider_output_present: bool = False,
    license_evidence_path: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "grade": grade,
        "allowed_uses": list(allowed_uses or ["internal_research", "internal_eval"]),
        "forbidden_uses": list(forbidden_uses or ["external_release", "external_training", "commercial_sale", "public_sample_pack"]),
        "export_allowed": bool(export_allowed),
        "external_eval_allowed": bool(external_eval_allowed),
        "external_training_allowed": bool(external_training_allowed),
        "commercial_sale_allowed": bool(commercial_sale_allowed),
        "requires_legal_review": bool(requires_legal_review),
        "requires_owner_release": bool(requires_owner_release),
        "provider_neutral": bool(provider_neutral),
        "raw_provider_output_present": bool(raw_provider_output_present),
        "license_evidence_path": license_evidence_path,
        "terms_snapshot_date": now_utc()[:10],
        "reason": reason,
    }


def infer_data_need_from_incident(record: dict[str, Any]) -> dict[str, Any]:
    incident = str(record.get("incident_type") or "")
    primary, value = INCIDENT_NEED_MAP.get(incident, ("FACTORY_DATASET_INTERNAL", "MEDIUM"))
    gold = as_dict(record.get("gold_output"))
    reason = str(
        record.get("quality_signal")
        or record.get("value_reason")
        or gold.get("model_should_learn")
        or f"Incident {incident or 'UNKNOWN'} harvested for internal Factory learning."
    )
    learn = [str(gold["model_should_learn"])] if gold.get("model_should_learn") else []
    return default_data_need(
        primary_need=primary,
        technical_value=value,
        value_reason=reason,
        future_model_should_learn=learn,
    )


def infer_data_rights_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Conservative, safety-first inference. Defaults to restricted-use when in
    doubt; never infers an external-training grade without explicit license
    evidence; technical value never grants export."""
    commercial = as_dict(record.get("commercial_safety"))
    raw_output = bool(commercial.get("contains_raw_provider_output"))
    quarantine = (
        bool(commercial.get("contains_secrets"))
        or raw_output
        or bool(commercial.get("contains_internal_paths"))
        or bool(record.get("sensitive_fields"))
        or str(record.get("incident_type")) == "QUARANTINE_REVIEW"
    )
    if quarantine:
        return default_data_rights(
            grade="F_QUARANTINE",
            allowed_uses=["remediation", "redaction", "legal_review"],
            forbidden_uses=["internal_training", "external_release", "external_training", "commercial_sale", "public_sample_pack"],
            requires_legal_review=True,
            requires_owner_release=True,
            raw_provider_output_present=raw_output,
            reason="Quarantine: secrets, sensitive fields, raw provider output, or unclear provenance present.",
        )
    provider_neutral = bool(commercial.get("provider_neutral"))
    release_eligible = record.get("release_eligible") is True or commercial.get("release_eligible") is True
    license_evidence = record.get("license_evidence_path")
    if provider_neutral and not raw_output and release_eligible:
        if license_evidence:
            return default_data_rights(
                grade="D_EXTERNAL_TRAINING_CANDIDATE",
                allowed_uses=["internal_research", "internal_eval", "external_eval_candidate", "external_training_candidate"],
                forbidden_uses=["commercial_sale", "public_sample_pack"],
                external_eval_allowed=True,
                external_training_allowed=True,
                provider_neutral=True,
                license_evidence_path=str(license_evidence),
                reason="Provider-neutral, product-shaped, with explicit license evidence: external-training candidate pending review.",
            )
        return default_data_rights(
            grade="C_EXTERNAL_EVAL_CANDIDATE",
            allowed_uses=["internal_research", "internal_eval", "external_eval_candidate"],
            forbidden_uses=["external_training", "commercial_sale", "public_sample_pack"],
            external_eval_allowed=True,
            provider_neutral=True,
            reason="Provider-neutral and product-shaped: external-eval candidate pending review.",
        )
    return default_data_rights(
        grade="A_INTERNAL_RESEARCH_ONLY",
        provider_neutral=provider_neutral,
        raw_provider_output_present=raw_output,
        reason="Unknown or mixed provenance/license: retained for internal research only.",
    )


def validate_data_need(need: dict[str, Any]) -> list[str]:
    if not isinstance(need, dict):
        return ["data_need:must_be_object"]
    failures: list[str] = []
    for field in ("primary_need", "secondary_needs", "technical_value", "value_reason", "future_model_should_learn", "recommended_internal_use"):
        if field not in need:
            failures.append(f"data_need.{field}:required")
    if need.get("primary_need") not in DATA_NEED_PRIMARY_VALUES:
        failures.append("data_need.primary_need:invalid")
    if need.get("technical_value") not in TECHNICAL_VALUE_VALUES:
        failures.append("data_need.technical_value:invalid")
    for field in ("secondary_needs", "future_model_should_learn", "recommended_internal_use"):
        if field in need and not isinstance(need.get(field), list):
            failures.append(f"data_need.{field}:must_be_list")
    for secondary in (need.get("secondary_needs") or []):
        if secondary not in DATA_NEED_PRIMARY_VALUES:
            failures.append(f"data_need.secondary_needs:{secondary}_invalid")
    return failures


def validate_data_rights(rights: dict[str, Any]) -> list[str]:
    if not isinstance(rights, dict):
        return ["data_rights:must_be_object"]
    failures: list[str] = []
    bool_fields = (
        "export_allowed", "external_eval_allowed", "external_training_allowed", "commercial_sale_allowed",
        "requires_legal_review", "requires_owner_release", "provider_neutral", "raw_provider_output_present",
    )
    for field in ("grade", "allowed_uses", "forbidden_uses", *bool_fields):
        if field not in rights:
            failures.append(f"data_rights.{field}:required")
    if rights.get("grade") not in DATA_RIGHTS_GRADES:
        failures.append("data_rights.grade:invalid")
    for field in ("allowed_uses", "forbidden_uses"):
        if field in rights and not isinstance(rights.get(field), list):
            failures.append(f"data_rights.{field}:must_be_list")
    for field in bool_fields:
        if field in rights and not isinstance(rights.get(field), bool):
            failures.append(f"data_rights.{field}:must_be_bool")
    overlap = set(rights.get("allowed_uses") or []) & set(rights.get("forbidden_uses") or [])
    if overlap:
        failures.append(f"data_rights.allowed_forbidden_overlap:{sorted(overlap)}")
    grade = rights.get("grade")
    external_fields = ("export_allowed", "external_eval_allowed", "external_training_allowed", "commercial_sale_allowed")
    if grade == "F_QUARANTINE":
        for field in external_fields:
            if rights.get(field):
                failures.append(f"data_rights.{field}:must_be_false_for_quarantine")
    if grade in ("A_INTERNAL_RESEARCH_ONLY", "E_RESTRICTED_DO_NOT_EXPORT"):
        for field in external_fields:
            if rights.get(field):
                failures.append(f"data_rights.{field}:must_be_false_for_internal_grade")
    if rights.get("external_eval_allowed") and grade not in ("C_EXTERNAL_EVAL_CANDIDATE", "D_EXTERNAL_TRAINING_CANDIDATE"):
        failures.append("data_rights.external_eval_allowed:requires_C_or_D_grade")
    if rights.get("external_training_allowed"):
        if grade != "D_EXTERNAL_TRAINING_CANDIDATE":
            failures.append("data_rights.external_training_allowed:requires_D_grade")
        if not rights.get("license_evidence_path"):
            failures.append("data_rights.external_training_allowed:requires_license_evidence")
    if rights.get("commercial_sale_allowed"):
        if rights.get("requires_owner_release") or rights.get("requires_legal_review"):
            failures.append("data_rights.commercial_sale_allowed:requires_owner_and_legal_clearance")
        if not rights.get("export_allowed"):
            failures.append("data_rights.commercial_sale_allowed:requires_export_allowed")
        if not rights.get("license_evidence_path"):
            failures.append("data_rights.commercial_sale_allowed:requires_license_evidence")
    return failures


def infer_model_origin_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Conservative model-origin attribution. Controlled/human-authored rows are
    not model-generated; natural agent receipts map to their provider TOS; unknown
    agents stay `unknown` (never assumed clean)."""
    commercial = as_dict(record.get("commercial_safety"))
    raw_output = bool(commercial.get("contains_raw_provider_output"))
    if record.get("source_model_output_used") is False or str(record.get("provenance_type")) == "CONTROLLED_CASE":
        return {
            "provider": "agentready_factory",
            "model_name": "human_or_factory_authored",
            "model_license_family": "not_model_generated",
            "execution_mode": "deterministic",
            "raw_output_included": False,
        }
    agent = str(record.get("agent") or record.get("source_agent") or "").lower()
    provider_map = {"claude": ("anthropic", "frontier_tos"), "codex": ("openai", "frontier_tos")}
    provider, license_family = provider_map.get(agent, ("unknown", "unknown"))
    return {
        "provider": provider,
        "model_name": agent or "unknown",
        "model_license_family": license_family,
        "execution_mode": "api" if provider != "unknown" else "unknown",
        "raw_output_included": raw_output,
    }


def quarantine_data_rights_for_signal(reason: str) -> dict[str, Any]:
    """An F_QUARANTINE rights record for a source-signal contamination. No export,
    eval, training, or sale -- remediation only. Into the dungeon, no debate."""
    return default_data_rights(
        grade="F_QUARANTINE",
        allowed_uses=["remediation", "redaction", "legal_review"],
        forbidden_uses=["internal_training", "external_release", "external_training", "commercial_sale", "public_sample_pack"],
        requires_legal_review=True,
        requires_owner_release=True,
        reason=f"Quarantine: {reason}",
    )


def data_rights_gate_row(row: dict[str, Any], intended_use: str) -> tuple[bool, str]:
    """Decide whether a single graded row is eligible for the intended use.

    grade is the eligibility CLASS; export_allowed / commercial_sale_allowed are
    the current operational CLEARANCE. A grade-C row with export_allowed=false is
    a candidate, NOT cleared, so it fails external_eval."""
    rights = row.get("data_rights") if isinstance(row.get("data_rights"), dict) else None
    need = row.get("data_need") if isinstance(row.get("data_need"), dict) else None
    if not rights:
        return (False, "missing_data_rights")
    if not need:
        return (False, "missing_data_need")
    grade = rights.get("grade")
    legal_ok = rights.get("requires_legal_review") is False or bool(rights.get("legal_clearance"))
    owner_ok = rights.get("requires_owner_release") is False or bool(rights.get("owner_release"))

    if intended_use == "internal_research":
        if grade == "F_QUARANTINE":
            return (False, "grade_F_quarantine_not_allowed")
        if rights.get("raw_provider_output_present"):
            return (False, "raw_provider_output_present")
        return (True, "")
    if intended_use == "internal_training":
        if grade not in ("B_INTERNAL_TRAINING_ALLOWED", "D_EXTERNAL_TRAINING_CANDIDATE"):
            return (False, f"grade_{grade}_not_allowed_for_internal_training")
        return (True, "")
    if intended_use == "external_eval":
        if grade not in ("C_EXTERNAL_EVAL_CANDIDATE", "D_EXTERNAL_TRAINING_CANDIDATE"):
            return (False, f"grade_{grade}_not_eligible_for_external_eval")
        if not rights.get("external_eval_allowed"):
            return (False, "external_eval_allowed_false")
        if not rights.get("export_allowed"):
            return (False, "export_allowed_false")
        if not rights.get("provider_neutral"):
            return (False, "not_provider_neutral")
        if not legal_ok:
            return (False, "legal_review_pending")
        if not owner_ok:
            return (False, "owner_release_pending")
        return (True, "")
    if intended_use == "external_training":
        if grade != "D_EXTERNAL_TRAINING_CANDIDATE":
            return (False, f"grade_{grade}_not_eligible_for_external_training")
        if not rights.get("external_training_allowed"):
            return (False, "external_training_allowed_false")
        if not rights.get("export_allowed"):
            return (False, "export_allowed_false")
        if not rights.get("license_evidence_path"):
            return (False, "missing_license_evidence")
        if not rights.get("provider_neutral"):
            return (False, "not_provider_neutral")
        if not legal_ok:
            return (False, "legal_review_pending")
        if not owner_ok:
            return (False, "owner_release_pending")
        return (True, "")
    if intended_use == "commercial_sale":
        if grade in ("F_QUARANTINE", "E_RESTRICTED_DO_NOT_EXPORT"):
            return (False, f"grade_{grade}_not_sellable")
        if not rights.get("commercial_sale_allowed"):
            return (False, "commercial_sale_allowed_false")
        if not rights.get("export_allowed"):
            return (False, "export_allowed_false")
        if not legal_ok:
            return (False, "legal_review_pending")
        if not owner_ok:
            return (False, "owner_release_pending")
        return (True, "")
    return (False, f"unknown_intended_use:{intended_use}")
