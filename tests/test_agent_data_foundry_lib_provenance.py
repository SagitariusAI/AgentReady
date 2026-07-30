from __future__ import annotations

from agent_data_foundry_lib.provenance import (
    CREATOR_PROVENANCE_SCHEMA,
    _human_correction_signal,
    _model_signal,
    build_creator_provenance_envelope,
    summarize_provenance,
)


def test_envelope_terminal_producer_and_chain() -> None:
    env = build_creator_provenance_envelope({"source_id_hash": "h1"}, "commit1")
    cp = env["creator_provenance"]
    assert cp["schema_version"] == CREATOR_PROVENANCE_SCHEMA
    assert cp["creator_type"] == "deterministic_factory" and cp["creator_role"] == "exporter"
    assert cp["source_commit"] == "commit1" and cp["source_receipt_id"] == "h1"
    assert env["provenance_chain"][-1]["stage"] == "exported"
    assert env["review_provenance"]["schema_version"] == "sf.review_provenance.v0.1"


def test_model_name_not_inferred_from_agent_name() -> None:
    # an agent name on model_origin must NEVER become model_name; only model_route_cost is read
    row = {"model_origin": {"model_name": "Claude Code", "provider": "anthropic", "execution_mode": "api"}}
    ms = _model_signal(row)
    assert ms["model_name"] is None and ms["creator_type"] == "unknown"
    env = build_creator_provenance_envelope(row, "c")
    assert all(s["model_name"] != "Claude Code" for s in env["provenance_chain"])


def test_deterministic_execution_mode_is_factory_not_model() -> None:
    row = {"model_route_cost": {"provider": "agentready_factory", "execution_mode": "deterministic"}}
    assert _model_signal(row)["creator_type"] == "deterministic_factory"


def test_founder_correction_review_and_no_fabricated_approval() -> None:
    row = {"founder_override_reason": "verified push receipt"}
    env = build_creator_provenance_envelope(row, "c")
    assert env["review_provenance"]["review_status"] == "founder_approved"
    assert any(s["stage"] == "corrected" and s["authority_level"] == "founder" for s in env["provenance_chain"])
    # a row with no human signal must never fabricate founder approval
    plain = build_creator_provenance_envelope({}, "c")
    assert plain["review_provenance"]["review_status"] != "founder_approved"
    assert all(r["reviewer_display"] != "Founder" for r in plain["review_provenance"]["reviewers"])


def test_human_correction_signal_kinds() -> None:
    assert _human_correction_signal({"founder_override_reason": "x"})["kind"] == "founder"
    assert _human_correction_signal({"human_correction": "x"})["kind"] == "human"
    assert _human_correction_signal({})["kind"] == "none"


def test_summarize_provenance_counts() -> None:
    envs = [build_creator_provenance_envelope({"provenance_type": "CONTROLLED_CASE"}, "c") for _ in range(3)]
    envs += [build_creator_provenance_envelope({}, "c") for _ in range(2)]
    s = summarize_provenance(envs)
    assert s["schema_version"] == "sf.creator_provenance_manifest.v0.1" and s["row_count"] == 5
    assert s["founder_authored_count"] == 3  # controlled cases authored by founder
    assert s["model_name_distribution"].get("null", 0) >= 5  # no model names anywhere
    assert s["deterministic_exported_count"] == 5  # every row has a factory exported stage


def test_reexported_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.build_creator_provenance_envelope is build_creator_provenance_envelope
    assert adf.summarize_provenance is summarize_provenance
    assert adf.CREATOR_PROVENANCE_SCHEMA == CREATOR_PROVENANCE_SCHEMA
