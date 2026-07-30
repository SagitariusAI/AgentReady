from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_data_foundry_lib.refinery_handoff import ARTIFACT_NAMES, CANONICAL_STAGES, package_refinery_candidate


def test_refinery_handoff_is_immutable_and_never_claims_final(tmp_path: Path) -> None:
    export_root = tmp_path / "exports" / "sentinel"
    export_root.mkdir(parents=True)
    for name in ARTIFACT_NAMES:
        (export_root / name).write_text(f"{name}\n", encoding="utf-8")
    training_export = {
        "output_root": "exports/sentinel",
        "train_count": 9,
        "heldout_count": 3,
        "train_heldout_no_overlap": True,
        "all_internal_only": True,
        "broad_label_readiness": True,
        "label_coverage": {"SUPPORTED_CLAIM": {"train": 9, "heldout": 3, "total": 12}},
    }

    result = package_refinery_candidate(
        tmp_path,
        training_export,
        task_id="task-1",
        generated_at="2026-07-29T22:30:00+00:00",
    )

    assert result["status"] == "CANDIDATE_READY_FOR_CANONICAL_REFINERY"
    assert result["canonical_pipeline"] == list(CANONICAL_STAGES)
    assert result["final_dataset_emitted"] is False
    assert result["promotion_allowed"] is False
    assert result["workflow_lane"] == "research"
    assert result["data_lane"] == "research"
    assert result["machinery_zone"] == "FACTORY"
    assert result["cross_lane_import_policy"] == "explicit_only"
    assert all(stage["status"] == "pending_external_refinery" for stage in result["stages"][1:])
    copied = Path(result["artifacts"][0]["path"])
    assert copied.read_text(encoding="utf-8") == f"{ARTIFACT_NAMES[0]}\n"
    assert result["artifacts"][0]["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    pointer = json.loads(
        (tmp_path / "data" / "training-library" / "30_refinery_handoff" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert pointer["final_dataset_emitted"] is False
    assert pointer["data_lane"] == "research"


def test_refinery_handoff_blocks_partial_label_coverage(tmp_path: Path) -> None:
    export_root = tmp_path / "exports" / "sentinel"
    export_root.mkdir(parents=True)
    for name in ARTIFACT_NAMES:
        (export_root / name).write_text(f"{name}\n", encoding="utf-8")
    result = package_refinery_candidate(
        tmp_path,
        {
            "output_root": "exports/sentinel",
            "train_count": 1,
            "heldout_count": 0,
            "train_heldout_no_overlap": True,
            "all_internal_only": True,
            "broad_label_readiness": False,
            "unsupported_labels": ["VAULT_CODE_CONFUSION"],
            "heldout_unsupported_labels": ["VAULT_CODE_CONFUSION"],
        },
        task_id="partial",
        generated_at="2026-07-29T22:31:00+00:00",
    )
    assert result["status"] == "CANDIDATE_BLOCKED_LABEL_COVERAGE"
    assert result["promotion_allowed"] is False
