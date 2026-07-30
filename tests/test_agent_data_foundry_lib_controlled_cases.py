# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.controlled_cases import (
    COMPLETION_BY_DEFERRAL_SUBTYPES,
    CONTROLLED_CASE_FAMILIES,
    MISDIRECTED_VERIFICATION_SUBTYPES,
    SUPPORTED_CLAIM_SUBTYPES,
    UNSUPPORTED_PROMOTION_SUBTYPES,
    VAULT_CODE_CONFUSION_SUBTYPES,
    completion_by_deferral_controlled_row,
    controlled_case_family_slug,
    controlled_case_fingerprint,
    controlled_case_promotion_receipt_path,
    controlled_case_validation_report_path,
    controlled_cases_parent_root,
    controlled_cases_root,
    controlled_provenance_fields,
    generate_supported_claim_controlled_cases,
    generate_vault_code_confusion_controlled_cases,
    misdirected_verification_controlled_row,
    promote_controlled_cases,
    staged_controlled_case_rows,
    supported_claim_controlled_row,
    unsupported_promotion_controlled_row,
    validate_controlled_case,
    validate_controlled_cases,
    vault_code_confusion_controlled_row,
)
from agent_data_foundry_lib.io_jsonl import append_jsonl
from agent_data_foundry_lib.schemas import CLAIM_EVIDENCE_SCHEMA_VERSION


def test_family_registry_and_subtype_counts_unchanged():
    assert list(CONTROLLED_CASE_FAMILIES) == [
        "VAULT_CODE_CONFUSION", "UNSUPPORTED_PROMOTION", "MISDIRECTED_VERIFICATION",
        "COMPLETION_BY_DEFERRAL", "SUPPORTED_CLAIM",
    ]
    # label distribution depends on these counts staying fixed
    assert len(VAULT_CODE_CONFUSION_SUBTYPES) == 10
    assert len(UNSUPPORTED_PROMOTION_SUBTYPES) == 10
    assert len(MISDIRECTED_VERIFICATION_SUBTYPES) == 10
    assert len(COMPLETION_BY_DEFERRAL_SUBTYPES) == 10
    assert len(SUPPORTED_CLAIM_SUBTYPES) == 10


def test_controlled_provenance_defaults_unchanged():
    assert controlled_provenance_fields("VAULT_CODE_CONFUSION") == {
        "provenance_type": "CONTROLLED_CASE", "source_mode": "controlled_generated",
        "controlled_case_family": "VAULT_CODE_CONFUSION", "natural_observation": False,
        "human_authored": True, "human_or_factory_adjudicated": True, "synthetic_content": True,
        "source_model_output_used": False, "release_eligible": True,
        "source_doctrine_version": "AGENT_DATA_MANAGEMENT_DOCTRINE.md",
    }


def test_path_helpers_and_slug():
    root = Path("R")
    assert controlled_cases_parent_root(root) == root / "data" / "training-library" / "10_working" / "controlled-cases"
    assert controlled_case_family_slug("SUPPORTED_CLAIM") == "supported-claim"
    assert controlled_case_family_slug("UNKNOWN") == "vault-code-confusion"  # default
    assert controlled_cases_root(root, "MISDIRECTED_VERIFICATION").name == "misdirected-verification"
    assert controlled_cases_root(root).name == "vault-code-confusion"  # default family
    assert controlled_case_validation_report_path(root).name == "validation_report.json"
    assert controlled_case_promotion_receipt_path(root).name == "promotion_receipt.json"


def test_fingerprint_deterministic_and_family_scoped():
    import hashlib

    fp = controlled_case_fingerprint("vcc-001")
    assert fp == hashlib.sha256(b"controlled/vault-code-confusion/vcc-001").hexdigest()
    assert len(fp) == 64
    # family slug changes the fingerprint namespace
    assert controlled_case_fingerprint("c1", "supported-claim") != controlled_case_fingerprint("c1", "vault-code-confusion")


def test_vault_row_block_verdict_and_provenance():
    row = vault_code_confusion_controlled_row("vcc-001", "vault_page_source_missing", "desc", "source_file")
    assert row["schema_version"] == CLAIM_EVIDENCE_SCHEMA_VERSION
    assert row["incident_type"] == "VAULT_CODE_CONFUSION" and row["verdict"] == "BLOCK"
    assert row["provenance_type"] == "CONTROLLED_CASE"
    assert row["commercial_safety"]["release_eligible"] is True
    assert row["claim_evidence_alignment"]["evidence_contradicts_claim"] is True
    assert row["state_transition"]["promotion_allowed"] is False
    # deterministic id hash
    import hashlib
    assert row["source_id_hash"] == hashlib.sha256(b"controlled/vault-code-confusion/vcc-001").hexdigest()


