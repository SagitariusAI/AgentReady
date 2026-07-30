# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry import (
    build_claim_evidence_release_gate,
    generate_completion_by_deferral_controlled_cases,
    generate_misdirected_verification_controlled_cases,
    generate_supported_claim_controlled_cases,
    generate_unsupported_promotion_controlled_cases,
    generate_vault_code_confusion_controlled_cases,
    main,
    promote_controlled_cases,
    validate_controlled_cases,
)


def test_generate_vault_code_confusion_controlled_cases_stages_with_provenance_without_gold_promotion(tmp_path: Path) -> None:
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    before_count = 0

    result = generate_vault_code_confusion_controlled_cases(tmp_path)

    assert result["generated"] == 50
    assert result["validated"] is True
    assert result["promoted_to_gold"] is False
    assert result["gold_rows_before"] == before_count
    assert result["gold_rows_after"] == before_count
    assert len(result["subtype_distribution"]) == 10
    assert all(count == 5 for count in result["subtype_distribution"].values())
    staging_path = tmp_path / result["staging_path"]
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "VAULT_CODE_CONFUSION" for row in rows)
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["source_mode"] == "controlled_generated" for row in rows)
    assert all(row["natural_observation"] is False for row in rows)
    assert all(row["human_authored"] is True for row in rows)
    assert all(row["synthetic_content"] is True for row in rows)
    assert all(row["source_model_output_used"] is False for row in rows)
    assert not gold_path.exists()

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["summary"]["total_records"] == 0
    assert gate["summary"]["controlled_records"] == 0
    assert gate["summary"]["staged_controlled_records"] == 50


def test_validate_controlled_cases_writes_report_without_promoting_to_gold(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)

    result = validate_controlled_cases(tmp_path)

    assert result["validated"] is True
    assert result["checked"] == 50
    assert result["eligible_for_promotion"] == 50
    assert result["promoted"] == 0
    assert result["promotion_enabled"] is False
    assert result["validation_failures"] == []
    validation_path = tmp_path / result["validation_report_path"]
    assert validation_path.exists()
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    assert not gold_path.exists()


def test_promote_controlled_cases_requires_adjudication_and_keeps_controlled_provenance(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)

    result = promote_controlled_cases(tmp_path)

    assert result["validated"] is True
    assert result["promotion_enabled"] is True
    assert result["promoted"] == 50
    assert result["skipped_duplicates"] == 0
    receipt_path = tmp_path / result["promotion_receipt_path"]
    assert receipt_path.exists()
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["natural_observation"] is False for row in rows)
    assert all(row["controlled_case_family"] == row["incident_type"] for row in rows)
    assert all(row["human_or_factory_adjudicated"] is True for row in rows)

    duplicate_result = promote_controlled_cases(tmp_path)

    assert duplicate_result["promoted"] == 0
    assert duplicate_result["skipped_duplicates"] == 50
    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["summary"]["total_records"] == 50
    assert gate["summary"]["controlled_records"] == 50
    assert gate["summary"]["natural_records"] == 0


def test_promote_controlled_cases_blocks_unadjudicated_staged_rows(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)
    staging_path = tmp_path / "data" / "training-library" / "10_working" / "controlled-cases" / "vault-code-confusion" / "cases.jsonl"
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["human_or_factory_adjudicated"] = False
    staging_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = promote_controlled_cases(tmp_path)

    assert result["validated"] is False
    assert result["promoted"] == 0
    assert result["validation_failures"][0]["failures"] == ["human_or_factory_adjudicated:true_required"]
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    assert not gold_path.exists()


def test_generate_unsupported_promotion_controlled_cases_stages_with_provenance_without_gold_promotion(tmp_path: Path) -> None:
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"

    result = generate_unsupported_promotion_controlled_cases(tmp_path)

    assert result["generated"] == 50
    assert result["validated"] is True
    assert result["promoted_to_gold"] is False
    assert result["controlled_case_family"] == "UNSUPPORTED_PROMOTION"
    assert len(result["subtype_distribution"]) == 10
    assert all(count == 5 for count in result["subtype_distribution"].values())
    staging_path = tmp_path / result["staging_path"]
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "UNSUPPORTED_PROMOTION" for row in rows)
    assert all(row["controlled_case_family"] == "UNSUPPORTED_PROMOTION" for row in rows)
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["natural_observation"] is False for row in rows)
    assert all(row["human_authored"] is True for row in rows)
    assert all(row["synthetic_content"] is True for row in rows)
    assert all(row["source_model_output_used"] is False for row in rows)
    assert all(row["verdict"] == "BLOCK" for row in rows)
    assert all(row["training_target"] == "detect_unsupported_promotion" for row in rows)
    assert all(row["claim_evidence_alignment"]["contradiction_type"] == "UNSUPPORTED_PROMOTION" for row in rows)
    assert all(row["state_transition"]["promotion_allowed"] is False for row in rows)
    assert not gold_path.exists()

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["summary"]["total_records"] == 0
    assert gate["summary"]["controlled_records"] == 0
    assert gate["summary"]["staged_controlled_records"] == 50


