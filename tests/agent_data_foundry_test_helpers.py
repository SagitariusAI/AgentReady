# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Shared builders/helpers/constants for the split agent_data_foundry test suite (verbatim move).

Anything used by more than one focused test module (or by a shared helper) lives here so the
focused modules import it instead of duplicating it."""

import json
from pathlib import Path

_REALISH_GH_TOKEN = "ghp_" + "ab" * 18


_CLAIM_TYPE_BY_LABEL = {
    "SUPPORTED_CLAIM": "receipt_state_promotion",
    "COMPLETION_BY_DEFERRAL": "completion_complete",
    "UNSUPPORTED_PROMOTION": "promotion_complete",
    "MISDIRECTED_VERIFICATION": "verification_complete",
    "VAULT_CODE_CONFUSION": "implementation_complete",
    "CLAIM_WITHOUT_EVIDENCE": "receipt_state_promotion",
}


_RELEASE_DIR = Path("data") / "training-library" / "40_release_ready" / "claim_evidence-claim-evidence-eval-v0.1.0"


_DATASET_DIR = Path("data") / "training-library" / "30_curated" / "internal" / "factory-dataset"


_SAMPLE_DIFF = """diff --git a/tests/test_x.py b/tests/test_x.py
index 111..222 100644
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,5 +1,7 @@
 import pytest
