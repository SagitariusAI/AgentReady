# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    _RELEASE_DIR,
    _write_split_corpus,
)

from agent_data_foundry import (
    CLAIM_EVIDENCE_REQUIRED_LABELS,
    baseline_predict,
    build_claim_evidence_eval_split,
    claim_evidence_baseline_eval,
    main,
)


def test_build_claim_evidence_eval_split_is_deterministic_with_natural_safe_heldout(tmp_path: Path) -> None:
    _write_split_corpus(tmp_path)

    first = build_claim_evidence_eval_split(tmp_path)
    manifest_path = tmp_path / _RELEASE_DIR / "split_manifest.json"
    manifest_first = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Determinism: rebuilding with the same corpus + seed yields the same heldout.
    build_claim_evidence_eval_split(tmp_path)
    manifest_second = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_first["heldout"]["case_ids"] == manifest_second["heldout"]["case_ids"]
    assert manifest_first["seed"] == 424242

    assert first["safe_heldout_natural_majority"] is True
    assert first["all_six_labels_in_heldout"] is True

    report = json.loads((tmp_path / _RELEASE_DIR / "reports" / "split_report.json").read_text(encoding="utf-8"))
    assert report["heldout_natural_majority"] is True
    # SAFE heldout must be entirely natural here (20 natural SAFE cover the target).
    assert report["safe_heldout_total"] > 0
    assert report["safe_heldout_natural"] == report["safe_heldout_total"]

    eval_ids = {json.loads(line)["case_id"] for line in (tmp_path / _RELEASE_DIR / "data" / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines()}
    expected_ids = {json.loads(line)["case_id"] for line in (tmp_path / _RELEASE_DIR / "data" / "expected_outputs.jsonl").read_text(encoding="utf-8").splitlines()}
    assert eval_ids == expected_ids
    assert len(eval_ids) == report["total_cases"]


def test_cli_builds_claim_evidence_eval_split(tmp_path: Path, capsys) -> None:
    _write_split_corpus(tmp_path)
    exit_code = main(["--action", "build-claim_evidence-eval-split", "--root", str(tmp_path)])

    assert exit_code == 0
    assert "ClaimEvidence eval split" in capsys.readouterr().out
    assert (tmp_path / _RELEASE_DIR / "data" / "eval_cases.jsonl").exists()
    assert (tmp_path / _RELEASE_DIR / "data" / "expected_outputs.jsonl").exists()
    assert (tmp_path / _RELEASE_DIR / "split_manifest.json").exists()


def test_baseline_predict_uses_input_side_signals_not_the_answer() -> None:
    safe = baseline_predict({
        "input_view": {"claim_type": "receipt_state_promotion"},
        "evidence_profile": {"gate_evidence_present": True, "push_evidence_present": True, "blockers_present": False},
    })
    assert safe["verdict"] == "SAFE"
    assert safe["labels"] == ["SUPPORTED_CLAIM"]
    assert safe["required_action"] == "ALLOW_PROMOTION"

    promotion = baseline_predict({
        "input_view": {"claim_type": "promotion_complete"},
        "evidence_profile": {"gate_evidence_present": False, "push_evidence_present": False, "blockers_present": False},
    })
    assert promotion["verdict"] == "BLOCK"
    assert promotion["labels"] == ["UNSUPPORTED_PROMOTION"]

    deferral = baseline_predict({
        "input_view": {"claim_type": "completion_complete"},
        "evidence_profile": {"blockers_present": True},
    })
    assert deferral["labels"] == ["COMPLETION_BY_DEFERRAL"]


def test_claim_evidence_baseline_eval_emits_required_metrics_deterministically(tmp_path: Path) -> None:
    _write_split_corpus(tmp_path)
    build_claim_evidence_eval_split(tmp_path)

    first = claim_evidence_baseline_eval(tmp_path)
    metrics = first["metrics"]
    for key in (
        "verdict_accuracy",
        "macro_f1",
        "SAFE_false_positive_rate",
        "BLOCK_false_negative_rate",
        "json_validity_rate",
        "natural_subset_accuracy",
        "controlled_subset_accuracy",
        "natural_vs_controlled_delta",
        "heldout_case_count",
    ):
        assert key in metrics
    assert set(CLAIM_EVIDENCE_REQUIRED_LABELS).issubset(metrics["per_label_f1"])
    assert first["heldout_case_count"] > 0
    assert metrics["json_validity_rate"] == 1.0
    assert first["split_seed"] == 424242
    assert (tmp_path / _RELEASE_DIR / "reports" / "baseline_results.md").exists()

    # Deterministic: same heldout + same rules => identical metrics.
    second = claim_evidence_baseline_eval(tmp_path)
    assert first["metrics"] == second["metrics"]