def test_promote_controlled_cases_promotes_multiple_families_into_gold(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)
    generate_unsupported_promotion_controlled_cases(tmp_path)

    validation = validate_controlled_cases(tmp_path)
    assert validation["validated"] is True
    assert validation["checked"] == 100
    assert sorted(validation["controlled_case_families"]) == ["UNSUPPORTED_PROMOTION", "VAULT_CODE_CONFUSION"]

    result = promote_controlled_cases(tmp_path)
    assert result["validated"] is True
    assert result["promoted"] == 100
    assert result["skipped_duplicates"] == 0

    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 100
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["controlled_case_family"] == row["incident_type"] for row in rows)

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["label_distribution"]["UNSUPPORTED_PROMOTION"] == 50
    assert gate["label_distribution"]["VAULT_CODE_CONFUSION"] == 50
    assert gate["summary"]["controlled_records"] == 100
    assert gate["summary"]["natural_records"] == 0

    duplicate = promote_controlled_cases(tmp_path)
    assert duplicate["promoted"] == 0
    assert duplicate["skipped_duplicates"] == 100


def test_cli_generates_unsupported_promotion_controlled_cases(tmp_path: Path, capsys) -> None:
    exit_code = main(["--action", "generate-unsupported-promotion-controlled-cases", "--root", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "unsupported-promotion controlled-case generation" in captured
    staging_path = tmp_path / "data" / "training-library" / "10_working" / "controlled-cases" / "unsupported-promotion" / "cases.jsonl"
    assert staging_path.exists()
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "UNSUPPORTED_PROMOTION" for row in rows)


def test_generate_misdirected_verification_controlled_cases_stages_with_provenance_without_gold_promotion(tmp_path: Path) -> None:
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"

    result = generate_misdirected_verification_controlled_cases(tmp_path)

    assert result["generated"] == 50
    assert result["validated"] is True
    assert result["promoted_to_gold"] is False
    assert result["controlled_case_family"] == "MISDIRECTED_VERIFICATION"
    assert len(result["subtype_distribution"]) == 10
    assert all(count == 5 for count in result["subtype_distribution"].values())
    staging_path = tmp_path / result["staging_path"]
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "MISDIRECTED_VERIFICATION" for row in rows)
    assert all(row["controlled_case_family"] == "MISDIRECTED_VERIFICATION" for row in rows)
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["natural_observation"] is False for row in rows)
    assert all(row["verdict"] == "BLOCK" for row in rows)
    assert all(row["training_target"] == "detect_misdirected_verification" for row in rows)
    assert all(row["claim_evidence_alignment"]["contradiction_type"] == "MISDIRECTED_VERIFICATION" for row in rows)
    assert all(row["claim_evidence_alignment"]["claimed_target"] != row["claim_evidence_alignment"]["actual_target"] for row in rows)
    assert all(row["state_transition"]["promotion_allowed"] is False for row in rows)
    assert not gold_path.exists()

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["summary"]["staged_controlled_records"] == 50


def test_promote_controlled_cases_promotes_all_three_families_into_gold(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)
    generate_unsupported_promotion_controlled_cases(tmp_path)
    generate_misdirected_verification_controlled_cases(tmp_path)

    validation = validate_controlled_cases(tmp_path)
    assert validation["validated"] is True
    assert validation["checked"] == 150
    assert sorted(validation["controlled_case_families"]) == [
        "MISDIRECTED_VERIFICATION",
        "UNSUPPORTED_PROMOTION",
        "VAULT_CODE_CONFUSION",
    ]

    result = promote_controlled_cases(tmp_path)
    assert result["validated"] is True
    assert result["promoted"] == 150
    assert result["skipped_duplicates"] == 0

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["label_distribution"]["MISDIRECTED_VERIFICATION"] == 50
    assert gate["label_distribution"]["UNSUPPORTED_PROMOTION"] == 50
    assert gate["label_distribution"]["VAULT_CODE_CONFUSION"] == 50
    assert gate["summary"]["controlled_records"] == 150

    duplicate = promote_controlled_cases(tmp_path)
    assert duplicate["promoted"] == 0
    assert duplicate["skipped_duplicates"] == 150


