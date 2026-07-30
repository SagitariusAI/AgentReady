# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Creator-provenance envelope + summary helpers for the Agent Data Foundry."""
from __future__ import annotations

from typing import Any

from agent_data_foundry_lib.io_jsonl import as_dict

# ---- Creator Provenance Envelope v0.1 -------------------------------------
# Unified provenance: every exported row identifies who/what produced,
# transformed, reviewed, corrected, mined, exported, or evaluated it -- humans,
# deterministic Factory code, frontier/local LLMs, hybrids. An unknown value
# stays an EXPLICIT null / "unknown" (never silently omitted); model_name is
# NEVER inferred from an agent name; human identity defaults to an internal
# pseudonymous role label; no fabricated model names/versions, reviewers, or
# approvals. Restricted-use everywhere it appears.

CREATOR_PROVENANCE_SCHEMA = "sf.creator_provenance.v0.1"
REVIEW_PROVENANCE_SCHEMA = "sf.review_provenance.v0.1"
FACTORY_CREATOR_DISPLAY = "AgentReady Factory"
FACTORY_PROVIDER = "agentready_factory"

_PROV_STAGE_KEYS = (
    "stage", "creator_type", "creator_id", "creator_display", "creator_role",
    "authority_level", "contribution_type", "provider", "model_name",
    "model_version", "runtime", "route", "timestamp", "source_task_id",
    "source_receipt_id", "source_commit", "confidence", "privacy_scope", "notes",
)


def _prov_stage(stage: str, **kw: Any) -> dict[str, Any]:
    """A provenance_chain stage with the full, consistent key set (nulls for the
    fields a stage does not assert) so manifest summaries aggregate uniformly."""
    out: dict[str, Any] = {key: None for key in _PROV_STAGE_KEYS}
    out["stage"] = stage
    out["creator_type"] = "unknown"
    out["contribution_type"] = "unknown"
    out["confidence"] = "unknown"
    out.update({k: v for k, v in kw.items() if k in out})
    return out


def _human_correction_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Explicit human/owner correction from the captured human_correction_lineage
    block OR raw record fields. Never fabricated: absent fields mean no human acted,
    so the human-specific signal honestly stays absent."""
    hcl = as_dict(row.get("human_correction_lineage"))
    owner_override = hcl.get("owner_override_reason") or row.get("owner_override_reason")
    human_correction = hcl.get("human_correction") or row.get("human_correction")
    source = str(hcl.get("correction_source") or "")
    review_decision = hcl.get("review_decision") or row.get("review_decision") or (row.get("gold_output") or {}).get("verdict")
    if owner_override:
        kind = "owner"
    elif human_correction or source == "human_review":
        kind = "human"
    elif source == "machine_adjudication" or review_decision:
        kind = "machine"
    else:
        kind = "none"
    return {
        "kind": kind,
        "owner_override": str(owner_override) if owner_override else None,
        "review_decision": str(review_decision) if review_decision else None,
    }


# Provider tokens that are NOT a real model vendor -- they name the Factory itself
# or an unknown source, so they must never be read as a frontier/local-LLM origin.
_NON_MODEL_PROVIDERS = {"agentready_factory", "agentready", "factory", "internal",
                        "deterministic", "deterministic_factory", "none", "unknown", ""}
_LOCAL_EXEC_MODES = {"local", "on_device", "offline", "edge"}


def _model_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Honest origin classification from the captured model_route_cost ONLY.
    `execution_mode: deterministic` (and a factory/internal provider) means the row
    was produced by deterministic Factory code, NOT a model -- never call that a
    frontier LLM. A real frontier/local LLM is asserted only when an explicit model
    provider/name is present; model_name is NEVER the agent name; model_version has
    no source field yet, so it stays null/unknown."""
    mrc = as_dict(row.get("model_route_cost"))
    provider = str(mrc.get("provider") or "") or None
    model_name = str(mrc.get("model_name") or "") or None
    execution_mode = str(mrc.get("execution_mode") or "").lower()
    provider_is_model = bool(provider) and provider.lower() not in _NON_MODEL_PROVIDERS
    if execution_mode == "deterministic" or (provider and not provider_is_model and not model_name):
        return {"provider": None, "model_name": None, "model_version": None,
                "creator_type": "deterministic_factory", "confidence": "explicit"}
    if model_name or provider_is_model:
        creator_type = "local_llm" if execution_mode in _LOCAL_EXEC_MODES else "frontier_llm"
        return {"provider": provider, "model_name": model_name, "model_version": None,
                "creator_type": creator_type, "confidence": "explicit" if model_name else "inferred"}
    return {"provider": None, "model_name": None, "model_version": None,
            "creator_type": "unknown", "confidence": "unknown"}


