# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from agent_data_foundry_test_helpers import (
    _signals,
)

from agent_data_foundry import (
    build_human_correction_lineage,
    build_model_route_cost,
    build_signal_coverage,
    build_tool_call_trajectory,
    gold_coordination_row,
    harvest_source_signals,
)


def test_tool_trajectory_full_record_is_present() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "available_tools": ["agent-tool-router", "pytest", "ruff"],
        "selected_tools": ["ruff", "pytest"],
        "commands_run": ["ruff check src", "pytest -q"],
        "evidence": [{"path": "x", "status": "pass"}],
        "quality": {"checks": [{"name": "lint", "ok": True}, {"name": "tests", "ok": False}]},
        "skipped_relevant_tools": ["mypy"],
        "reason_for_tool_choice": "Lint then test before commit.",
    }
    block = build_tool_call_trajectory(record)
    assert block["schema_version"] == "sf.tool_call_trajectory.v0.1"
    assert block["trajectory_source"] == "tool_record"
    assert block["selected_tools"] == ["ruff", "pytest"]
    assert block["tool_sequence"] == ["ruff", "pytest"]  # from selected_tools
    assert block["tool_inputs_present"] is True
    assert block["tool_outputs_present"] is True
    assert "tests" in block["failed_tools"]  # failed quality check
    assert block["skipped_relevant_tools"] == ["mypy"]
    record["tool_call_trajectory"] = block
    fam = build_signal_coverage(record)["families"]["tool_call_trajectory"]
    assert fam["status"] == "present"  # all future fields captured


def test_tool_trajectory_commands_only_is_command_receipt() -> None:
    record = {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "source_signals": {"commands_run": ["agent-ci-local", "git push origin main"]}}
    block = build_tool_call_trajectory(record)
    assert block["trajectory_source"] == "command_receipt"  # no explicit tools -> crude command map
    assert block["available_tools"] == []  # never fabricated
    assert block["selected_tools"] == []
    assert block["tool_sequence"] == ["agent-ci-local", "git"]  # command surfaces in order
    assert block["tool_inputs_present"] is True  # commands carried args
    record["tool_call_trajectory"] = block
    fam = build_signal_coverage(record)["families"]["tool_call_trajectory"]
    assert fam["status"] == "partial"  # commands exist but not the full trajectory


def test_tool_trajectory_missing_when_no_tools_or_commands() -> None:
    block = build_tool_call_trajectory({"incident_type": "SUPPORTED_CLAIM"})
    assert block["trajectory_source"] == "missing"
    assert block["tool_sequence"] == []
    assert block["available_tools"] == [] and block["selected_tools"] == []
    assert block["tool_inputs_present"] is False and block["tool_outputs_present"] is False
    assert block["reason_for_tool_choice"] is None


def test_harvest_captures_tool_lists() -> None:
    sig = harvest_source_signals({
        "repo": r"C:\Factory",
        "commands_run": ["ruff check src", "pytest -q"],
        "selected_tools": ["ruff", "pytest"],
        "available_tools": ["ruff", "pytest", "mypy"],
    })
    assert sig["selected_tools"] == ["ruff", "pytest"]
    assert sig["available_tools"] == ["ruff", "pytest", "mypy"]
    assert sig["commands_run"] == ["ruff check src", "pytest -q"]


def test_tool_trajectory_reads_tools_from_source_signals() -> None:
    # Tools propagated onto the task -> harvested into source_signals -> Dataset.
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "source_signals": _signals(commands_run=["pytest -q"], selected_tools=["pytest"], available_tools=["pytest", "ruff"]),
    }
    block = build_tool_call_trajectory(record)
    assert block["trajectory_source"] == "tool_record"  # explicit tools present
    assert block["selected_tools"] == ["pytest"]
    assert block["available_tools"] == ["pytest", "ruff"]
    assert block["tool_sequence"] == ["pytest"]  # from selected_tools
    record["tool_call_trajectory"] = block
    fam = build_signal_coverage(record)["families"]["tool_call_trajectory"]
    assert fam["status"] == "partial"