def test_cli_generates_misdirected_verification_controlled_cases(tmp_path: Path, capsys) -> None:
    exit_code = main(["--action", "generate-misdirected-verification-controlled-cases", "--root", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "misdirected-verification controlled-case generation" in captured
    staging_path = tmp_path / "data" / "training-library" / "10_working" / "controlled-cases" / "misdirected-verification" / "cases.jsonl"
    assert staging_path.exists()
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "MISDIRECTED_VERIFICATION" for row in rows)


def test_generate_completion_by_deferral_controlled_cases_blocks_deferred_required_work(tmp_path: Path) -> None:
    result = generate_completion_by_deferral_controlled_cases(tmp_path)

    assert result["generated"] == 50
    assert result["validated"] is True
    assert result["controlled_case_family"] == "COMPLETION_BY_DEFERRAL"
    assert len(result["subtype_distribution"]) == 10
    staging_path = tmp_path / result["staging_path"]
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 50
    assert all(row["incident_type"] == "COMPLETION_BY_DEFERRAL" for row in rows)
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["verdict"] == "BLOCK" for row in rows)
    assert all(row["gold_output"]["required_action"] == "REJECT_PROMOTION" for row in rows)
    assert all(row["claim_evidence_alignment"]["evidence_contradicts_claim"] is True for row in rows)
    assert all(row["state_transition"]["promotion_allowed"] is False for row in rows)


def test_generate_supported_claim_controlled_cases_are_safe_positive_examples(tmp_path: Path) -> None:
    result = generate_supported_claim_controlled_cases(tmp_path)

    assert result["generated"] == 20
    assert result["validated"] is True
    assert result["controlled_case_family"] == "SUPPORTED_CLAIM"
    staging_path = tmp_path / result["staging_path"]
    rows = [json.loads(line) for line in staging_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20
    assert all(row["incident_type"] == "SUPPORTED_CLAIM" for row in rows)
    assert all(row["provenance_type"] == "CONTROLLED_CASE" for row in rows)
    assert all(row["verdict"] == "SAFE" for row in rows)
    assert all(row["gold_output"]["verdict"] == "ALLOW" for row in rows)
    assert all(row["claim_evidence_alignment"]["claim_supported"] is True for row in rows)
    assert all(row["claim_evidence_alignment"]["evidence_contradicts_claim"] is False for row in rows)
    assert all(row["state_transition"]["promotion_allowed"] is True for row in rows)


def test_promote_controlled_cases_closes_label_gates_across_five_families(tmp_path: Path) -> None:
    generate_vault_code_confusion_controlled_cases(tmp_path)
    generate_unsupported_promotion_controlled_cases(tmp_path)
    generate_misdirected_verification_controlled_cases(tmp_path)
    generate_completion_by_deferral_controlled_cases(tmp_path)
    generate_supported_claim_controlled_cases(tmp_path)

    validation = validate_controlled_cases(tmp_path)
    assert validation["validated"] is True
    assert validation["checked"] == 220
    assert sorted(validation["controlled_case_families"]) == [
        "COMPLETION_BY_DEFERRAL",
        "MISDIRECTED_VERIFICATION",
        "SUPPORTED_CLAIM",
        "UNSUPPORTED_PROMOTION",
        "VAULT_CODE_CONFUSION",
    ]

    result = promote_controlled_cases(tmp_path)
    assert result["promoted"] == 220
    assert result["skipped_duplicates"] == 0

    gate = build_claim_evidence_release_gate(tmp_path)
    assert gate["label_distribution"]["COMPLETION_BY_DEFERRAL"] == 50
    assert gate["label_distribution"]["SUPPORTED_CLAIM"] == 20
    assert gate["summary"]["controlled_records"] == 220
    # SAFE controlled rows keep the corpus from being negative-only.
    assert gate["gate"]["negative_only_corpus_blocked"]["passed"] is True


def test_cli_generates_completion_by_deferral_controlled_cases(tmp_path: Path, capsys) -> None:
    exit_code = main(["--action", "generate-completion-by-deferral-controlled-cases", "--root", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "completion-by-deferral controlled-case generation" in captured
    staging_path = tmp_path / "data" / "training-library" / "10_working" / "controlled-cases" / "completion-by-deferral" / "cases.jsonl"
    assert staging_path.exists()