def test_unsupported_and_misdirected_and_completion_block_rows():
    up = unsupported_promotion_controlled_row("u1", "open_blockers_called_verified", "d", "VERIFIED", "BLOCKED", "x")
    assert up["incident_type"] == "UNSUPPORTED_PROMOTION" and up["verdict"] == "BLOCK"
    assert up["input_view"]["blockers_present"] is True  # subtype-driven
    mv = misdirected_verification_controlled_row("m1", "wrong_repo_verified", "d", "A", "B", "x")
    assert mv["incident_type"] == "MISDIRECTED_VERIFICATION" and mv["claim_evidence_alignment"]["claimed_target"] == "A"
    cd = completion_by_deferral_controlled_row("c1", "required_test_deferred", "d", "required_test")
    assert cd["incident_type"] == "COMPLETION_BY_DEFERRAL" and cd["gold_output"]["required_action"] == "REJECT_PROMOTION"


def test_supported_claim_row_is_safe_positive():
    row = supported_claim_controlled_row("sc-1", "gate_green_committed_pushed", "d", "DONE", "receipts")
    assert row["incident_type"] == "SUPPORTED_CLAIM" and row["verdict"] == "SAFE"
    assert row["gold_output"]["verdict"] == "ALLOW"
    assert row["claim_evidence_alignment"]["claim_supported"] is True
    assert row["state_transition"]["promotion_allowed"] is True


def test_staged_controlled_case_rows_reads_every_family(tmp_path: Path):
    # stage one case under two families; staged_ should read both
    append_jsonl(controlled_cases_root(tmp_path, "VAULT_CODE_CONFUSION") / "cases.jsonl",
                 [vault_code_confusion_controlled_row("vcc-001", "vault_page_source_missing", "d", "source_file")])
    append_jsonl(controlled_cases_root(tmp_path, "SUPPORTED_CLAIM") / "cases.jsonl",
                 [supported_claim_controlled_row("sc-1", "gate_green_committed_pushed", "d", "DONE", "receipts")])
    rows = staged_controlled_case_rows(tmp_path)
    incident_types = {r["incident_type"] for r in rows}
    assert incident_types == {"VAULT_CODE_CONFUSION", "SUPPORTED_CLAIM"}
    assert len(rows) == 2


def test_reexported_identity_from_package_and_central():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    # Generation primitives are owned by the leaf and re-exported from the package surface.

    # orchestration is), so assert their canonical package identity.
    assert adfl.vault_code_confusion_controlled_row is vault_code_confusion_controlled_row
    assert adfl.CONTROLLED_CASE_FAMILIES is CONTROLLED_CASE_FAMILIES
    assert adfl.controlled_cases_root is controlled_cases_root
    assert adfl.SUPPORTED_CLAIM_SUBTYPES is SUPPORTED_CLAIM_SUBTYPES
    # staged_controlled_case_rows is still re-imported centrally (the release gate uses it).
    assert adf.staged_controlled_case_rows is staged_controlled_case_rows


def test_generate_validate_promote_lifecycle_from_leaf(tmp_path: Path):
    # the orchestration now lives in the leaf; exercise the full lifecycle end to end
    gen = generate_vault_code_confusion_controlled_cases(tmp_path, count=10)
    assert gen["schema_version"] == "agentready.data_foundry.controlled_cases.v1"
    assert gen["controlled_case_family"] == "VAULT_CODE_CONFUSION" and gen["generated"] == 10
    assert gen["validated"] is True and gen["promoted_to_gold"] is False
    generate_supported_claim_controlled_cases(tmp_path, count=10)

    validation = validate_controlled_cases(tmp_path)
    assert validation["schema_version"] == "agentready.data_foundry.controlled_case_gate.v1"
    assert validation["validated"] is True and validation["checked"] == 20

    promotion = promote_controlled_cases(tmp_path)
    assert promotion["promotion_enabled"] is True and promotion["promoted"] == 20
    # idempotent: a second promotion dedups against existing fingerprints
    again = promote_controlled_cases(tmp_path)
    assert again["promoted"] == 0 and again["skipped_duplicates"] == 20


def test_validate_controlled_case_tokens_from_leaf():
    valid = vault_code_confusion_controlled_row("vcc-001", "vault_page_source_missing", "d", "source_file")
    assert validate_controlled_case(valid) == []  # complete controlled row passes
    failures = validate_controlled_case({"incident_type": "NOT_A_FAMILY"})
    assert "provenance_type:CONTROLLED_CASE_required" in failures
    assert "incident_type:unrecognized_controlled_case_family" in failures


def test_orchestration_reexported_from_central():
    import agent_data_foundry as adf

    # the orchestration IS re-exported from agent_data_foundry (CLI dispatch + tests)
    assert adf.generate_vault_code_confusion_controlled_cases is generate_vault_code_confusion_controlled_cases
    assert adf.validate_controlled_cases is validate_controlled_cases
    assert adf.promote_controlled_cases is promote_controlled_cases
    assert adf.validate_controlled_case is validate_controlled_case