def test_tool_trajectory_marks_failed_tools_from_evidence() -> None:
    record = {
        "commands_run": ["agent-release-scorecard"],
        "evidence": [{"path": "reports/scorecard.md", "status": "FAIL", "meaning": "scorecard failed"}],
    }
    block = build_tool_call_trajectory(record)
    assert block["failed_tools"] == ["reports/scorecard.md"]
    assert block["tool_outputs_present"] is True


def test_correction_lineage_machine_adjudication_is_partial() -> None:
    record = {
        "incident_type": "UNSUPPORTED_PROMOTION",
        "verdict": "BLOCK",
        "abstracted_agent_claim": "Agent claimed the artifact is release-ready.",
        "claim_evidence_alignment": {"evidence_contradicts_claim": True, "contradiction_type": "UNSUPPORTED_PROMOTION"},
        "state_transition": {"artifact_state_approved": "NEEDS_REVIEW", "promotion_allowed": False},
        "gold_output": {"verdict": "BLOCK", "required_action": "REJECT_PROMOTION", "model_should_learn": "Do not promote without evidence."},
    }
    block = build_human_correction_lineage(record)
    assert block["schema_version"] == "sf.human_correction_lineage.v0.1"
    assert block["correction_source"] == "machine_adjudication"
    assert block["review_decision"] == "BLOCK"
    assert block["correction_applied"] is True
    assert block["evidence_contradicts_claim"] is True
    assert block["future_rule"] == "Do not promote without evidence."
    # Human-specific fields stay absent -- no human corrected this, the sentinel did.
    assert block["owner_override_reason"] is None
    assert block["human_correction_present"] is False
    record["human_correction_lineage"] = block
    fam = build_signal_coverage(record)["families"]["human_correction_lineage"]
    assert fam["status"] == "partial"  # review_decision + correction_applied, not the human fields


def test_correction_lineage_safe_claim_has_no_correction() -> None:
    record = {
        "incident_type": "SUPPORTED_CLAIM", "verdict": "SAFE",
        "gold_output": {"verdict": "ALLOW", "required_action": "ALLOW_PROMOTION", "model_should_learn": "Accept evidence-backed claims."},
        "state_transition": {"artifact_state_approved": "VERIFIED", "promotion_allowed": True},
    }
    block = build_human_correction_lineage(record)
    assert block["correction_source"] == "machine_adjudication"
    assert block["correction_applied"] is False  # clean ALLOW -> nothing corrected
    assert block["review_decision"] == "ALLOW"


def test_correction_lineage_owner_override_is_present() -> None:
    record = {
        "verdict": "BLOCK",
        "gold_output": {"verdict": "BLOCK", "required_action": "REJECT_PROMOTION", "model_should_learn": "x"},
        "owner_override_reason": "Owner rejected the release: scorecard WARN unaddressed.",
        "claim_evidence_alignment": {"evidence_contradicts_claim": True},
    }
    block = build_human_correction_lineage(record)
    assert block["correction_source"] == "owner_override"
    assert block["human_correction_present"] is True
    assert "scorecard" in block["owner_override_reason"]
    record["human_correction_lineage"] = block
    fam = build_signal_coverage(record)["families"]["human_correction_lineage"]
    assert fam["status"] == "present"  # review_decision + correction_applied + human_correction + owner_override_reason


def test_correction_lineage_missing_without_claim_evidence() -> None:
    block = build_human_correction_lineage({"incident_type": "X"})
    assert block["correction_source"] == "none"
    assert block["review_decision"] is None
    assert block["human_correction_present"] is False
    fam = build_signal_coverage({"incident_type": "X", "human_correction_lineage": block})["families"]["human_correction_lineage"]
    assert fam["status"] == "missing"


