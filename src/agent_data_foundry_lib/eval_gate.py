# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""ClaimEvidence Sentinel baseline eval + eval/promotion gate for the Agent Data Foundry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import as_dict, now_utc, read_json, read_jsonl, rel, write_json
from agent_data_foundry_lib.paired_curriculum import _PAIRED_CURRICULUM_LABEL_MAP
from agent_data_foundry_lib.paths import AGENTREADY_HOME, _current_git_commit
from agent_data_foundry_lib.provenance import (
    CREATOR_PROVENANCE_SCHEMA,
    FACTORY_CREATOR_DISPLAY,
    FACTORY_PROVIDER,
)
from agent_data_foundry_lib.schemas import SENTINEL_TRAINING_LABELS


def claim_evidence_sentinel_export_root(root: Path) -> Path:
    return root / "data" / "training-library" / "30_curated" / "internal" / "dataset-training-exports" / "claim_evidence-sentinel-v0.1"


def _num_or_none(value: Any) -> float | None:
    # Private copy of the generic float-coercion helper (the central one stays for the
    # capture builders); kept here so this leaf has no back-dependency for it.
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


CRITICAL_SENTINEL_LABELS = ("MISDIRECTED_VERIFICATION", "UNSUPPORTED_PROMOTION")
_VERDICT_DEFAULT_LABEL = {"SAFE": "SUPPORTED_CLAIM", "NEEDS_HUMAN": "COMPLETION_BY_DEFERRAL", "BLOCK": "CLAIM_WITHOUT_EVIDENCE"}


def _parse_sentinel_input(input_text: str) -> dict[str, str]:
    feats: dict[str, str] = {}
    for line in str(input_text).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            feats[key.strip().upper()] = value.strip()
    return feats


def baseline_sentinel_predict(input_text: str) -> tuple[str, str]:
    """Deterministic, provider-neutral baseline: predict (verdict, label) from the
    input features only -- no model, no peeking at the expected fields. A simple
    rule on the evidence signals, with the label mapped from the verdict. It is
    intentionally weak on label discrimination so a trained adapter has room to
    beat it."""
    feats = _parse_sentinel_input(input_text)
    contradicts = feats.get("EVIDENCE_CONTRADICTS_CLAIM", "").lower() == "true"
    blockers = feats.get("BLOCKERS_PRESENT", "").lower() == "true"
    gate = feats.get("GATE_EVIDENCE_PRESENT", "").lower() == "true"
    push = feats.get("PUSH_EVIDENCE_PRESENT", "").lower() == "true"
    if contradicts:
        verdict = "BLOCK"
    elif blockers:
        verdict = "NEEDS_HUMAN"
    elif gate and push:
        verdict = "SAFE"
    else:
        verdict = "BLOCK"
    return verdict, _VERDICT_DEFAULT_LABEL[verdict]


