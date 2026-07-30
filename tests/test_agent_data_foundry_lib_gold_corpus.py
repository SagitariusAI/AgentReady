# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_lib.controlled_cases import vault_code_confusion_controlled_row
from agent_data_foundry_lib.gold_corpus import (
    claim_evidence_case_schema,
    existing_gold_fingerprints,
    gold_jsonl_path,
    validate_claim_evidence_case,
    write_claim_evidence_schema,
)
from agent_data_foundry_lib.io_jsonl import append_jsonl
from agent_data_foundry_lib.schemas import CLAIM_EVIDENCE_SCHEMA_VERSION


def test_gold_jsonl_path_is_canonical():
    root = Path("R")
    assert gold_jsonl_path(root) == (
        root / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    )


def test_existing_gold_fingerprints_reads_dedup_set(tmp_path: Path):
    assert existing_gold_fingerprints(tmp_path) == set()  # no corpus yet
    append_jsonl(gold_jsonl_path(tmp_path), [{"fingerprint": "a1"}, {"fingerprint": "b2"}, {"no_fp": 1}])
    assert existing_gold_fingerprints(tmp_path) == {"a1", "b2"}


def test_claim_evidence_case_schema_required_fields_stable():
    schema = claim_evidence_case_schema()
    assert schema["title"] == "ClaimEvidence Claim-Evidence Case"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert len(schema["required"]) == 25
    for key in ("schema_version", "fingerprint", "incident_type", "verdict", "commercial_safety", "evidence_profile"):
        assert key in schema["required"], key
    # properties mirror required
    assert set(schema["properties"]) == set(schema["required"])


def test_write_claim_evidence_schema_emits_canonical_path_and_content(tmp_path: Path):
    out = write_claim_evidence_schema(tmp_path)
    assert out == tmp_path / "data" / "training-library" / "schemas" / "claim_evidence_case.schema.json"
    assert json.loads(out.read_text(encoding="utf-8")) == claim_evidence_case_schema()


def test_validate_passes_complete_row_and_flags_missing():
    valid = vault_code_confusion_controlled_row("vcc-001", "vault_page_source_missing", "d", "source_file")
    assert validate_claim_evidence_case(valid) == []  # complete, correct schema_version
    # missing all fields
    failures = validate_claim_evidence_case({})
    assert "schema_version" in failures and "fingerprint" in failures
    assert "schema_version:v0.2_required" in failures  # version gate token


def test_validate_schema_version_gate_token():
    valid = vault_code_confusion_controlled_row("vcc-002", "vault_page_source_missing", "d", "source_file")
    bumped = dict(valid)
    bumped["schema_version"] = "wrong.version"
    failures = validate_claim_evidence_case(bumped)
    assert failures == ["schema_version:v0.2_required"]  # only the version token, all fields present
    assert valid["schema_version"] == CLAIM_EVIDENCE_SCHEMA_VERSION


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    assert adf.validate_claim_evidence_case is validate_claim_evidence_case
    assert adf.gold_jsonl_path is gold_jsonl_path
    assert adf.existing_gold_fingerprints is existing_gold_fingerprints
    assert adf.write_claim_evidence_schema is write_claim_evidence_schema
    assert adf.claim_evidence_case_schema is claim_evidence_case_schema
