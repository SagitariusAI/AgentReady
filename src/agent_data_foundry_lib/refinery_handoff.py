# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Create immutable handoff bundles for an optional refinement pipeline.

AgentReady performs activity capture, curation, rights gating, and deterministic
train/heldout candidate construction. This module packages those inputs with a
provider-neutral sequence of semantic enrichment, relationship enrichment,
review, and final materialization. It never labels an intermediate export as a
final dataset or fabricates downstream acknowledgements.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import now_utc

CANONICAL_STAGES = (
    "curriculum_candidate",
    "semantic_enrichment",
    "relationship_enrichment",
    "final_semantic_review",
    "final_dataset_materialization",
)

ARTIFACT_NAMES = (
    "sft_train.jsonl",
    "classification_train.jsonl",
    "heldout_eval.jsonl",
    "export_manifest.json",
    "rights_report.json",
    "split_manifest.json",
    "curriculum_manifest.json",
    "provenance_manifest.json",
    "lineage_manifest.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
    return safe.strip("-_") or "event"


def package_refinery_candidate(
    root: Path | str,
    training_export: dict[str, Any],
    *,
    task_id: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    stamp = generated_at or now_utc()
    source_root = root / str(training_export["output_root"])
    bundle_id = _safe_id(f"{task_id or 'event'}-{stamp}")
    out_root = (
        root
        / "data"
        / "training-library"
        / "30_refinery_handoff"
        / "candidates"
        / bundle_id
    )
    out_root.mkdir(parents=True, exist_ok=False)

    artifacts: list[dict[str, Any]] = []
    for name in ARTIFACT_NAMES:
        source = source_root / name
        if not source.is_file():
            raise FileNotFoundError(f"required refinery candidate artifact missing: {source}")
        destination = out_root / name
        shutil.copy2(source, destination)
        artifacts.append(
            {
                "name": name,
                "path": str(destination),
                "sha256": _sha256(destination),
                "bytes": destination.stat().st_size,
            }
        )

    broad_label_readiness = training_export.get("broad_label_readiness") is True
    candidate_status = (
        "CANDIDATE_READY_FOR_CANONICAL_REFINERY"
        if broad_label_readiness
        else "CANDIDATE_BLOCKED_LABEL_COVERAGE"
    )
    stages = [
        {
            "stage": stage,
            "status": (
                "complete"
                if stage == "curriculum_candidate" and broad_label_readiness
                else "blocked_label_coverage"
                if stage == "curriculum_candidate"
                else "pending_external_refinery"
            ),
            "evidence": str(out_root / "curriculum_manifest.json") if stage == "curriculum_candidate" else "",
        }
        for stage in CANONICAL_STAGES
    ]
    manifest = {
        "schema": "agentready.refinery_candidate.v1",
        "bundle_id": bundle_id,
        "generated_at": stamp,
        "task_id": task_id,
        "status": candidate_status,
        "classification": "restricted_use",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "cross_lane_import_policy": "explicit_only",
        "refinery_owner": "external training pipeline",
        "canonical_pipeline": list(CANONICAL_STAGES),
        "stages": stages,
        "artifacts": artifacts,
        "train_count": int(training_export.get("train_count") or 0),
        "heldout_count": int(training_export.get("heldout_count") or 0),
        "train_heldout_no_overlap": training_export.get("train_heldout_no_overlap") is True,
        "all_restricted_use": training_export.get("all_restricted_use") is True,
        "label_coverage": training_export.get("label_coverage") or {},
        "unsupported_labels": training_export.get("unsupported_labels") or [],
        "train_unsupported_labels": training_export.get("train_unsupported_labels") or [],
        "heldout_unsupported_labels": training_export.get("heldout_unsupported_labels") or [],
        "broad_label_readiness": broad_label_readiness,
        "final_dataset_emitted": False,
        "model_training_performed": False,
        "promotion_allowed": False,
        "required_next_receipt": "refinery_completion_receipt",
    }
    manifest_path = out_root / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    pointer_root = root / "data" / "training-library" / "30_refinery_handoff"
    pointer = {
        "schema": "agentready.refinery_candidate_pointer.v1",
        "generated_at": stamp,
        "bundle_id": bundle_id,
        "status": manifest["status"],
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "candidate_manifest": str(manifest_path),
        "final_dataset_emitted": False,
    }
    (pointer_root / "latest.json").write_text(json.dumps(pointer, indent=2), encoding="utf-8")
    return {**manifest, "candidate_manifest": str(manifest_path)}