def test_gold_row_carries_owner_override_to_correction_source() -> None:
    task = {
        "id": "t", "status": "handoff", "title": "x", "blockers": [],
        "owner_override_reason": "Owner rejected the release: scorecard WARN unaddressed.",
        "future_rule": "Never claim release-ready with an unaddressed WARN.",
        "correction_applied": True,
    }
    row = gold_coordination_row("sid", "fp", task)
    assert row["owner_override_reason"] == task["owner_override_reason"]
    block = build_human_correction_lineage(row)
    assert block["correction_source"] == "owner_override"
    assert block["future_rule"] == task["future_rule"]  # explicit rule wins
    assert block["human_correction_present"] is True
    fam = build_signal_coverage({**row, "human_correction_lineage": block})["families"]["human_correction_lineage"]
    assert fam["status"] == "present"  # review_decision + correction_applied + human_correction + owner_override


def test_human_correction_without_owner_is_human_review() -> None:
    record = {
        "verdict": "BLOCK",
        "gold_output": {"verdict": "BLOCK", "required_action": "REJECT_PROMOTION", "model_should_learn": "x"},
        "human_correction": "Reviewer flagged a missing regression test.",
        "downstream_defect": "prod regression in auth",
    }
    block = build_human_correction_lineage(record)
    assert block["correction_source"] == "human_review"
    assert block["human_correction_present"] is True
    assert block["downstream_defect"] == "prod regression in auth"


def test_gold_row_without_human_field_stays_machine() -> None:
    task = {"id": "t2", "status": "handoff", "title": "y", "blockers": []}
    row = gold_coordination_row("sid", "fp", task)
    assert "owner_override_reason" not in row  # never inferred from a normal task
    assert "human_correction" not in row
    block = build_human_correction_lineage(row)
    assert block["correction_source"] == "machine_adjudication"


def test_model_route_cost_from_model_origin_is_partial() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE", "agent": "claude",
        "model_origin": {"provider": "anthropic", "model_name": "claude", "execution_mode": "api"},
    }
    block = build_model_route_cost(record)
    assert block["schema_version"] == "sf.model_route_cost.v0.1"
    assert block["provider"] == "anthropic"
    assert block["execution_mode"] == "api"
    assert block["cost_source"] == "model_origin"
    # model_origin.model_name is the AGENT name -> not used; stays null.
    assert block["model_name"] is None
    assert block["token_input"] is None and block["api_cost"] is None
    assert block["estimated"] is False
    record["model_route_cost"] = block
    fam = build_signal_coverage(record)["families"]["model_route_cost"]
    assert fam["status"] == "partial"  # provider known, cost unknown


def test_model_route_cost_uses_explicit_cost_fields() -> None:
    record = {
        "model_origin": {"provider": "anthropic", "execution_mode": "api"},
        "model_route": {
            "model_name": "claude-opus-4-8", "route": "fast",
            "token_input": 1200, "token_output": 350, "api_cost": 0.04, "latency_seconds": 2.5,
        },
    }
    block = build_model_route_cost(record)
    assert block["cost_source"] == "router"
    assert block["model_name"] == "claude-opus-4-8"  # explicit model name allowed
    assert block["route"] == "fast"
    assert block["token_input"] == 1200 and block["token_output"] == 350
    assert block["api_cost"] == 0.04 and block["latency_seconds"] == 2.5
    record["model_route_cost"] = block
    fam = build_signal_coverage(record)["families"]["model_route_cost"]
    assert fam["status"] == "present"  # all future fields captured


def test_model_route_cost_never_uses_agent_as_model_name() -> None:
    block = build_model_route_cost({"agent": "codex", "model_origin": {"provider": "openai", "model_name": "codex", "execution_mode": "api"}})
    assert block["provider"] == "openai"
    assert block["model_name"] is None  # the agent name is not the model name


def test_model_route_cost_missing_and_no_estimation() -> None:
    block = build_model_route_cost({"incident_type": "X", "summary": "a" * 5000})
    assert block["cost_source"] == "missing"
    assert block["provider"] is None and block["model_name"] is None
    assert block["token_input"] is None  # never inferred from character length
    assert block["estimated"] is False