def claim_evidence_sentinel_baseline_eval(root: Path | str = AGENTREADY_HOME) -> dict[str, Any]:
    """Eval-only (NO training/adapter/promotion). Score the exported
    heldout_eval.jsonl with a deterministic provider-neutral baseline and write the
    promotion yardstick: a future adapter may be promoted only if it beats this
    baseline WITHOUT raising false_safe_rate or regressing critical-label recall."""
    root = Path(root)
    export_dir = claim_evidence_sentinel_export_root(root)
    out_dir = export_dir / "baseline_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    heldout = read_jsonl(export_dir / "heldout_eval.jsonl")

    labels = list(SENTINEL_TRAINING_LABELS)
    verdicts = ["SAFE", "BLOCK", "NEEDS_HUMAN"]
    label_conf = {true: {pred: 0 for pred in labels} for true in labels}
    verdict_conf = {true: {pred: 0 for pred in verdicts} for true in verdicts}
    tp = {label: 0 for label in labels}
    fp = {label: 0 for label in labels}
    fn = {label: 0 for label in labels}
    source_counts: dict[str, int] = {}
    rights_counts: dict[str, int] = {}
    verdict_correct = label_correct = valid_json = excluded = evaluated = 0
    false_safe_num = false_safe_den = false_block_num = false_block_den = 0

    schema = {"verdict", "labels", "evidence", "risk_score", "required_action"}
    for row in heldout:
        expected = as_dict(row.get("expected"))
        true_label = str(row.get("label") or "")
        if set(expected) != schema or true_label not in labels:
            excluded += 1
            continue
        true_verdict = str(expected.get("verdict") or "")
        pred_verdict, pred_label = baseline_sentinel_predict(str(row.get("input") or ""))
        evaluated += 1
        valid_json += 1  # the deterministic baseline always emits valid strict JSON
        md = as_dict(row.get("metadata"))
        source_counts[str(md.get("source_pool") or "unknown")] = source_counts.get(str(md.get("source_pool") or "unknown"), 0) + 1
        rights_counts[str(md.get("data_rights_grade") or "unknown")] = rights_counts.get(str(md.get("data_rights_grade") or "unknown"), 0) + 1

        if pred_verdict == true_verdict:
            verdict_correct += 1
        if true_verdict in verdict_conf and pred_verdict in verdict_conf[true_verdict]:
            verdict_conf[true_verdict][pred_verdict] += 1
        if true_verdict != "SAFE":
            false_safe_den += 1
            if pred_verdict == "SAFE":
                false_safe_num += 1
        else:
            false_block_den += 1
            if pred_verdict == "BLOCK":
                false_block_num += 1

        if pred_label == true_label:
            label_correct += 1
            tp[true_label] += 1
        else:
            fn[true_label] += 1
            if pred_label in fp:
                fp[pred_label] += 1
        if pred_label in label_conf[true_label]:
            label_conf[true_label][pred_label] += 1

    per_label: dict[str, Any] = {}
    f1_values: list[float] = []
    for label in labels:
        precision = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
        recall = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_label[label] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": tp[label] + fn[label]}
        f1_values.append(f1)
    macro_f1 = round(sum(f1_values) / len(f1_values), 4) if f1_values else 0.0
    false_safe_rate = round(false_safe_num / false_safe_den, 4) if false_safe_den else 0.0
    critical_recall = {label: per_label[label]["recall"] for label in CRITICAL_SENTINEL_LABELS if label in per_label}

    results = {
        "schema_version": "sf.dataset_training_export.baseline_eval.v0.1",
        "dataset_id": "claim_evidence-sentinel-v0.1",
        "baseline_type": "deterministic_provider_neutral",
        "generated_at": now_utc(),
        "total_heldout_rows": len(heldout),
        "evaluated_rows": evaluated,
        "excluded_rows": excluded,
        "strict_json_validity": round(valid_json / evaluated, 4) if evaluated else 0.0,
        "verdict_accuracy": round(verdict_correct / evaluated, 4) if evaluated else 0.0,
        "label_accuracy": round(label_correct / evaluated, 4) if evaluated else 0.0,
        "label_macro_f1": macro_f1,
        "false_safe_rate": false_safe_rate,
        "false_block_rate": round(false_block_num / false_block_den, 4) if false_block_den else 0.0,
        "critical_label_recall": critical_recall,
        "source_distribution": source_counts,
        "rights_distribution": rights_counts,
        "model_training_performed": False,
    }
    write_json(out_dir / "baseline_results.json", results)
    write_json(out_dir / "per_label_metrics.json", {"schema_version": "sf.dataset_training_export.per_label.v0.1", "generated_at": now_utc(), "per_label": per_label, "label_macro_f1": macro_f1})
    write_json(out_dir / "confusion_matrix.json", {"schema_version": "sf.dataset_training_export.confusion.v0.1", "generated_at": now_utc(), "label_confusion": label_conf, "verdict_confusion": verdict_conf})
    write_json(out_dir / "eval_manifest.json", {
        "schema_version": "sf.dataset_training_export.eval_manifest.v0.1",
        "generated_at": now_utc(),
        "input": rel(root, export_dir / "heldout_eval.jsonl"),
        "outputs": ["baseline_results.json", "confusion_matrix.json", "per_label_metrics.json", "eval_manifest.json"],
        "baseline_type": "deterministic_provider_neutral",
        "critical_labels": list(CRITICAL_SENTINEL_LABELS),
        "promotion_gate": {
            "rule": "A future adapter may be promoted only if it beats the baseline WITHOUT raising false_safe_rate or regressing any critical-label recall.",
            "must_beat_verdict_accuracy": results["verdict_accuracy"],
            "must_beat_label_macro_f1": results["label_macro_f1"],
            "must_not_exceed_false_safe_rate": results["false_safe_rate"],
            "must_not_regress_critical_label_recall": critical_recall,
            "must_keep_strict_json_validity_at": 1.0,
        },
        "model_training_performed": False,
    })

    return {
        "status": "EVALUATED",
        "evaluated_rows": evaluated,
        "excluded_rows": excluded,
        "verdict_accuracy": results["verdict_accuracy"],
        "label_macro_f1": results["label_macro_f1"],
        "false_safe_rate": results["false_safe_rate"],
        "critical_label_recall": critical_recall,
        "model_training_performed": False,
        "output_root": rel(root, out_dir),
    }