def build_creator_provenance_envelope(row: dict[str, Any], source_commit: str | None) -> dict[str, Any]:
    """Unified per-row provenance: a singular creator_provenance (the row's terminal
    producer -- the deterministic exporter), an ordered provenance_chain (origin ->
    correction -> review -> export), and review_provenance. All restricted-use."""
    receipt_id = str(row.get("source_id_hash") or row.get("fingerprint") or "") or None
    is_controlled = str(row.get("provenance_type") or "") == "CONTROLLED_CASE"
    hc = _human_correction_signal(row)
    ms = _model_signal(row)

    chain: list[dict[str, Any]] = []
    # origin stage: human-authored controlled case, or model/unknown-generated receipt
    if is_controlled:
        chain.append(_prov_stage(
            "authored", creator_type="human", creator_display="Owner", creator_role="author",
            authority_level="owner", contribution_type="authored",
            privacy_scope="internal_pseudonymous", source_receipt_id=receipt_id,
            confidence="inferred",  # inferred from provenance_type=CONTROLLED_CASE, no explicit per-row author field
        ))
    else:
        ct = ms["creator_type"]
        authority = {"deterministic_factory": "system", "frontier_llm": "agent", "local_llm": "agent"}.get(ct, "unknown")
        contribution = {"deterministic_factory": "transformed", "frontier_llm": "authored", "local_llm": "authored"}.get(ct, "unknown")
        chain.append(_prov_stage(
            "generated", creator_type=ct,
            creator_display=FACTORY_CREATOR_DISPLAY if ct == "deterministic_factory" else "unknown",
            creator_role="generator", authority_level=authority, contribution_type=contribution,
            provider=ms["provider"] or (FACTORY_PROVIDER if ct == "deterministic_factory" else None),
            model_name=ms["model_name"], model_version=ms["model_version"],
            source_receipt_id=receipt_id, confidence=ms["confidence"],
        ))

    # correction / review stage -- only when a human explicitly acted, else machine
    if hc["kind"] == "owner":
        chain.append(_prov_stage(
            "corrected", creator_type="human", creator_display="Owner", creator_role="reviewer",
            authority_level="owner", contribution_type="corrected",
            privacy_scope="internal_pseudonymous", notes=hc["owner_override"], confidence="explicit",
        ))
    elif hc["kind"] == "human":
        chain.append(_prov_stage(
            "corrected", creator_type="human", creator_display="Internal reviewer", creator_role="reviewer",
            authority_level="reviewer", contribution_type="corrected",
            privacy_scope="internal_pseudonymous", confidence="explicit",
        ))
    elif hc["kind"] == "machine":
        chain.append(_prov_stage(
            "reviewed", creator_type="deterministic_factory", creator_display=FACTORY_CREATOR_DISPLAY,
            creator_role="validator", authority_level="system", contribution_type="reviewed",
            provider=FACTORY_PROVIDER, notes=hc["review_decision"], confidence="explicit",
        ))

    # terminal export stage (always last)
    chain.append(_prov_stage(
        "exported", creator_type="deterministic_factory", creator_display=FACTORY_CREATOR_DISPLAY,
        creator_role="exporter", authority_level="system", contribution_type="exported",
        provider=FACTORY_PROVIDER, source_commit=source_commit, source_receipt_id=receipt_id,
        privacy_scope="named_internal", confidence="explicit",
    ))

    # singular creator_provenance = the terminal producer (the deterministic exporter)
    creator_provenance = {
        "schema_version": CREATOR_PROVENANCE_SCHEMA,
        "creator_type": "deterministic_factory",
        "creator_id": None,
        "creator_display": FACTORY_CREATOR_DISPLAY,
        "creator_role": "exporter",
        "authority_level": "system",
        "contribution_type": "exported",
        "provider": FACTORY_PROVIDER,
        "model_name": None,
        "model_version": None,
        "runtime": None,
        "route": None,
        "timestamp": None,
        "source_task_id": None,
        "source_receipt_id": receipt_id,
        "source_commit": source_commit,
        "confidence": "explicit",
        "privacy_scope": "named_internal",
        "notes": None,
    }

    if hc["kind"] == "owner":
        review_status = "owner_approved"
        reviewers = [{"reviewer_type": "human", "reviewer_display": "Owner", "authority_level": "owner",
                      "decision": hc["owner_override"] or hc["review_decision"], "confidence": "explicit"}]
    elif hc["kind"] == "human":
        review_status = "human_reviewed"
        reviewers = [{"reviewer_type": "human", "reviewer_display": "Internal reviewer", "authority_level": "reviewer",
                      "decision": hc["review_decision"], "confidence": "explicit"}]
    elif hc["kind"] == "machine":
        review_status = "machine_reviewed"
        reviewers = [{"reviewer_type": "deterministic_factory", "reviewer_display": FACTORY_CREATOR_DISPLAY,
                      "authority_level": "system", "decision": hc["review_decision"], "confidence": "explicit"}]
    else:
        review_status = "unreviewed"
        reviewers = []
    review_provenance = {
        "schema_version": REVIEW_PROVENANCE_SCHEMA,
        "review_status": review_status,
        "reviewers": reviewers,
    }

    return {
        "creator_provenance": creator_provenance,
        "provenance_chain": chain,
        "review_provenance": review_provenance,
    }


