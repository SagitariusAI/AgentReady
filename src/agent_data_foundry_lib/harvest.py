# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Coordination-harvest + ARCHIVE receipt-export pipeline for the Agent Data Foundry.

The receipt-curation half of the foundry: ``harvest_coordination_records`` walks the coordination
receipts, derives the silver/gold coordination rows + capture signals, and writes the harvest
shelf (manifest + checksums + report); ``build_data_foundry`` is the top-level build that exports
the ARCHIVE training folders from eligible receipts (``export_row`` + ``metadata`` + ``evidence_text``
+ ``rejection_reasons``) and writes the manifest / plan / report. The harvest schema + eligible
statuses, the ARCHIVE payload budget, and the export-folder map live here.

Clean leaf: composes the adjudication row builders (``gold_coordination_row`` /
``silver_coordination_row`` / fingerprint + source-id + ``safe_segment``), the receipt primitives
(``receipts``), ``io_jsonl``, and the ``paths`` foundation (home + run-id / release-id) -- no
back-import to agent_data_foundry. Exported rows, manifests, checksums, rejection reasons, report
schema strings, and output paths are preserved byte-for-byte from the pre-split module. This is a
working curation shelf only; it never emits a commercial release package.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.adjudication import (
    gold_coordination_row,
    safe_segment,
    silver_coordination_row,
    task_fingerprint,
    task_source_id,
)
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    jsonl_row_count,
    now_utc,
    read_json,
    read_jsonl,
    rel,
    sha256_file,
    write_json,
)
from agent_data_foundry_lib.paths import AGENTREADY_HOME, default_release_id, run_id_utc
from agent_data_foundry_lib.receipts import PROMOTABLE_POLICIES, discover_receipts
from agent_workflow_lanes import classify_workflow_lane

ARCHIVE_PAYLOAD_BUDGET_BYTES = 95_000_000_000

EXPORT_FOLDERS = {
    "instruction_jsonl": Path("30_curated/sft/instruction-jsonl/instruction_jsonl.jsonl"),
    "chat_messages_jsonl": Path("30_curated/sft/chat-messages-jsonl/chat_messages_jsonl.jsonl"),
    "preference_dpo_jsonl": Path("30_curated/preferences/dpo-jsonl/preference_dpo_jsonl.jsonl"),
    "tool_use_jsonl": Path("30_curated/tool-use/tool-call-jsonl/tool_use_jsonl.jsonl"),
    "evaluation_jsonl": Path("30_curated/evaluations/jsonl/evaluation_jsonl.jsonl"),
    "retrieval_jsonl": Path("30_curated/retrieval/jsonl/retrieval_jsonl.jsonl"),
}

COORDINATION_HARVEST_SCHEMA = "agentready.data_foundry.coordination_harvest.v1"
COORDINATION_ELIGIBLE_STATUSES = {"completed", "closed", "handoff"}


def rejection_reasons(receipt: dict[str, Any], min_score: int) -> list[str]:
    reasons: list[str] = []
    workflow_lane, _lane_source = classify_workflow_lane(receipt)
    if workflow_lane != "research" and not receipt.get("research_import_authorized"):
        reasons.append(f"cross_lane_import_not_authorized:{workflow_lane}")
    quality = receipt.get("quality") or {}
    score = int(quality.get("score") or 0)
    if not quality.get("passed") or score < min_score:
        reasons.append(f"quality_below_{min_score}")

    dataset_format = str(receipt.get("dataset_format_target") or "")
    if dataset_format not in EXPORT_FOLDERS:
        reasons.append(f"unsupported_dataset_format:{dataset_format or 'missing'}")

    policy = str(receipt.get("work_product_policy") or "")
    if policy == "external_source_citation_only" and dataset_format != "retrieval_jsonl":
        reasons.append("external_source_citation_only")
    elif policy not in PROMOTABLE_POLICIES and not (policy == "external_source_citation_only" and dataset_format == "retrieval_jsonl"):
        reasons.append(policy or "missing_work_product_policy")

    classification = str(receipt.get("data_classification") or "")
    if classification == "restricted":
        reasons.append("restricted_classification")
    if str(receipt.get("retention_class") or "") == "ephemeral_30d":
        reasons.append("ephemeral_retention")
    if str(receipt.get("training_value") or "") == "none" and dataset_format != "retrieval_jsonl":
        reasons.append("no_training_value")
    if receipt.get("promotion_blockers"):
        reasons.append("promotion_blockers")
    if receipt.get("sensitive_fields"):
        reasons.append("sensitive_fields_require_redaction")
    if str(receipt.get("data_classification") or "") == "secret_pointer_only":
        reasons.append("secret_pointer_only")
    return reasons


