"""Shared Gold-corpus path/dedup helpers and the Cerberus case schema + validator.

Phase L1 of the module split: the Gold-corpus identity layer and the canonical Cerberus
claim-evidence case schema/validator live here as a clean leaf. These are the shared
primitives that the controlled-case validate/promote orchestration, the mining gold-append
path, and the release gate all depend on:

- ``gold_jsonl_path`` — the single canonical Gold corpus path (product_incidents.jsonl).
- ``existing_gold_fingerprints`` — the corpus dedup set (read-only).
- ``cerberus_case_schema`` / ``write_cerberus_schema`` — the canonical Cerberus claim-evidence
  case JSON schema and its on-disk emitter.
- ``validate_cerberus_case`` — required-field + schema-version validation, returning the list
  of failure tokens that controlled-case validation and the release gate assert against.

Imports only sibling leaves (io_jsonl for read/write, schemas for the shared schema-version
constant) plus stdlib — no back-import to ``agent_data_foundry``. Extracting this layer is the
prerequisite that lets a future slice move the controlled-case generate/validate/promote
orchestration (and later mining/harvest) out of the central module: those depend on these
helpers, not the other way round. The Gold corpus path, fingerprint/dedup behavior, schema
fields, schema-version gate, and validation failure tokens are preserved byte-for-byte.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import read_jsonl, write_json
from agent_data_foundry_lib.schemas import CERBERUS_SCHEMA_VERSION


def gold_jsonl_path(root: Path) -> Path:
    return root / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"


def existing_gold_fingerprints(root: Path) -> set[str]:
    return {str(row.get("fingerprint")) for row in read_jsonl(gold_jsonl_path(root)) if row.get("fingerprint")}


def cerberus_case_schema() -> dict[str, Any]:
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
        "title": "Cerberus Claim-Evidence Case",
        "type": "object",
        "required": required,
        "properties": {name: {} for name in required},
    }


def write_cerberus_schema(root: Path) -> Path:
    schema_path = root / "data" / "training-library" / "schemas" / "claim_evidence_case.schema.json"
    write_json(schema_path, cerberus_case_schema())
    return schema_path


def validate_cerberus_case(row: dict[str, Any]) -> list[str]:
    missing = [field for field in cerberus_case_schema()["required"] if field not in row]
    if row.get("schema_version") != CERBERUS_SCHEMA_VERSION:
        missing.append("schema_version:v0.2_required")
    return missing