def summarize_provenance(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    """Manifest-level rollup of per-row provenance for producer-quality analysis:
    distributions over every contributor in the chain, plus the named counts that
    later gate curriculum trust and review authority."""
    creator_type_dist: dict[str, int] = {}
    creator_role_dist: dict[str, int] = {}
    authority_dist: dict[str, int] = {}
    contribution_dist: dict[str, int] = {}
    review_status_dist: dict[str, int] = {}
    provider_dist: dict[str, int] = {}
    model_name_dist: dict[str, int] = {}
    model_version_dist: dict[str, int] = {}
    source_commit_dist: dict[str, int] = {}
    human_rows = model_rows = factory_rows = 0
    owner_authored = owner_corrected = human_reviewed = 0
    machine_generated = factory_generated = deterministic_exported = unreviewed = 0
    owner_approved_gold = rejected = unknown_creator = unknown_model_version = 0

    def bump(dist: dict[str, int], value: Any) -> None:
        key = "null" if value is None else str(value)
        dist[key] = dist.get(key, 0) + 1

    for env in envelopes:
        chain = env.get("provenance_chain") or []
        review = env.get("review_provenance") or {}
        cp = env.get("creator_provenance") or {}
        types = {str(stage.get("creator_type")) for stage in chain}
        human_rows += int("human" in types)
        model_rows += int(bool({"frontier_llm", "local_llm"} & types))
        factory_rows += int("deterministic_factory" in types)
        for stage in chain:
            bump(creator_type_dist, stage.get("creator_type"))
            bump(creator_role_dist, stage.get("creator_role"))
            bump(authority_dist, stage.get("authority_level"))
            bump(contribution_dist, stage.get("contribution_type"))
            bump(provider_dist, stage.get("provider"))
            bump(model_name_dist, stage.get("model_name"))
            bump(model_version_dist, stage.get("model_version"))
        bump(source_commit_dist, cp.get("source_commit"))
        origin = chain[0] if chain else {}
        origin_type = str(origin.get("creator_type"))
        if origin_type == "human" and str(origin.get("authority_level")) == "owner":
            owner_authored += 1
        if origin_type in ("frontier_llm", "local_llm"):
            machine_generated += 1
        if str(origin.get("stage")) == "generated" and origin_type == "deterministic_factory":
            factory_generated += 1
        if origin_type == "unknown":
            unknown_creator += 1
        # "unknown model version" = a model/unknown origin whose version we don't know
        # (a deterministic-factory origin has no model version to be unknown about).
        if (str(origin.get("stage")) == "generated" and origin.get("model_version") is None
                and origin_type in ("frontier_llm", "local_llm", "unknown")):
            unknown_model_version += 1
        if any(s.get("stage") == "corrected" and str(s.get("authority_level")) == "owner" for s in chain):
            owner_corrected += 1
        if any(s.get("stage") == "exported" and str(s.get("creator_type")) == "deterministic_factory" for s in chain):
            deterministic_exported += 1
        status = str(review.get("review_status") or "unreviewed")
        bump(review_status_dist, status)
        owner_approved_gold += int(status == "owner_approved")
        human_reviewed += int(status in ("human_reviewed", "owner_approved"))
        unreviewed += int(status == "unreviewed")
        rejected += int(status == "rejected")

    return {
        "schema_version": "sf.creator_provenance_manifest.v0.1",
        "row_count": len(envelopes),
        "creator_type_distribution": creator_type_dist,
        "creator_role_distribution": creator_role_dist,
        "authority_level_distribution": authority_dist,
        "contribution_type_distribution": contribution_dist,
        "review_status_distribution": review_status_dist,
        "provider_distribution": provider_dist,
        "model_name_distribution": model_name_dist,
        "model_version_distribution": model_version_dist,
        "source_commit_distribution": source_commit_dist,
        "human_vs_model_vs_factory": {"human": human_rows, "model": model_rows, "deterministic_factory": factory_rows},
        "owner_authored_count": owner_authored,
        "owner_corrected_count": owner_corrected,
        "human_reviewed_count": human_reviewed,
        "machine_generated_count": machine_generated,
        "factory_generated_count": factory_generated,
        "deterministic_exported_count": deterministic_exported,
        "unreviewed_candidate_count": unreviewed,
        "owner_approved_training_gold_count": owner_approved_gold,
        "rejected_candidate_count": rejected,
        "unknown_creator_count": unknown_creator,
        "unknown_model_version_count": unknown_model_version,
    }