def metadata(receipt: dict[str, Any], source_path: Path | None = None) -> dict[str, Any]:
    workflow_lane, workflow_lane_source = classify_workflow_lane(receipt)
    meta = {
        "receipt_id": receipt.get("receipt_id"),
        "task_id": receipt.get("task_id"),
        "agent": receipt.get("agent"),
        "repo": receipt.get("repo"),
        "generated_utc": receipt.get("generated_utc"),
        "artifact_type": receipt.get("artifact_type"),
        "workflow_lane": workflow_lane,
        "workflow_lane_source": workflow_lane_source,
        "research_import_authorized": bool(receipt.get("research_import_authorized")),
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "collection_scope": receipt.get("collection_scope"),
        "collection_purpose": receipt.get("collection_purpose"),
        "data_classification": receipt.get("data_classification"),
        "retention_class": receipt.get("retention_class"),
        "training_value": receipt.get("training_value"),
        "work_product_policy": receipt.get("work_product_policy"),
        "dataset_labels": receipt.get("dataset_labels") or [],
        "quality": receipt.get("quality") or {},
    }
    if source_path:
        meta["source_receipt_path"] = str(source_path)
    return meta


def evidence_text(receipt: dict[str, Any]) -> str:
    rows = []
    for item in receipt.get("evidence") or []:
        if isinstance(item, dict):
            rows.append(f"{item.get('path', '')} [{item.get('status', '')}]: {item.get('meaning', '')}".strip())
    return "\n".join(row for row in rows if row)


def export_row(receipt: dict[str, Any], source_path: Path) -> dict[str, Any] | None:
    fmt = str(receipt.get("dataset_format_target") or "")
    meta = metadata(receipt, source_path)
    if fmt == "instruction_jsonl":
        return {
            "instruction": receipt.get("intent") or receipt.get("summary") or "",
            "input": evidence_text(receipt),
            "output": receipt.get("outcome") or receipt.get("future_model_should_learn") or "",
            "metadata": meta,
        }
    if fmt == "chat_messages_jsonl":
        return {
            "messages": [
                {"role": "system", "content": "You are an AgentReady software-factory worker. Use evidence before claims."},
                {"role": "user", "content": receipt.get("intent") or receipt.get("summary") or ""},
                {"role": "assistant", "content": receipt.get("outcome") or receipt.get("future_model_should_learn") or ""},
            ],
            "metadata": meta,
        }
    if fmt == "preference_dpo_jsonl":
        chosen = receipt.get("outcome") or receipt.get("summary") or ""
        return {
            "prompt": receipt.get("intent") or receipt.get("summary") or "",
            "chosen": chosen,
            "rejected": "Claim success without evidence, classification, retention, or next action.",
            "metadata": meta,
        }
    if fmt == "tool_use_jsonl":
        return {
            "task": receipt.get("intent") or receipt.get("summary") or "",
            "available_tools": ["agent-tool-router", "agent-report-submit", "agent-training-library", "agent-data-foundry"],
            "selected_tools": receipt.get("commands_run") or [],
            "evidence": receipt.get("evidence") or [],
            "outcome": receipt.get("outcome") or "",
            "metadata": meta,
        }
    if fmt == "evaluation_jsonl":
        return {
            "case_id": receipt.get("receipt_id") or receipt.get("task_id"),
            "prompt": receipt.get("intent") or receipt.get("summary") or "",
            "expected": receipt.get("outcome") or receipt.get("future_model_should_learn") or "",
            "rubric": {
                "must_include_evidence": True,
                "must_preserve_classification": True,
                "must_state_next_action": True,
            },
            "metadata": meta,
        }
    if fmt == "retrieval_jsonl":
        return {
            "doc_id": receipt.get("receipt_id") or receipt.get("task_id"),
            "text": "\n\n".join(
                value
                for value in (
                    receipt.get("intent") or "",
                    receipt.get("summary") or "",
                    receipt.get("outcome") or "",
                    receipt.get("future_model_should_learn") or "",
                    evidence_text(receipt),
                )
                if value
            ),
            "source": str(source_path),
            "timestamp": receipt.get("generated_utc") or now_utc(),
            "classification": receipt.get("data_classification") or "internal",
            "metadata": meta,
        }
    return None