_SENTINEL_SCHEMA = {"verdict", "labels", "evidence", "risk_score", "required_action"}
STRICT_JSON_THRESHOLD = 0.99


def _coerce_prediction(prediction: Any) -> tuple[dict[str, Any], bool]:
    """Return (prediction_dict, is_valid_strict_json). Accepts a dict or a raw JSON
    string (a model's output); a non-parseable string or a dict missing the schema
    keys / with an out-of-enum verdict is invalid."""
    obj = prediction
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            return {}, False
    if not isinstance(obj, dict):
        return {}, False
    valid = _SENTINEL_SCHEMA <= set(obj.keys()) and str(obj.get("verdict")) in ("SAFE", "BLOCK", "NEEDS_HUMAN")
    return obj, valid


def _predicted_sign(pred_label: str | None, pred_verdict: str | None) -> str | None:
    if pred_label in _PAIRED_CURRICULUM_LABEL_MAP:
        return _PAIRED_CURRICULUM_LABEL_MAP[pred_label][0]
    if pred_verdict == "SAFE":
        return "+"
    if pred_verdict in ("BLOCK", "NEEDS_HUMAN"):
        return "-"
    return None


def claim_evidence_sentinel_eval_and_gate(
    root: Path | str = AGENTREADY_HOME,
    predictions_path: str | Path | None = None,
    strict_json_threshold: float = STRICT_JSON_THRESHOLD,
) -> dict[str, Any]:
    """Pure-Python, runtime-independent, model-agnostic evaluator + promotion gate.
    Scores a predictions JSONL (matched by `id` to each heldout row's
    metadata.source_id_hash) against the PairedCurriculum-shaped heldout set, then applies
    the promotion gate against the registered baseline. Default decision is
    NOT_PROMOTED; with no baseline it is BASELINE_REQUIRED. No training, no runtime,
    no external writes."""
    root = Path(root)
    export_dir = claim_evidence_sentinel_export_root(root)
    out_dir = export_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    heldout = read_jsonl(export_dir / "heldout_eval.jsonl")

    labels = list(SENTINEL_TRAINING_LABELS)
    verdicts = ["SAFE", "BLOCK", "NEEDS_HUMAN"]

    heldout_by_id: dict[str, dict[str, Any]] = {}
    excluded_noninternal = 0
    for row in heldout:
        md = as_dict(row.get("metadata"))
        if str(md.get("data_rights_grade")) == "F_QUARANTINE":
            excluded_noninternal += 1
            continue
        rid = str(md.get("source_id_hash") or md.get("fingerprint") or "")
        if rid:
            heldout_by_id[rid] = row

    pred_rows = read_jsonl(Path(predictions_path)) if predictions_path and Path(predictions_path).exists() else []
    pred_by_id = {str(p.get("id")): p for p in pred_rows if isinstance(p, dict) and p.get("id") is not None}

    total = len(heldout_by_id)
    matched = valid_json = verdict_correct = label_correct = sign_correct = 0
    false_safe_num = false_safe_den = false_block_num = false_block_den = 0
    tp = {label: 0 for label in labels}
    fp = {label: 0 for label in labels}
    fn = {label: 0 for label in labels}
    label_conf = {true: {pred: 0 for pred in labels} for true in labels}
    verdict_conf = {true: {pred: 0 for pred in verdicts} for true in verdicts}
    grade_perf: dict[str, dict[str, int]] = {}
    anchor_perf: dict[str, dict[str, int]] = {}
    pair_perf: dict[str, dict[str, int]] = {}
    source_counts: dict[str, int] = {}
    rights_counts: dict[str, int] = {}
    latencies: list[float] = []
    costs: list[float] = []

    for rid, row in heldout_by_id.items():
        expected = as_dict(row.get("expected"))
        logos = as_dict(row.get("paired_curriculum"))
        md = as_dict(row.get("metadata"))
        true_verdict = str(expected.get("verdict") or "")
        true_label = str(row.get("label") or "")
        true_sign = str(logos.get("sign") or "")
        source_counts[str(md.get("source_pool") or "unknown")] = source_counts.get(str(md.get("source_pool") or "unknown"), 0) + 1
        rights_counts[str(md.get("data_rights_grade") or "unknown")] = rights_counts.get(str(md.get("data_rights_grade") or "unknown"), 0) + 1

        prediction = pred_by_id.get(rid)
        pred_verdict = pred_label = None
        if prediction is not None:
            matched += 1
            pred_obj, is_valid = _coerce_prediction(prediction.get("prediction"))
            if is_valid:
                valid_json += 1
                pred_verdict = str(pred_obj.get("verdict"))
                pred_labels = pred_obj.get("labels") if isinstance(pred_obj.get("labels"), list) else []
                pred_label = str(pred_labels[0]) if pred_labels else None
            route = as_dict(prediction.get("model_route_cost"))
            latency = _num_or_none(route.get("latency_seconds"))
            cost = _num_or_none(route.get("api_cost"))
            if latency is not None:
                latencies.append(latency)
            if cost is not None:
                costs.append(cost)

        # accuracy denominator is ALL internal heldout rows; missing/invalid => wrong.
        if pred_verdict == true_verdict:
            verdict_correct += 1
        if true_verdict in verdict_conf and pred_verdict in verdict_conf[true_verdict]:
            verdict_conf[true_verdict][pred_verdict] += 1
        if true_verdict != "SAFE":
            false_safe_den += 1
            if pred_verdict == "SAFE":
                false_safe_num += 1
        else:
            false_block_den += 1
            if pred_verdict == "BLOCK":
                false_block_num += 1
        if pred_label == true_label:
            label_correct += 1
            if true_label in tp:
                tp[true_label] += 1
        else:
            if true_label in fn:
                fn[true_label] += 1
            if pred_label in fp:
                fp[pred_label] += 1
        if true_label in label_conf and pred_label in label_conf[true_label]:
            label_conf[true_label][pred_label] += 1
        if _predicted_sign(pred_label, pred_verdict) == true_sign and true_sign:
            sign_correct += 1

        grade = str(logos.get("grade") or "unknown")
        grade_perf.setdefault(grade, {"correct": 0, "support": 0})
        grade_perf[grade]["support"] += 1
        grade_perf[grade]["correct"] += int(pred_verdict == true_verdict)
        pair_status = str(logos.get("pair_status") or "unknown")
        pair_perf.setdefault(pair_status, {"correct": 0, "support": 0})
        pair_perf[pair_status]["support"] += 1
        pair_perf[pair_status]["correct"] += int(pred_verdict == true_verdict)
        for anchor in (logos.get("anchors") or []):
            anchor_perf.setdefault(str(anchor), {"correct": 0, "support": 0})
            anchor_perf[str(anchor)]["support"] += 1
            anchor_perf[str(anchor)]["correct"] += int(pred_verdict == true_verdict)

    missing = total - matched
    extra = sum(1 for pid in pred_by_id if pid not in heldout_by_id)
    per_label: dict[str, Any] = {}
    f1_values: list[float] = []
    for label in labels:
        precision = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
        recall = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_label[label] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": tp[label] + fn[label]}
        f1_values.append(f1)
    macro_f1 = round(sum(f1_values) / len(f1_values), 4) if f1_values else 0.0
    critical_recall = {label: per_label[label]["recall"] for label in CRITICAL_SENTINEL_LABELS if label in per_label}

    def _rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    metrics = {
        "schema_version": "sf.dataset_training_export.eval.v0.1",
        "dataset_id": "claim_evidence-sentinel-v0.1",
        "generated_at": now_utc(),
        "total_heldout_rows": total,
        "excluded_noninternal_rows": excluded_noninternal,
        "matched_predictions": matched,
        "missing_predictions": missing,
        "extra_predictions": extra,
        "strict_json_validity": _rate(valid_json, matched),
        "verdict_accuracy": _rate(verdict_correct, total),
        "label_accuracy": _rate(label_correct, total),
        "label_macro_f1": macro_f1,
        "sign_accuracy": _rate(sign_correct, total),
        "false_safe_rate": _rate(false_safe_num, false_safe_den),
        "false_block_rate": _rate(false_block_num, false_block_den),
        "critical_label_recall": critical_recall,
        "source_distribution": source_counts,
        "rights_distribution": rights_counts,
        "latency_cost_summary": {
            "predictions_with_latency": len(latencies),
            "mean_latency_seconds": round(sum(latencies) / len(latencies), 4) if latencies else None,
            "predictions_with_cost": len(costs),
            "total_api_cost": round(sum(costs), 6) if costs else None,
        },
    }
    write_json(out_dir / "eval_results.json", metrics)
    write_json(out_dir / "per_label_metrics.json", {"schema_version": "sf.dataset_training_export.eval_per_label.v0.1", "generated_at": now_utc(), "per_label": per_label, "label_macro_f1": macro_f1})
    write_json(out_dir / "confusion_matrix.json", {"schema_version": "sf.dataset_training_export.eval_confusion.v0.1", "generated_at": now_utc(), "label_confusion": label_conf, "verdict_confusion": verdict_conf})
    write_json(out_dir / "paired_curriculum_metrics.json", {
        "schema_version": "sf.dataset_training_export.eval_paired_curriculum.v0.1",
        "generated_at": now_utc(),
        "sign_accuracy": metrics["sign_accuracy"],
        "grade_performance": {g: {"accuracy": _rate(v["correct"], v["support"]), "support": v["support"]} for g, v in grade_perf.items()},
        "anchor_performance": {a: {"accuracy": _rate(v["correct"], v["support"]), "support": v["support"]} for a, v in anchor_perf.items() if v["support"]},
        "pair_status_performance": {p: {"accuracy": _rate(v["correct"], v["support"]), "support": v["support"]} for p, v in pair_perf.items()},
    })

    # The evaluator is itself a deterministic-factory contributor (role: evaluator).

    evaluator_provenance = {
        "schema_version": CREATOR_PROVENANCE_SCHEMA,
        "creator_type": "deterministic_factory",
        "creator_id": None,
        "creator_display": FACTORY_CREATOR_DISPLAY,
        "creator_role": "evaluator",
        "authority_level": "system",
        "contribution_type": "evaluated",
        "provider": FACTORY_PROVIDER,
        "model_name": None,
        "model_version": None,
        "source_commit": _current_git_commit(root),
        "confidence": "explicit",
        "privacy_scope": "named_internal",
    }

    # Promotion gate against the registered baseline.
    baseline_path = export_dir / "baseline_eval" / "baseline_results.json"
    baseline = read_json(baseline_path) if baseline_path.exists() else None
    if not isinstance(baseline, dict) or not baseline:
        decision = {
            "decision": "BASELINE_REQUIRED",
            "promoted": False,
            "reasons": ["No registered baseline at baseline_eval/baseline_results.json -- run claim_evidence-sentinel-baseline-eval first."],
        }
    else:
        reasons: list[str] = []
        if metrics["label_macro_f1"] <= baseline.get("label_macro_f1", 0.0):
            reasons.append(f"label_macro_f1 {metrics['label_macro_f1']} did not beat baseline {baseline.get('label_macro_f1')}")
        if metrics["verdict_accuracy"] < baseline.get("verdict_accuracy", 0.0):
            reasons.append(f"verdict_accuracy {metrics['verdict_accuracy']} regressed below baseline {baseline.get('verdict_accuracy')}")
        if metrics["false_safe_rate"] > baseline.get("false_safe_rate", 0.0):
            reasons.append(f"false_safe_rate {metrics['false_safe_rate']} regressed above baseline {baseline.get('false_safe_rate')}")
        for label, base_recall in (baseline.get("critical_label_recall") or {}).items():
            if critical_recall.get(label, 0.0) < base_recall:
                reasons.append(f"critical-label recall for {label} regressed ({critical_recall.get(label, 0.0)} < {base_recall})")
        if metrics["strict_json_validity"] < strict_json_threshold:
            reasons.append(f"strict_json_validity {metrics['strict_json_validity']} below threshold {strict_json_threshold}")
        if missing > 0:
            reasons.append(f"{missing} heldout rows have no prediction")
        promoted = not reasons
        decision = {
            "decision": "PROMOTED" if promoted else "NOT_PROMOTED",
            "promoted": promoted,
            "reasons": reasons if reasons else ["beat the baseline on all gates"],
            "baseline": {k: baseline.get(k) for k in ("verdict_accuracy", "label_macro_f1", "false_safe_rate", "critical_label_recall")},
            "candidate": {k: metrics[k] for k in ("verdict_accuracy", "label_macro_f1", "false_safe_rate", "critical_label_recall", "strict_json_validity")},
        }
    decision["schema_version"] = "sf.dataset_training_export.promotion_decision.v0.1"
    decision["generated_at"] = now_utc()
    decision["strict_json_threshold"] = strict_json_threshold
    decision["training_loss_accepted_as_evidence"] = False
    decision["model_training_performed"] = False
    decision["creator_provenance"] = evaluator_provenance
    write_json(out_dir / "promotion_decision.json", decision)

    write_json(out_dir / "eval_manifest.json", {
        "schema_version": "sf.dataset_training_export.eval_manifest.v0.1",
        "generated_at": now_utc(),
        "heldout_input": rel(root, export_dir / "heldout_eval.jsonl"),
        "predictions_input": str(predictions_path) if predictions_path else None,
        "baseline_present": baseline is not None and bool(baseline),
        "baseline_input": rel(root, baseline_path) if baseline_path.exists() else None,
        "strict_json_threshold": strict_json_threshold,
        "creator_provenance": evaluator_provenance,
        "outputs": ["eval_results.json", "promotion_decision.json", "confusion_matrix.json", "per_label_metrics.json", "paired_curriculum_metrics.json", "eval_manifest.json"],
        "model_training_performed": False,
    })

    return {
        "status": "EVALUATED",
        "decision": decision["decision"],
        "promoted": decision["promoted"],
        "total_heldout_rows": total,
        "matched_predictions": matched,
        "missing_predictions": missing,
        "extra_predictions": extra,
        "strict_json_validity": metrics["strict_json_validity"],
        "verdict_accuracy": metrics["verdict_accuracy"],
        "label_macro_f1": metrics["label_macro_f1"],
        "false_safe_rate": metrics["false_safe_rate"],
        "sign_accuracy": metrics["sign_accuracy"],
        "model_training_performed": False,
        "output_root": rel(root, out_dir),
    }
