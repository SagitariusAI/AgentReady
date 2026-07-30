# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Canonical Factory Capture event intake for the Agent Data Foundry."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from agent_data_foundry_lib.adjudication import receipt_gold_row, safe_segment
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    now_utc,
    read_json,
    read_jsonl,
    rel,
    sha256_file,
    write_json,
)

CAPTURE_HARVEST_SCHEMA = "agentready.data_foundry.capture_event_harvest.v1"
VALID_LANES = {"personal", "business", "research"}


def _fingerprint(event: dict[str, Any]) -> str:
    canonical = json.dumps(event, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_id(repo_root: str, event_id: str) -> str:
    repo_hash = hashlib.sha256(repo_root.encode("utf-8")).hexdigest()[:16]
    return f"factory-capture/{repo_hash}/{event_id}"


def _capture_store_roots(
    root: Path,
    source_repo: str = "",
    extra_roots: Iterable[Path | str] = (),
) -> list[Path]:
    candidates = [root, *(Path(item) for item in extra_roots)]
    if source_repo:
        candidates.append(Path(source_repo))
    fleet_report = root / "reports" / "factory-capture-fleet" / "latest.json"
    fleet = read_json(fleet_report) or {}
    for project in fleet.get("projects") or []:
        if isinstance(project, dict) and project.get("initialized") and project.get("declared_root"):
            candidates.append(Path(str(project["declared_root"])))
    stores: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        store = candidate if candidate.name == ".factory_capture" else candidate / ".factory_capture"
        key = str(store.resolve(strict=False)).lower()
        if key not in seen and (store / "config.json").is_file():
            seen.add(key)
            stores.append(store)
    return stores


def _verified_log(store: Path, relative_path: object, expected_sha: object) -> tuple[str | None, str]:
    if not relative_path:
        return None, ""
    path = store / str(relative_path)
    if not path.is_file():
        return None, "missing"
    text = path.read_text(encoding="utf-8")
    actual = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return text, "" if not expected_sha or actual == str(expected_sha) else "hash_mismatch"


def _gold_capture_row(
    *,
    event: dict[str, Any],
    source_id: str,
    fingerprint: str,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    success = int(event.get("exit_code") or 0) == 0 and str(event.get("status") or "") == "success"
    command = [str(part) for part in (event.get("command") or [])]
    receipt = {
        "receipt_id": str(event["event_id"]),
        "task_id": str(event["event_id"]),
        "outcome": f"Governed command {'succeeded' if success else 'failed'}: {' '.join(command)}",
        "evidence": [
            f"exit_code={event.get('exit_code')}",
            f"stdout_sha256={event.get('stdout_sha256') or ''}",
            f"stderr_sha256={event.get('stderr_sha256') or ''}",
        ],
        "quality": {"passed": success, "score": 100 if success else 0},
        "promotion_blockers": [] if success else ["command_exit_nonzero"],
        "commands_run": command,
        "workflow_lane": "research",
        "workflow_lane_source": str(event.get("workflow_lane_source") or "capture_event"),
        "source_signals": {
            "commands_run": command,
            "exit_code": event.get("exit_code"),
            "stdout_sha256": event.get("stdout_sha256"),
            "stderr_sha256": event.get("stderr_sha256"),
        },
    }
    label = "SUPPORTED_CLAIM" if success else "CLAIM_WITHOUT_EVIDENCE"
    verdict = "SAFE" if success else "BLOCK"
    rationale = "Governed command outcome is backed by exit code and redacted log hashes."
    row = receipt_gold_row(receipt, label, verdict, rationale)
    row.update(
        {
            "source_id_hash": hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            "fingerprint": fingerprint,
            "provenance_type": "CAPTURE_EVENT",
            "source_mode": "factory_capture_command_run",
            "source_lineage": lineage,
        }
    )
    return row


def harvest_capture_events(
    root: Path | str,
    *,
    source_repo: str = "",
    capture_roots: Iterable[Path | str] = (),
) -> dict[str, Any]:
    """Ingest explicit-lane capture events and promote governed research commands."""
    root = Path(root)
    harvest_root = root / "data" / "training-library" / "10_working" / "capture-event-harvest"
    bronze_root = harvest_root / "00_bronze"
    silver_path = harvest_root / "10_silver" / "capture_events.jsonl"
    ledger_path = harvest_root / "metadata" / "capture_event_ledger.json"
    gold_path = (
        root
        / "data"
        / "training-library"
        / "10_working"
        / "coordination-harvest"
        / "20_gold"
        / "product_incidents.jsonl"
    )
    ledger = read_json(ledger_path) or {
        "schema_version": CAPTURE_HARVEST_SCHEMA,
        "captured_sources": {},
    }
    captured_sources = ledger.setdefault("captured_sources", {})
    existing_silver = read_jsonl(silver_path)
    existing_gold = read_jsonl(gold_path)
    existing_gold_hashes = {str(row.get("source_id_hash") or "") for row in existing_gold}
    changed_source_ids: set[str] = set()
    changed_source_hashes: set[str] = set()
    new_silver: list[dict[str, Any]] = []
    new_gold: list[dict[str, Any]] = []
    summary = {
        "stores_scanned": 0,
        "events_seen": 0,
        "captured": 0,
        "updated": 0,
        "restored_to_gold": 0,
        "skipped_existing": 0,
        "skipped_missing_lane": 0,
        "skipped_invalid": 0,
        "research_command_rows": 0,
        "cross_lane_rows": 0,
    }

    for store in _capture_store_roots(root, source_repo, capture_roots):
        summary["stores_scanned"] += 1
        config = read_json(store / "config.json") or {}
        repo_root = str(config.get("repo_root") or store.parent)
        event_path = store / "events.jsonl"
        for event in read_jsonl(event_path):
            summary["events_seen"] += 1
            event_id = str(event.get("event_id") or "")
            lane = str(event.get("workflow_lane") or "").strip().lower()
            if not event_id or str(event.get("schema") or "") != "sf.capture_event.v0.1":
                summary["skipped_invalid"] += 1
                continue
            if lane not in VALID_LANES:
                summary["skipped_missing_lane"] += 1
                continue
            source_id = _source_id(repo_root, event_id)
            fingerprint = _fingerprint(event)
            source_hash = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
            previous = captured_sources.get(source_id)
            restore_gold = (
                isinstance(previous, dict)
                and previous.get("fingerprint") == fingerprint
                and lane == "research"
                and event.get("event_type") == "command_run"
                and source_hash not in existing_gold_hashes
            )
            if isinstance(previous, dict) and previous.get("fingerprint") == fingerprint and not restore_gold:
                summary["skipped_existing"] += 1
                continue
            stdout, stdout_problem = _verified_log(store, event.get("stdout_log"), event.get("stdout_sha256"))
            stderr, stderr_problem = _verified_log(store, event.get("stderr_log"), event.get("stderr_sha256"))
            if stdout_problem or stderr_problem:
                summary["skipped_invalid"] += 1
                continue
            bronze_path = bronze_root / lane / safe_segment(Path(repo_root).name) / f"{fingerprint}.json"
            bronze = {
                "schema_version": CAPTURE_HARVEST_SCHEMA,
                "captured_at": now_utc(),
                "source_id": source_id,
                "fingerprint": fingerprint,
                "workflow_lane": lane,
                "data_lane": lane,
                "machinery_zone": "FACTORY",
                "source_event_path": str(event_path),
                "event": event,
                "redacted_logs": {"stdout": stdout, "stderr": stderr},
            }
            if not bronze_path.exists():
                write_json(bronze_path, bronze)
            lineage = {
                "source_id": source_id,
                "source_id_hash": source_hash,
                "fingerprint": fingerprint,
                "bronze_path": rel(root, bronze_path),
                "bronze_sha256": sha256_file(bronze_path),
                "ledger_path": rel(root, ledger_path),
                "source_event_path": str(event_path),
                "event_id": event_id,
                "stdout_sha256": event.get("stdout_sha256"),
                "stderr_sha256": event.get("stderr_sha256"),
            }
            new_silver.append(
                {
                    "schema_version": CAPTURE_HARVEST_SCHEMA,
                    "source_id": source_id,
                    "fingerprint": fingerprint,
                    "event_type": event.get("event_type"),
                    "workflow_lane": lane,
                    "data_lane": lane,
                    "provenance_type": "CAPTURE_EVENT",
                    "source_lineage": lineage,
                }
            )
            changed_source_ids.add(source_id)
            changed_source_hashes.add(lineage["source_id_hash"])
            if lane == "research" and event.get("event_type") == "command_run":
                new_gold.append(
                    _gold_capture_row(
                        event=event,
                        source_id=source_id,
                        fingerprint=fingerprint,
                        lineage=lineage,
                    )
                )
                summary["research_command_rows"] += 1
                if restore_gold:
                    summary["restored_to_gold"] += 1
            elif lane != "research":
                summary["cross_lane_rows"] += 1
            if not restore_gold:
                summary["updated" if isinstance(previous, dict) else "captured"] += 1
            captured_sources[source_id] = {
                "fingerprint": fingerprint,
                "bronze_path": rel(root, bronze_path),
                "workflow_lane": lane,
                "version": int(previous.get("version") or 1) + 1 if isinstance(previous, dict) else 1,
            }

    if changed_source_ids:
        append_jsonl(
            silver_path,
            [
                row
                for row in existing_silver
                if str(row.get("source_id") or "") not in changed_source_ids
            ]
            + new_silver,
        )
        append_jsonl(
            gold_path,
            [
                row
                for row in existing_gold
                if str(row.get("source_id_hash") or "") not in changed_source_hashes
            ]
            + new_gold,
        )
    ledger["updated_at"] = now_utc()
    write_json(ledger_path, ledger)
    result = {
        "schema_version": CAPTURE_HARVEST_SCHEMA,
        "generated_at": now_utc(),
        "summary": summary,
        "silver_path": rel(root, silver_path),
        "gold_path": rel(root, gold_path),
        "ledger_path": rel(root, ledger_path),
        "workflow_lanes": sorted(VALID_LANES),
        "research_promotion_policy": "explicit_research_command_run_only",
        "commercial_release_emitted": False,
    }
    report = root / "reports" / "data-foundry" / "capture-event-harvest-latest.json"
    write_json(report, result)
    return result