def read_harvest_ledger(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {"schema_version": COORDINATION_HARVEST_SCHEMA, "captured_sources": {}}
    captured = payload.get("captured_sources")
    if not isinstance(captured, dict):
        payload["captured_sources"] = {}
    return payload


def write_harvest_checksums(root: Path, harvest_root: Path, files: list[Path]) -> Path:
    checksums = {
        "schema_version": COORDINATION_HARVEST_SCHEMA,
        "generated_at": now_utc(),
        "files": [file_record(root, path) for path in files if path.exists()],
    }
    path = harvest_root / "metadata" / "checksums.json"
    write_json(path, checksums)
    return path


def write_harvest_report(root: Path, result: dict[str, Any]) -> None:
    report_root = root / "reports" / "data-foundry"
    report_root.mkdir(parents=True, exist_ok=True)
    latest_json = report_root / "coordination-harvest-latest.json"
    write_json(latest_json, result)
    latest_md = report_root / "coordination-harvest-latest.md"
    summary = result["summary"]
    lines = [
        "# AgentReady Data Foundry Coordination Harvest",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Coordination root: `{result['coordination_root']}`",
        f"- Roots scanned: `{summary['roots_scanned']}`",
        f"- Captured: `{summary['captured']}`",
        f"- Existing skipped: `{summary['skipped_existing']}`",
        f"- Ineligible skipped: `{summary['skipped_ineligible']}`",
        f"- Invalid skipped: `{summary['skipped_invalid']}`",
        f"- Silver rows: `{summary['silver_rows']}`",
        f"- Gold rows: `{summary['gold_rows']}`",
        f"- Manifest: `{result['manifest_path']}`",
        f"- Checksums: `{result['checksums_path']}`",
        "",
        "This harvest is a working curation shelf only. It does not emit a commercial release package.",
    ]
    latest_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def harvest_coordination_records(
    root: Path | str = AGENTREADY_HOME,
    coordination_root: Path | str | None = None,
    max_roots: int = 100,
    limit_per_root: int = 250,
    rebuild: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    coordination_root = Path(coordination_root) if coordination_root else root / "coordination"
    harvest_root = root / "data" / "training-library" / "10_working" / "coordination-harvest"
    if rebuild and harvest_root.exists():
        shutil.rmtree(harvest_root)
    bronze_root = harvest_root / "00_bronze" / "tasks"
    silver_path = harvest_root / "10_silver" / "incidents.jsonl"
    gold_path = harvest_root / "20_gold" / "product_incidents.jsonl"
    ledger_path = harvest_root / "metadata" / "coordination_capture_ledger.json"

    ledger = read_harvest_ledger(ledger_path)
    captured_sources = ledger["captured_sources"]
    new_silver_rows: list[dict[str, Any]] = []
    new_gold_rows: list[dict[str, Any]] = []
    summary = {
        "max_roots": max_roots,
        "limit_per_root": limit_per_root,
        "available_roots": 0,
        "roots_scanned": 0,
        "roots_truncated": False,
        "truncated_roots_count": 0,
        "task_roots_truncated": 0,
        "truncated_tasks_count": 0,
        "truncated": False,
        "tasks_seen": 0,
        "captured": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_ineligible": 0,
        "skipped_invalid": 0,
        "skipped_cross_lane": 0,
        "silver_rows": 0,
        "gold_rows": 0,
    }
    updated_source_ids: set[str] = set()
    updated_source_hashes: set[str] = set()

    roots = [path for path in sorted(coordination_root.iterdir()) if path.is_dir()] if coordination_root.exists() else []
    summary["available_roots"] = len(roots)
    summary["truncated_roots_count"] = max(0, len(roots) - max(0, max_roots))
    summary["roots_truncated"] = summary["truncated_roots_count"] > 0
    for repo_root in roots[: max(0, max_roots)]:
        task_root = repo_root / "tasks"
        if not task_root.exists():
            continue
        summary["roots_scanned"] += 1
        task_paths = sorted(task_root.glob("*.json"))
        truncated_tasks = max(0, len(task_paths) - max(0, limit_per_root))
        if truncated_tasks:
            summary["task_roots_truncated"] += 1
            summary["truncated_tasks_count"] += truncated_tasks
        for source_path in task_paths[: max(0, limit_per_root)]:
            summary["tasks_seen"] += 1
            task = read_json(source_path)
            if not isinstance(task, dict) or not task.get("id"):
                summary["skipped_invalid"] += 1
                continue
            status = str(task.get("status") or "").lower()
            source_id = task_source_id(repo_root.name, task, source_path)
            if status not in COORDINATION_ELIGIBLE_STATUSES:
                summary["skipped_ineligible"] += 1
                continue
            workflow_lane, _lane_source = classify_workflow_lane(task)
            if workflow_lane != "research" and not task.get("research_import_authorized"):
                summary["skipped_cross_lane"] += 1
                continue

            fingerprint = task_fingerprint(source_id, task)
            previous = captured_sources.get(source_id)
            previous_fingerprint = str(previous.get("fingerprint") or "") if isinstance(previous, dict) else ""
            if previous_fingerprint == fingerprint:
                summary["skipped_existing"] += 1
                continue
            is_update = source_id in captured_sources
            bronze_path = bronze_root / safe_segment(repo_root.name) / safe_segment(str(task.get("id"))) / f"{fingerprint}.json"
            write_json(
                bronze_path,
                {
                    "schema_version": "agentready.data_foundry.coordination_bronze.v1",
                    "source_id": source_id,
                    "source_path": str(source_path),
                    "fingerprint": fingerprint,
                    "captured_at": now_utc(),
                    "task": task,
                },
            )
            new_silver_rows.append(silver_coordination_row(repo_root.name, source_path, source_id, fingerprint, task))
            gold_row = gold_coordination_row(source_id, fingerprint, task)
            gold_row["source_lineage"] = {
                "source_id": source_id,
                "source_id_hash": hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
                "fingerprint": fingerprint,
                "source_path": str(source_path),
                "bronze_path": rel(root, bronze_path),
                "bronze_sha256": sha256_file(bronze_path),
                "ledger_path": rel(root, ledger_path),
                "provenance_type": "COORDINATION_TASK",
            }
            new_gold_rows.append(gold_row)
            updated_source_ids.add(source_id)
            updated_source_hashes.add(hashlib.sha256(source_id.encode("utf-8")).hexdigest())
            captured_sources[source_id] = {
                "fingerprint": fingerprint,
                "captured_at": now_utc(),
                "bronze_path": rel(root, bronze_path),
                "version": int(previous.get("version") or 1) + 1 if isinstance(previous, dict) else 1,
            }
            summary["updated" if is_update else "captured"] += 1

    if new_silver_rows:
        existing_silver = [
            row for row in read_jsonl(silver_path) if str(row.get("source_id") or "") not in updated_source_ids
        ]
        existing_gold = [
            row
            for row in read_jsonl(gold_path)
            if str(row.get("source_id_hash") or "") not in updated_source_hashes
        ]
        append_jsonl(silver_path, [*existing_silver, *new_silver_rows])
        append_jsonl(gold_path, [*existing_gold, *new_gold_rows])
    ledger["updated_at"] = now_utc()
    write_json(ledger_path, ledger)

    summary["silver_rows"] = jsonl_row_count(silver_path)
    summary["gold_rows"] = jsonl_row_count(gold_path)
    summary["truncated"] = bool(summary["roots_truncated"] or summary["task_roots_truncated"])
    run_id = run_id_utc()
    run_manifest_path = harvest_root / "manifests" / "runs" / f"{run_id}.json"
    latest_manifest_path = harvest_root / "manifests" / "latest.json"
    checksums_path = write_harvest_checksums(root, harvest_root, [silver_path, gold_path, ledger_path])
    manifest = {
        "schema_version": COORDINATION_HARVEST_SCHEMA,
        "generated_at": now_utc(),
        "run_id": run_id,
        "coordination_root": str(coordination_root),
        "summary": summary,
        "bounds": {
            "max_roots": max_roots,
            "limit_per_root": limit_per_root,
            "available_roots": summary["available_roots"],
            "roots_truncated": summary["roots_truncated"],
            "truncated_roots_count": summary["truncated_roots_count"],
            "task_roots_truncated": summary["task_roots_truncated"],
            "truncated_tasks_count": summary["truncated_tasks_count"],
            "truncated": summary["truncated"],
        },
        "captured_sources": sorted(captured_sources),
        "silver_path": rel(root, silver_path),
        "gold_path": rel(root, gold_path),
        "ledger_path": rel(root, ledger_path),
        "checksums_path": rel(root, checksums_path),
        "commercial_release_emitted": False,
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "cross_lane_import_policy": "explicit_only",
        "rebuilt": rebuild,
    }
    write_json(run_manifest_path, manifest)
    write_json(latest_manifest_path, manifest)

    result = {
        **manifest,
        "manifest_path": rel(root, latest_manifest_path),
        "run_manifest_path": rel(root, run_manifest_path),
    }
    write_harvest_report(root, result)
    return result


def write_rejections(root: Path, release_id: str, rejections: list[dict[str, Any]]) -> Path:
    path = root / "data" / "training-library" / "20_rejected" / "weak" / f"{release_id}-rejections.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in rejections:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def copy_raw_receipt(root: Path, release_id: str, source_path: Path, receipt: dict[str, Any]) -> Path:
    receipt_id = str(receipt.get("receipt_id") or source_path.stem).replace("\\", "_").replace("/", "_")
    raw_root = root / "data" / "training-library" / "01_raw" / "frontier-receipts" / release_id
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"{receipt_id}.json"
    shutil.copy2(source_path, target)
    return target


def file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "relative_path": rel(root, path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_archive_plan(root: Path, release_id: str, files: list[Path]) -> Path:
    plan_files = [file_record(root, path) for path in files if path.exists() and path.stat().st_size > 0]
    volumes: list[dict[str, Any]] = []
    current: dict[str, Any] = {"volume_id": f"ARCHIVE-{release_id}-001", "bytes": 0, "files": []}
    volume_index = 1
    for record in plan_files:
        if current["files"] and current["bytes"] + record["bytes"] > ARCHIVE_PAYLOAD_BUDGET_BYTES:
            volumes.append(current)
            volume_index += 1
            current = {"volume_id": f"ARCHIVE-{release_id}-{volume_index:03d}", "bytes": 0, "files": []}
        current["files"].append(record)
        current["bytes"] += record["bytes"]
    if current["files"] or not volumes:
        volumes.append(current)

    payload = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "release_id": release_id,
        "media_class": "ARCHIVE",
        "payload_budget_bytes": ARCHIVE_PAYLOAD_BUDGET_BYTES,
        "volumes": volumes,
    }
    path = root / "data" / "training-library" / "90_archives" / "archive-100gb" / "staging" / f"{release_id}-archive-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_manifest(
    root: Path,
    release_id: str,
    summary: dict[str, int],
    exports: dict[str, dict[str, Any]],
    rejections: list[dict[str, Any]],
    files: list[Path],
    archive_plan_path: Path,
) -> Path:
    release_root = root / "data" / "training-library" / "40_releases" / "by-date" / release_id
    release_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "release_id": release_id,
        "summary": summary,
        "exports": exports,
        "rejections": rejections,
        "files": [file_record(root, path) for path in files if path.exists()],
        "archive_plan_path": rel(root, archive_plan_path),
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "cross_lane_import_policy": "explicit_only",
    }
    path = release_root / "MANIFEST.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    current = root / "data" / "training-library" / "40_releases" / "current" / "MANIFEST.json"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def write_report(root: Path, release_id: str, manifest: dict[str, Any]) -> Path:
    report_root = root / "reports" / "data-foundry"
    report_root.mkdir(parents=True, exist_ok=True)
    path = report_root / f"data-foundry-{release_id}.md"
    lines = [
        "# AgentReady Data Foundry",
        "",
        f"- Release: `{release_id}`",
        f"- Generated: {manifest['generated_at']}",
        f"- Promoted: `{manifest['summary']['promoted']}`",
        f"- Rejected: `{manifest['summary']['rejected']}`",
        f"- Manifest: `{manifest['manifest_path']}`",
        f"- ARCHIVE plan: `{manifest['archive_plan_path']}`",
        "",
        "## Exports",
        "",
        "| Format | Records | Path |",
        "| --- | ---: | --- |",
    ]
    for fmt, info in sorted(manifest["exports"].items()):
        lines.append(f"| `{fmt}` | {info['records']} | `{info['path']}` |")
    lines.extend(["", "## Rejections", "", "| Receipt | Reasons |", "| --- | --- |"])
    for item in manifest["rejections"][:50]:
        lines.append(f"| `{item['receipt_id']}` | {', '.join(item['reasons'])} |")
    if len(manifest["rejections"]) > 50:
        lines.append(f"| ... | {len(manifest['rejections']) - 50} more |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_root / "latest.md").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_json = report_root / "latest.json"
    latest_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def build_data_foundry(
    root: Path | str = AGENTREADY_HOME,
    release_id: str | None = None,
    min_score: int = 70,
    coordination_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    receipt_root = Path(coordination_root) if coordination_root else None
    release_id = release_id or default_release_id()
    library_root = root / "data" / "training-library"
    release_root = library_root / "40_releases" / "by-date" / release_id
    release_root.mkdir(parents=True, exist_ok=True)

    promoted_rows: dict[str, list[dict[str, Any]]] = {key: [] for key in EXPORT_FOLDERS}
    rejections: list[dict[str, Any]] = []
    raw_receipt_files: list[Path] = []
    receipt_count = 0
    for source_path, receipt in discover_receipts(root, receipt_root):
        receipt_count += 1
        reasons = rejection_reasons(receipt, min_score)
        if reasons:
            rejections.append(
                {
                    "receipt_id": receipt.get("receipt_id") or source_path.stem,
                    "source_path": str(source_path),
                    "reasons": reasons,
                    "metadata": metadata(receipt, source_path),
                }
            )
            continue
        raw_receipt_files.append(copy_raw_receipt(root, release_id, source_path, receipt))
        row = export_row(receipt, source_path)
        if row is None:
            rejections.append(
                {
                    "receipt_id": receipt.get("receipt_id") or source_path.stem,
                    "source_path": str(source_path),
                    "reasons": ["export_transform_failed"],
                    "metadata": metadata(receipt, source_path),
                }
            )
            continue
        promoted_rows[str(receipt["dataset_format_target"])].append(row)

    export_info: dict[str, dict[str, Any]] = {}
    output_files: list[Path] = []
    for fmt, rows in promoted_rows.items():
        if not rows:
            continue
        curated_path = library_root / EXPORT_FOLDERS[fmt]
        release_path = release_root / EXPORT_FOLDERS[fmt]
        append_jsonl(curated_path, rows)
        release_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(curated_path, release_path)
        output_files.append(release_path)
        export_info[fmt] = {
            "records": len(rows),
            "path": rel(root, release_path),
            "curated_path": rel(root, curated_path),
            "sha256": sha256_file(release_path),
            "bytes": release_path.stat().st_size,
        }

    rejection_path = write_rejections(root, release_id, rejections)
    output_files.extend(raw_receipt_files)
    output_files.append(rejection_path)
    archive_plan_path = write_archive_plan(root, release_id, [path for path in output_files if path.name != rejection_path.name])
    summary = {
        "receipts_seen": receipt_count,
        "promoted": sum(len(rows) for rows in promoted_rows.values()),
        "rejected": len(rejections),
        "export_files": len(export_info),
    }
    manifest_path = write_manifest(root, release_id, summary, export_info, rejections, output_files, archive_plan_path)

    result = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "release_id": release_id,
        "summary": summary,
        "exports": export_info,
        "rejections": rejections,
        "manifest_path": rel(root, manifest_path),
        "archive_plan_path": rel(root, archive_plan_path),
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "cross_lane_import_policy": "explicit_only",
    }
    write_report(root, release_id, result)
    return result
