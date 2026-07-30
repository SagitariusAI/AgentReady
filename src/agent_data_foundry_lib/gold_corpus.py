# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Shared Gold-corpus path/dedup helpers and the ClaimEvidence case schema + validator."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import read_jsonl, write_json
from agent_data_foundry_lib.schemas import CLAIM_EVIDENCE_SCHEMA_VERSION


def gold_jsonl_path(root: Path) -> Path:
    return root / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"


def existing_gold_fingerprints(root: Path) -> set[str]:
    return {str(row.get("fingerprint")) for row in read_jsonl(gold_jsonl_path(root)) if row.get("fingerprint")}


def claim_evidence_case_schema() -> dict[str, Any]:
    required = [
        "schema_version",
        "source_id_hash",
        "fingerprint",
        "family",
        "dataset_family",
        "training_target",
        "dataset_readiness_level",
        "provenance_type",
        "source_mode",
        "natural_observation",
        "human_authored",
        "synthetic_content",
        "source_model_output_used",
        "release_eligible",
        "incident_type",
        "verdict",
        "severity",
        "abstracted_agent_claim",
        "input_view",
        "claim_evidence_alignment",
        "state_transition",
        "gold_output",
        "commercial_safety",
        "recommended_use",
        "evidence_profile",
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ClaimEvidence Claim-Evidence Case",
        "type": "object",
        "required": required,
        "properties": {name: {} for name in required},
    }


def write_claim_evidence_schema(root: Path) -> Path:
    schema_path = root / "data" / "training-library" / "schemas" / "claim_evidence_case.schema.json"
    write_json(schema_path, claim_evidence_case_schema())
    return schema_path


def validate_claim_evidence_case(row: dict[str, Any]) -> list[str]:
    missing = [field for field in claim_evidence_case_schema()["required"] if field not in row]
    if row.get("schema_version") != CLAIM_EVIDENCE_SCHEMA_VERSION:
        missing.append("schema_version:v0.2_required")
    return missing
