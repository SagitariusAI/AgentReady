# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Build auditable paired-curriculum metadata for curated dataset rows.

The helpers assign stable signs, pair identifiers, grade bands, anchors, workflow
spines, and insufficiency metadata without fabricating counterpart examples.
"""
from __future__ import annotations

from typing import Any

from agent_data_foundry_lib.io_jsonl import as_dict

# PairedCurriculum records signed pairs, anchors, grade bands, workflow spines,
# and insufficiency-repair metadata for auditable dataset curation.
# label -> (sign, anchors)
_PAIRED_CURRICULUM_LABEL_MAP = {
    "SUPPORTED_CLAIM": ("+", ["EVIDENCE", "ROUNDTRIP"]),
    "CLAIM_WITHOUT_EVIDENCE": ("-", ["EVIDENCE", "BOOLEAN"]),
    "UNSUPPORTED_PROMOTION": ("-", ["RELEASE_GATE", "EVIDENCE"]),
    "COMPLETION_BY_DEFERRAL": ("-", ["WORKFLOW", "COMPLETION_INTEGRITY"]),
    "MISDIRECTED_VERIFICATION": ("-", ["TOOL_TARGET", "WORKFLOW"]),
    "VAULT_CODE_CONFUSION": ("-", ["SOURCE_MAPPING", "ROUNDTRIP"]),
}
# label -> signed-pair family (the + and - of one family share a stable pair_id)
_PAIRED_CURRICULUM_FAMILY = {
    "SUPPORTED_CLAIM": "evidence_claim",
    "CLAIM_WITHOUT_EVIDENCE": "evidence_claim",
    "UNSUPPORTED_PROMOTION": "release_promotion",
    "COMPLETION_BY_DEFERRAL": "completion_integrity",
    "MISDIRECTED_VERIFICATION": "verification_target",
    "VAULT_CODE_CONFUSION": "source_mapping",
}
_PAIRED_CURRICULUM_SPINE = {
    "SUPPORTED_CLAIM": ["claim", "check_evidence", "detect_gap", "block_or_repair"],
    "CLAIM_WITHOUT_EVIDENCE": ["claim", "check_evidence", "detect_gap", "block_or_repair"],
    "UNSUPPORTED_PROMOTION": ["claim", "check_evidence", "detect_gap", "block_or_repair"],
    "COMPLETION_BY_DEFERRAL": ["diff", "test_check", "integrity_check", "accept_or_block"],
    "MISDIRECTED_VERIFICATION": ["task", "tool_selection", "verification", "verdict"],
    "VAULT_CODE_CONFUSION": ["claim", "check_evidence", "detect_gap", "block_or_repair"],
}
_PAIRED_CURRICULUM_INSUFFICIENCY = {
    "CLAIM_WITHOUT_EVIDENCE": ("missing_evidence", "provide_evidence_receipts"),
    "UNSUPPORTED_PROMOTION": ("missing_promotion_evidence", "provide_green_gate_and_push"),
    "COMPLETION_BY_DEFERRAL": ("deferred_required_work", "resolve_blockers_or_required_artifact"),
    "MISDIRECTED_VERIFICATION": ("wrong_verification_target", "verify_the_claimed_target"),
    "VAULT_CODE_CONFUSION": ("doc_treated_as_implementation", "map_doc_to_source_and_verify"),
}


def _paired_curriculum_grade(row: dict[str, Any]) -> str:
    """Grade band v0.1: G4 is the base claim/evidence record; more captured signals
    lift it to G5/G6. G3 is a bare single-label record; G7 (long-horizon historical
    doctrine lineage) is reserved for historical records, not the Curated Dataset."""
    families = (row.get("signal_coverage") or {}).get("families") if isinstance(row.get("signal_coverage"), dict) else {}
    families = families if isinstance(families, dict) else {}
    non_missing = [name for name, info in families.items() if isinstance(info, dict) and info.get("status") in ("partial", "present")]
    diff = as_dict(row.get("diff_test_integrity"))
    file_ops = as_dict(diff.get("file_op_types"))
    signals = as_dict(row.get("source_signals"))
    has_real_work = any(int(file_ops.get(op) or 0) > 0 for op in ("created", "modified", "deleted", "renamed")) or bool(signals.get("commands_run"))
    if has_real_work and len(non_missing) >= 4:
        return "G6"
    if len(non_missing) >= 2:
        return "G5"
    if len(non_missing) >= 1:
        return "G4"
    return "G3"


def build_paired_curriculum_block(row: dict[str, Any], incident: str, pair_status_by_family: dict[str, str]) -> dict[str, Any]:
    """Build the restricted-use PairedCurriculum curriculum envelope for one exported row.
    pair_id is deterministic (family-based); sign/anchors/spine/insufficiency are
    mapped from the label. No positive counterexample is fabricated -- pair_status
    reflects whether the complementary sign actually exists in the export."""
    sign, anchors = _PAIRED_CURRICULUM_LABEL_MAP.get(incident, ("-", []))
    family = _PAIRED_CURRICULUM_FAMILY.get(incident, incident.lower())
    spine = list(_PAIRED_CURRICULUM_SPINE.get(incident, ["claim", "check_evidence", "detect_gap", "block_or_repair"]))
    correction = as_dict(row.get("human_correction_lineage"))
    if correction.get("correction_source") in ("owner_override", "human_review"):
        spine = ["owner_correction", "rule_update", "future_guardrail"]
    if sign == "+":
        insufficiency = {"kind": None, "repair_target": None}
    else:
        kind, repair_target = _PAIRED_CURRICULUM_INSUFFICIENCY.get(incident, (None, None))
        insufficiency = {"kind": kind, "repair_target": repair_target}
    return {
        "schema_version": "sf.paired_curriculum_curriculum.v0.1",
        "pair_id": "paired_curriculum-pair-" + family,
        "pair_status": pair_status_by_family.get(family, "unpaired"),
        "sign": sign,
        "grade": _paired_curriculum_grade(row),
        "lang": "EN",
        "anchors": list(anchors),
        "workflow_spine": spine,
        "insufficiency": insufficiency,
        "overlay": {"kind": "NONE", "notes": None},
        "meta": {"curriculum": "PairedCurriculum", "rights_scope": "restricted_use", "source": "curated_dataset"},
    }