-    assert old_value == 1
+    assert new_value == 2
+    assert helper() is True
+    mocker.patch("mod.fn")
+    @pytest.mark.skipif(True, reason="x")
+    @pytest.mark.xfail(reason="known")
"""


def write_receipt(root: Path, name: str, payload: dict) -> Path:
    path = root / "coordination" / "DemoRepo-1234" / "task-reports" / name / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_task(coordination_root: Path, repo_key: str, task_id: str, payload: dict) -> Path:
    path = coordination_root / repo_key / "tasks" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def base_receipt(**overrides: object) -> dict:
    payload = {
        "schema_version": 2,
        "receipt_id": "receipt-001",
        "generated_utc": "2026-06-12T00:00:00+00:00",
        "repo": r"D:\DemoRepo",
        "task_id": "task-001",
        "agent": "codex",
        "artifact_type": "execution_trace",
        "workflow_lane": "research",
        "workflow_lane_source": "explicit",
        "collection_scope": "repo_change",
        "collection_purpose": "training",
        "data_classification": "internal",
        "retention_class": "training_candidate_review",
        "training_value": "high",
        "work_product_policy": "company_owned_review_before_training",
        "dataset_format_target": "tool_use_jsonl",
        "future_model_should_learn": "Use calibrated receipts as training candidates only after curation gates pass.",
        "intent": "Implement a test fixture.",
        "summary": "A strong receipt suitable for tool-use export.",
        "outcome": "The change was implemented and verified.",
        "confidence": 91,
        "commands_run": ["pytest tests/test_agent_data_foundry.py"],
        "paths_touched": [r"D:\DemoRepo\src\demo.py"],
        "evidence": [{"path": r"D:\DemoRepo\src\demo.py", "status": "pass", "meaning": "test evidence"}],
        "changes_made": ["Created a durable export."],
        "risks": ["No known risk."],
        "next_actions": ["Use the exported row."],
        "dataset_labels": ["tool-use"],
        "quality": {"passed": True, "score": 94, "grade": "A"},
    }
    payload.update(overrides)
    return payload


def base_task(**overrides: object) -> dict:
    payload = {
        "id": "task-001",
        "repo_root": r"D:\DemoRepo",
        "title": "Deliver governed production slice",
        "status": "completed",
        "agent": "codex",
        "workflow_lane": "research",
        "workflow_lane_source": "explicit",
        "summary": "Raw agent summary with implementation particulars that should not appear in product rows.",
        "paths": "src/demo.py,tests/test_demo.py",
        "branch": "agent/codex/demo",
        "worktree": r"C:\Factory\worktrees\DemoRepo\task-001",
        "created_at": "2026-06-15T01:00:00",
        "updated_at": "2026-06-15T02:00:00",
        "evidence": [
            r"C:\Factory\reports\release-scorecard\latest.md",
            "git push origin agent/codex/demo",
        ],
        "blockers": [],
        "next_actions": [],
    }
    payload.update(overrides)
    return payload


def _split_gold_row(idx: int, label: str, provenance: str, verdict: str, required_action: str) -> dict:
    safe = verdict == "SAFE"
    blockers = label == "COMPLETION_BY_DEFERRAL"
    claim_type = _CLAIM_TYPE_BY_LABEL.get(label, "receipt_state_promotion")
    evidence_profile = {
        "evidence_count": 1,
        "blockers_present": blockers,
        "gate_evidence_present": safe,
        "push_evidence_present": safe,
    }
    return {
        "fingerprint": f"fp-{label}-{provenance}-{idx:04d}",
        "incident_type": label,
        "provenance_type": provenance,
        "verdict": verdict,
        "release_eligible": True,
        "input_view": {"claim": "controlled or natural claim", "claim_type": claim_type, "evidence_count": 1, "blockers_present": blockers},
        "evidence_profile": evidence_profile,
        "abstracted_agent_claim": "claim",
        "gold_output": {"verdict": verdict, "required_action": required_action, "model_should_learn": "lesson"},
        "controlled_case_family": label if provenance == "CONTROLLED_CASE" else None,
    }


def _write_split_corpus(tmp_path: Path) -> None:
    rows: list[dict] = []
    idx = 0

    def add(label: str, provenance: str, count: int, verdict: str, action: str) -> None:
        nonlocal idx
        for _ in range(count):
            idx += 1
            rows.append(_split_gold_row(idx, label, provenance, verdict, action))

    # Natural-majority mixed corpus (natural 65 / controlled 41), all six labels.
    add("CLAIM_WITHOUT_EVIDENCE", "NATURAL_RECEIPT", 30, "BLOCK", "REJECT_PROMOTION")
    add("SUPPORTED_CLAIM", "NATURAL_RECEIPT", 20, "SAFE", "ALLOW_PROMOTION")
    add("SUPPORTED_CLAIM", "CONTROLLED_CASE", 5, "SAFE", "ALLOW_PROMOTION")
    add("COMPLETION_BY_DEFERRAL", "NATURAL_RECEIPT", 15, "BLOCK", "REJECT_PROMOTION")
    add("MISDIRECTED_VERIFICATION", "CONTROLLED_CASE", 12, "BLOCK", "REJECT_PROMOTION")
    add("UNSUPPORTED_PROMOTION", "CONTROLLED_CASE", 12, "BLOCK", "REJECT_PROMOTION")
    add("VAULT_CODE_CONFUSION", "CONTROLLED_CASE", 12, "BLOCK", "REJECT_PROMOTION")
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _write_dataset_gold(tmp_path: Path) -> Path:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        # high-value internal (no provenance/commercial_safety) -> grade A, HIGH, kept internal
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-internal", "verdict": "BLOCK", "agent": "codex"},
        # CRITICAL, provider-neutral controlled, release-eligible -> grade C, CRITICAL, export false
        {
            "incident_type": "MISDIRECTED_VERIFICATION", "fingerprint": "fp-critical",
            "verdict": "BLOCK", "provenance_type": "CONTROLLED_CASE", "release_eligible": True,
            "commercial_safety": {"provider_neutral": True, "contains_raw_provider_output": False, "release_eligible": True},
        },
        # quarantine (secrets) -> excluded
        {
            "incident_type": "SUPPORTED_CLAIM", "fingerprint": "fp-quarantine",
            "commercial_safety": {"provider_neutral": False, "contains_secrets": True},
        },
    ]
    gold.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return gold


def _signals(**over):
    base = {
        "schema_version": "sf.source_signals.v0.1",
        "paths_touched": [], "changed_file_count": 0, "commands_run": [],
        "command_surfaces": [], "command_exit_codes": [], "test_commands": [],
        "test_command_present": False, "test_files_touched": [], "protected_path_touches": [],
    }
    base.update(over)
    return base
