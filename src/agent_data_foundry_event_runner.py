from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_data_foundry import build_data_foundry, harvest_coordination_records, now_utc
from agent_data_foundry_lib.capture_events import harvest_capture_events
from agent_data_foundry_lib.dojo_build import build_inhouse_dojo
from agent_data_foundry_lib.eval_gate import cerberus_sentinel_baseline_eval
from agent_data_foundry_lib.refinery_handoff import package_refinery_candidate
from agent_data_foundry_lib.training_export import export_cerberus_sentinel_training

TERMINAL_EVENT_TYPES = {
    "handoff",
    "task_handoff",
    "task_completed",
    "task_closed",
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _state_path(root: Path) -> Path:
    return root / "data" / "training-library" / "10_working" / "coordination-harvest" / "event-runner" / "state.json"


def _report_paths(root: Path) -> tuple[Path, Path]:
    report_root = root / "reports" / "data-foundry"
    return report_root / "event-runner-latest.json", report_root / "event-runner-latest.md"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _latest_receipt_mtime(coordination_root: Path) -> float:
    latest = 0.0
    for path in coordination_root.glob("*/task-reports/*/*.json"):
        if path.name.lower() == "latest.json":
            continue
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _run_internal_training_pipeline(root: Path, *, task_id: str = "", generated_at: str | None = None) -> dict[str, Any]:
    """Materialize current Gold into a policy-gated, internal training export.

    This is deliberately additive to the sealed Cerberus release. It rebuilds the
    mutable internal Dojo/export/eval views from current Gold and never writes to
    ``40_release_ready`` or performs model training/promotion.
    """
    try:
        dojo = build_inhouse_dojo(root)
        training_export = export_cerberus_sentinel_training(root)
        baseline_eval = cerberus_sentinel_baseline_eval(root)
        refinery_candidate = package_refinery_candidate(
            root,
            training_export,
            task_id=task_id,
            generated_at=generated_at,
        )
    except Exception as exc:  # fail visibly without breaking the caller's handoff
        return {
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "sealed_release_mutated": False,
        }

    checks = {
        "dojo_inhouse_ready": dojo.get("status") == "INHOUSE_READY",
        "training_export_inhouse_ready": training_export.get("status") == "INHOUSE_READY",
        "broad_label_readiness": training_export.get("broad_label_readiness") is True,
        "export_readback_matches": training_export.get("readback_matches") is True,
        "train_heldout_no_overlap": training_export.get("train_heldout_no_overlap") is True,
        "all_internal_only": training_export.get("all_internal_only") is True,
        "no_model_training_performed": training_export.get("model_training_performed") is False
        and baseline_eval.get("model_training_performed") is False,
        "baseline_evaluated": baseline_eval.get("status") == "EVALUATED",
        "refinery_candidate_packaged": refinery_candidate.get("status")
        in {"CANDIDATE_READY_FOR_CANONICAL_REFINERY", "CANDIDATE_BLOCKED_LABEL_COVERAGE"},
        "no_false_final_dataset_claim": refinery_candidate.get("final_dataset_emitted") is False,
    }
    status = (
        "PASS"
        if all(checks.values())
        else "BLOCKED_LABEL_COVERAGE"
        if not checks["broad_label_readiness"]
        else "FAIL"
    )
    return {
        "status": status,
        "checks": checks,
        "dojo": dojo,
        "training_export": training_export,
        "baseline_eval": baseline_eval,
        "refinery_candidate": refinery_candidate,
        "sealed_release_mutated": False,
    }


def _write_report(root: Path, payload: dict[str, Any]) -> None:
    json_path, md_path = _report_paths(root)
    _write_json(json_path, payload)
    lines = [
        "# AgentReady Data Foundry Event Runner",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Event type: `{payload['event_type']}`",
        f"- Task id: `{payload.get('task_id') or ''}`",
        f"- Triggered: `{str(payload['triggered']).lower()}`",
        f"- Reason: `{payload['reason']}`",
    ]
    harvest = payload.get("harvest") or {}
    if harvest:
        summary = harvest.get("summary") or {}
        lines.extend(
            [
                f"- Harvest captured: `{summary.get('captured', 0)}`",
                f"- Harvest updated: `{summary.get('updated', 0)}`",
                f"- Silver rows: `{summary.get('silver_rows', 0)}`",
                f"- Gold rows: `{summary.get('gold_rows', 0)}`",
            ]
        )
    capture_harvest = payload.get("capture_harvest") or {}
    if capture_harvest:
        summary = capture_harvest.get("summary") or {}
        lines.extend(
            [
                f"- Capture events seen: `{summary.get('events_seen', 0)}`",
                f"- Capture events added: `{summary.get('captured', 0)}`",
                f"- Capture events updated: `{summary.get('updated', 0)}`",
                f"- Research command rows: `{summary.get('research_command_rows', 0)}`",
            ]
        )
    build = payload.get("build") or {}
    if build:
        summary = build.get("summary") or {}
        lines.extend(
            [
                f"- Release: `{build.get('release_id', '')}`",
                f"- Promoted: `{summary.get('promoted', 0)}`",
                f"- Rejected: `{summary.get('rejected', 0)}`",
            ]
        )
    pipeline = payload.get("internal_training_pipeline") or {}
    if pipeline:
        dojo = pipeline.get("dojo") or {}
        training_export = pipeline.get("training_export") or {}
        baseline_eval = pipeline.get("baseline_eval") or {}
        refinery_candidate = pipeline.get("refinery_candidate") or {}
        lines.extend(
            [
                f"- Internal training pipeline: `{pipeline.get('status', 'UNKNOWN')}`",
                f"- Dojo rows: `{dojo.get('rows_emitted', 0)}` / `{dojo.get('rows_seen', 0)}`",
                f"- Training rows: `{training_export.get('train_count', 0)}`",
                f"- Heldout rows: `{training_export.get('heldout_count', 0)}`",
                f"- Baseline evaluated rows: `{baseline_eval.get('evaluated_rows', 0)}`",
                f"- Canonical refinery handoff: `{refinery_candidate.get('status', 'UNKNOWN')}`",
                f"- Final dataset emitted: `{str(refinery_candidate.get('final_dataset_emitted', False)).lower()}`",
                "- Sealed Cerberus release mutated: `false`",
            ]
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _release_id(prefix: str, stamp: str) -> str:
    safe_prefix = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in prefix.strip())
    safe_prefix = safe_prefix.strip("-_") or "event"
    return f"{safe_prefix}-{stamp.replace(':', '').replace('+', '-').replace('.', '-')}"


def run_event(
    *,
    root: Path | str,
    event_type: str,
    task_id: str = "",
    source_repo: str = "",
    coordination_root: Path | str | None = None,
    debounce_seconds: int = 300,
    max_roots: int = 1000,
    limit_per_root: int = 10000,
    min_score: int = 70,
    release_prefix: str = "event-backfill",
    force: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    event_type_normalized = event_type.strip().lower()
    stamp = now or now_utc()
    payload: dict[str, Any] = {
        "schema_version": "agentready.data_foundry.event_runner.v1",
        "generated_at": stamp,
        "event_type": event_type_normalized,
        "task_id": task_id,
        "source_repo": source_repo,
        "triggered": False,
        "reason": "",
    }
    if event_type_normalized not in TERMINAL_EVENT_TYPES:
        payload["reason"] = "ignored_event_type"
        _write_report(root, payload)
        return payload

    state_path = _state_path(root)
    state = _read_json(state_path)
    current_time = _parse_time(stamp)
    last_run = _parse_time(str(state.get("last_run_at") or ""))
    elapsed: float | None = None
    if not force and current_time and last_run:
        elapsed = (current_time - last_run).total_seconds()

    harvest_coordination_root = Path(coordination_root) if coordination_root else root / "coordination"
    harvest = harvest_coordination_records(
        root,
        coordination_root=harvest_coordination_root,
        max_roots=max_roots,
        limit_per_root=limit_per_root,
        rebuild=force,
    )
    capture_harvest = harvest_capture_events(root, source_repo=source_repo)
    latest_receipt_mtime = _latest_receipt_mtime(harvest_coordination_root)
    last_build_mtime = float(state.get("last_receipt_build_mtime") or 0)
    harvest_summary = harvest.get("summary") or {}
    harvested_changes = int(harvest_summary.get("captured") or 0) + int(harvest_summary.get("updated") or 0)
    capture_summary = capture_harvest.get("summary") or {}
    captured_event_changes = (
        int(capture_summary.get("captured") or 0)
        + int(capture_summary.get("updated") or 0)
        + int(capture_summary.get("restored_to_gold") or 0)
    )
    receipt_changed = latest_receipt_mtime > last_build_mtime

    if elapsed is not None and elapsed < debounce_seconds and not harvested_changes and not captured_event_changes and not receipt_changed:
        payload.update(
            {
                "reason": "debounced_no_changes",
                "debounce_seconds": debounce_seconds,
                "seconds_since_last_run": max(0, int(elapsed)),
                "harvest": harvest,
                "capture_harvest": capture_harvest,
            }
        )
        _write_report(root, payload)
        return payload

    build: dict[str, Any] | None = None
    if receipt_changed:
        build = build_data_foundry(
            root,
            release_id=_release_id(release_prefix, stamp),
            min_score=min_score,
            coordination_root=harvest_coordination_root,
        )
        state["last_receipt_build_mtime"] = latest_receipt_mtime
    internal_training_pipeline = (
        _run_internal_training_pipeline(root, task_id=task_id, generated_at=stamp)
        if harvested_changes or captured_event_changes or force
        else None
    )

    state.update(
        {
            "last_run_at": stamp,
            "last_event_type": event_type_normalized,
            "last_task_id": task_id,
            "last_source_repo": source_repo,
            "last_harvest_gold_rows": (harvest.get("summary") or {}).get("gold_rows", 0),
            "last_capture_event_changes": captured_event_changes,
            "last_build_release_id": (build or {}).get("release_id", state.get("last_build_release_id", "")),
            "last_internal_pipeline_status": (internal_training_pipeline or {}).get(
                "status", state.get("last_internal_pipeline_status", "")
            ),
        }
    )
    _write_json(state_path, state)

    payload.update(
        {
            "triggered": True,
            "reason": "terminal_event",
            "harvest": harvest,
            "capture_harvest": capture_harvest,
            "build": build,
            "internal_training_pipeline": internal_training_pipeline,
            "state_path": str(state_path),
        }
    )
    _write_report(root, payload)
    return payload


def main(argv=None) -> int:
    if argv is None:
        from factory_capture.governed import auto_capture_current_process

        captured_exit = auto_capture_current_process(surface="agent-data-foundry-event-runner")
        if captured_exit is not None:
            return captured_exit
    parser = argparse.ArgumentParser(description="Run bounded Data Foundry harvest/build after Factory lifecycle events.")
    parser.add_argument("--root", default=os.environ.get("AGENTREADY_HOME") or str(Path.home() / ".agentready"))
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--source-repo", default="")
    parser.add_argument("--coordination-root", default="")
    parser.add_argument("--debounce-seconds", type=int, default=300)
    parser.add_argument("--max-roots", type=int, default=1000)
    parser.add_argument("--limit-per-root", type=int, default=10000)
    parser.add_argument("--min-score", type=int, default=70)
    parser.add_argument("--release-prefix", default="event-backfill")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    result = run_event(
        root=args.root,
        event_type=args.event_type,
        task_id=args.task_id,
        source_repo=args.source_repo,
        coordination_root=args.coordination_root or None,
        debounce_seconds=args.debounce_seconds,
        max_roots=args.max_roots,
        limit_per_root=args.limit_per_root,
        min_score=args.min_score,
        release_prefix=args.release_prefix,
        force=args.force,
    )
    print("AgentReady Data Foundry event runner")
    print(f"Triggered: {result['triggered']} Reason: {result['reason']}")
    if result.get("harvest"):
        summary = result["harvest"]["summary"]
        print(f"Gold rows: {summary['gold_rows']} Captured: {summary['captured']}")
    if result.get("build"):
        summary = result["build"]["summary"]
        print(f"Release: {result['build']['release_id']} Promoted: {summary['promoted']} Rejected: {summary['rejected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
