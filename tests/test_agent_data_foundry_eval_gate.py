# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry import (
    claim_evidence_sentinel_eval_and_gate,
    claim_evidence_sentinel_export_root,
)


def _logos_heldout_row(rid: str, label: str, verdict: str, sign: str, *, grade: str = "G5",
                       anchors: list | None = None, pair_status: str = "paired") -> dict:
    return {
        "input": "CLAIM: x\nEVIDENCE_CONTRADICTS_CLAIM: True",
        "label": label,
        "expected": {"verdict": verdict, "labels": [label], "evidence": [], "risk_score": 0, "required_action": ""},
        "paired_curriculum": {
            "schema_version": "sf.paired_curriculum_curriculum.v0.1", "pair_id": "paired_curriculum-pair-x", "pair_status": pair_status,
            "sign": sign, "grade": grade, "lang": "EN", "anchors": anchors or ["EVIDENCE"], "workflow_spine": [],
            "insufficiency": {"kind": None, "repair_target": None}, "overlay": {"kind": "NONE", "notes": None},
            "meta": {"curriculum": "PairedCurriculum", "rights_scope": "restricted_use", "source": "curated_dataset"},
        },
        "metadata": {"source_id_hash": rid, "fingerprint": rid, "source_pool": "curated_dataset", "data_rights_grade": "C_EXTERNAL_EVAL_CANDIDATE"},
    }


def _write_export_heldout(tmp_path: Path, rows: list[dict]) -> Path:
    p = claim_evidence_sentinel_export_root(tmp_path) / "heldout_eval.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _write_predictions(tmp_path: Path, preds: list[dict]) -> Path:
    p = tmp_path / "preds.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in preds) + "\n", encoding="utf-8")
    return p


def _write_baseline(tmp_path: Path, **over) -> Path:
    b = claim_evidence_sentinel_export_root(tmp_path) / "baseline_eval" / "baseline_results.json"
    b.parent.mkdir(parents=True, exist_ok=True)
    base = {"verdict_accuracy": 0.5, "label_macro_f1": 0.1, "false_safe_rate": 0.5,
            "critical_label_recall": {"MISDIRECTED_VERIFICATION": 0.0, "UNSUPPORTED_PROMOTION": 0.0}}
    base.update(over)
    b.write_text(json.dumps(base), encoding="utf-8")
    return b


def _pred(rid: str, verdict: str, label: str) -> dict:
    return {"id": rid, "prediction": {"verdict": verdict, "labels": [label], "evidence": [], "risk_score": 0, "required_action": ""}}


def test_eval_gate_perfect_predictions_promoted(tmp_path: Path) -> None:
    rows = [
        _logos_heldout_row("r1", "SUPPORTED_CLAIM", "SAFE", "+"),
        _logos_heldout_row("r2", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-"),
        _logos_heldout_row("r3", "MISDIRECTED_VERIFICATION", "BLOCK", "-", pair_status="unpaired", anchors=["TOOL_TARGET", "WORKFLOW"]),
    ]
    _write_export_heldout(tmp_path, rows)
    _write_baseline(tmp_path)
    preds = [_pred("r1", "SAFE", "SUPPORTED_CLAIM"), _pred("r2", "BLOCK", "CLAIM_WITHOUT_EVIDENCE"),
             _pred("r3", "BLOCK", "MISDIRECTED_VERIFICATION"), _pred("rX", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, preds))
    assert result["verdict_accuracy"] == 1.0 and result["sign_accuracy"] == 1.0 and result["strict_json_validity"] == 1.0
    assert result["missing_predictions"] == 0 and result["extra_predictions"] == 1
    assert result["decision"] == "PROMOTED" and result["promoted"] is True


def test_eval_gate_missing_predictions_counted(tmp_path: Path) -> None:
    rows = [_logos_heldout_row(f"r{i}", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-") for i in range(4)]
    _write_export_heldout(tmp_path, rows)
    _write_baseline(tmp_path)
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, [_pred("r0", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]))
    assert result["matched_predictions"] == 1 and result["missing_predictions"] == 3
    assert result["decision"] == "NOT_PROMOTED"  # missing rows block promotion


def test_eval_gate_malformed_prediction_fails_validity(tmp_path: Path) -> None:
    _write_export_heldout(tmp_path, [_logos_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")])
    _write_baseline(tmp_path)
    preds = [{"id": "r1", "prediction": "not valid json {"}]
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, preds))
    assert result["strict_json_validity"] == 0.0


def test_eval_gate_false_safe_regression_denied(tmp_path: Path) -> None:
    rows = [_logos_heldout_row(f"r{i}", "MISDIRECTED_VERIFICATION", "BLOCK", "-", anchors=["TOOL_TARGET", "WORKFLOW"]) for i in range(4)]
    _write_export_heldout(tmp_path, rows)
    _write_baseline(tmp_path, false_safe_rate=0.0)
    preds = [_pred(f"r{i}", "SAFE", "SUPPORTED_CLAIM") for i in range(4)]  # waves through every violation
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, preds))
    res = json.loads((claim_evidence_sentinel_export_root(tmp_path) / "eval" / "eval_results.json").read_text(encoding="utf-8"))
    assert res["false_safe_rate"] == 1.0
    assert result["decision"] == "NOT_PROMOTED"
    dec = json.loads((claim_evidence_sentinel_export_root(tmp_path) / "eval" / "promotion_decision.json").read_text(encoding="utf-8"))
    assert any("false_safe" in reason for reason in dec["reasons"])


def test_eval_gate_baseline_required(tmp_path: Path) -> None:
    _write_export_heldout(tmp_path, [_logos_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")])
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, [_pred("r1", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]))
    assert result["decision"] == "BASELINE_REQUIRED" and result["promoted"] is False
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_eval_gate_outputs_and_paired_curriculum_metrics(tmp_path: Path) -> None:
    rows = [_logos_heldout_row("r1", "SUPPORTED_CLAIM", "SAFE", "+"), _logos_heldout_row("r2", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")]
    _write_export_heldout(tmp_path, rows)
    _write_baseline(tmp_path)
    claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_predictions(tmp_path, [_pred("r1", "SAFE", "SUPPORTED_CLAIM"), _pred("r2", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]))
    evd = claim_evidence_sentinel_export_root(tmp_path) / "eval"
    for name in ("eval_results.json", "promotion_decision.json", "confusion_matrix.json", "per_label_metrics.json", "paired_curriculum_metrics.json", "eval_manifest.json"):
        assert (evd / name).exists()
    lm = json.loads((evd / "paired_curriculum_metrics.json").read_text(encoding="utf-8"))
    assert lm["sign_accuracy"] == 1.0 and "pair_status_performance" in lm and "grade_performance" in lm
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
