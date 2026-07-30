"""Cerberus Sentinel training exporter for the Agent Data Foundry.

Phase I1 of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the export-only (NO training) Cerberus Sentinel training-set builder moved verbatim
out of agent_data_foundry.py with **no behavior change**. It builds the internal SFT /
classification / heldout-eval sets from the Factory Dojo's labeled claim-evidence
records, with a deterministic key-stable split (train and heldout never overlap),
F_QUARANTINE rows + off-target labels excluded, input text leak-scrubbed (a severe
finding drops the row), and the LogosOne curriculum + creator-provenance blocks on
every row. Historical chat segments are counted as unlabeled candidate enrichment
only -- never labeled, never a fabricated pair. Internal-only; never writes under
40_release_ready, never mutates sealed Cerberus v0.1, model_training_performed=False.

Near-leaf: imports the sibling lib modules (io_jsonl, logosone, provenance, safety_scan,
historical_chat, eval_gate for cerberus_sentinel_export_root, schemas for
SENTINEL_TRAINING_LABELS) + stdlib. The two shared central helpers -- `inhouse_dojo_root`
(the Dojo path, also used by the central Dojo builder + signal-coverage / safety / rights
reports) and the founder-pinned `_current_git_commit` -- stay central and are imported
LAZILY at call time, so there is no module-level import cycle. That lazy import is the
documented remaining coupling for the eventual Dojo-builder extraction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.dojo import inhouse_dojo_root
from agent_data_foundry_lib.eval_gate import cerberus_sentinel_export_root
from agent_data_foundry_lib.historical_chat import historical_chats_root
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    as_dict,
    jsonl_row_count,
    now_utc,
    read_json,
    read_jsonl,
    rel,
    write_json,
)
from agent_data_foundry_lib.logosone import _LOGOSONE_FAMILY, _LOGOSONE_LABEL_MAP, build_logosone_block
from agent_data_foundry_lib.paths import AGENTREADY_HOME, _current_git_commit
from agent_data_foundry_lib.provenance import build_creator_provenance_envelope, summarize_provenance
from agent_data_foundry_lib.safety_scan import _scan_source_signal_value
from agent_data_foundry_lib.schemas import SENTINEL_TRAINING_LABELS

SENTINEL_SYSTEM_PROMPT = (
    "You are the Cerberus Factory Sentinel. Given a software-delivery claim and its "
    "evidence, decide whether the claim is supported. Respond ONLY with strict JSON: "
    '{"verdict": "SAFE|BLOCK|NEEDS_HUMAN", "labels": [], "evidence": [], '
    '"risk_score": 0, "required_action": ""}. Trust evidence, not claims.'
)

_SENTINEL_RISK = {"SAFE": 10, "NEEDS_HUMAN": 50, "BLOCK": 90}


def _sentinel_verdict(row: dict[str, Any]) -> str:
    gold = as_dict(row.get("gold_output"))
    mapping = {"ALLOW": "SAFE", "HUMAN_REVIEW": "NEEDS_HUMAN", "BLOCK": "BLOCK"}
    gold_verdict = str(gold.get("verdict") or "").upper()
    if gold_verdict in mapping:
        return mapping[gold_verdict]
    row_verdict = str(row.get("verdict") or "").upper()
    if row_verdict == "SAFE":
        return "SAFE"
    if row_verdict in ("NEEDS_HUMAN", "NEEDS_REVIEW"):
        return "NEEDS_HUMAN"
    return "BLOCK"


def _sentinel_input_text(row: dict[str, Any]) -> str:
    input_view = as_dict(row.get("input_view"))
    profile = as_dict(row.get("evidence_profile"))
    align = as_dict(row.get("claim_evidence_alignment"))
    claim = str(row.get("abstracted_agent_claim") or input_view.get("claim") or "")
    return "\n".join([
        "CLAIM: " + claim,
        "CLAIM_TYPE: " + str(input_view.get("claim_type") or ""),
        "TASK_STATUS: " + str(input_view.get("task_status") or ""),
        "EVIDENCE_COUNT: " + str(profile.get("evidence_count", input_view.get("evidence_count", ""))),
        "GATE_EVIDENCE_PRESENT: " + str(profile.get("gate_evidence_present", "")),
        "PUSH_EVIDENCE_PRESENT: " + str(profile.get("push_evidence_present", "")),
        "BLOCKERS_PRESENT: " + str(profile.get("blockers_present", input_view.get("blockers_present", ""))),
        "EVIDENCE_CONTRADICTS_CLAIM: " + str(align.get("evidence_contradicts_claim", "")),
    ]).strip()


def _sentinel_target(row: dict[str, Any], verdict: str) -> dict[str, Any]:
    gold = as_dict(row.get("gold_output"))
    align = as_dict(row.get("claim_evidence_alignment"))
    evidence_required = align.get("evidence_required")
    evidence = [str(item) for item in evidence_required] if isinstance(evidence_required, list) else []
    return {
        "verdict": verdict,
        "labels": [str(row.get("incident_type"))],
        "evidence": evidence,
        "risk_score": _SENTINEL_RISK.get(verdict, 50),
        "required_action": str(gold.get("required_action") or ""),
    }


def _sentinel_heldout(key: str, heldout_pct: int) -> bool:
    """Deterministic, key-stable train/heldout assignment: the same source key is
    always on the same side, so heldout never overlaps train."""
    digest = hashlib.sha256(("cerberus-sentinel-v0.1:" + str(key)).encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 100) < max(0, min(100, int(heldout_pct)))


def _lineage_lookup(root: Path) -> dict[str, dict[str, Any]]:
    """Build a source-hash lookup from both canonical bronze ledgers."""
    lookup: dict[str, dict[str, Any]] = {}
    ledger_specs = (
        (
            root
            / "data"
            / "training-library"
            / "10_working"
            / "coordination-harvest"
            / "metadata"
            / "coordination_capture_ledger.json",
            "COORDINATION_TASK",
        ),
        (
            root
            / "data"
            / "training-library"
            / "10_working"
            / "capture-event-harvest"
            / "metadata"
            / "capture_event_ledger.json",
            "CAPTURE_EVENT",
        ),
    )
    for ledger_path, provenance_type in ledger_specs:
        ledger = read_json(ledger_path) or {}
        for source_id, value in (ledger.get("captured_sources") or {}).items():
            if not isinstance(value, dict):
                continue
            source_hash = hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()
            lookup[source_hash] = {
                "source_id": str(source_id),
                "source_id_hash": source_hash,
                "fingerprint": str(value.get("fingerprint") or ""),
                "bronze_path": str(value.get("bronze_path") or ""),
                "ledger_path": rel(root, ledger_path),
                "provenance_type": provenance_type,
            }
    return lookup


def export_cerberus_sentinel_training(root: Path | str = AGENTREADY_HOME, heldout_pct: int = 20,
                                      source_commit: str | None = None) -> dict[str, Any]:
    """Export-only (NO training). Build internal SFT / classification / heldout-eval
    sets for the Cerberus Sentinel from the internal Factory Dojo's labeled
    claim-evidence records. Deterministic split, no train/heldout overlap;
    F_QUARANTINE rows and off-target labels excluded; input text leak-scrubbed (a
    severe finding drops the row). Historical chat segments are counted as
    unlabeled candidate enrichment only -- never labeled. Internal-only; never
    writes under 40_release_ready and never mutates sealed Cerberus v0.1."""
    # inhouse_dojo_root now lives in the dojo.py leaf (imported at module level, Phase J1).
    # _current_git_commit now lives in the paths leaf (Phase N), imported at module level --
    # the last lazy back-import into agent_data_foundry is gone.
    root = Path(root)
    out_dir = cerberus_sentinel_export_root(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    dojo_rows = read_jsonl(inhouse_dojo_root(root) / "factory_dojo_internal.jsonl")
    lineage_lookup = _lineage_lookup(root)
    commit = source_commit if source_commit is not None else _current_git_commit(root)
    provenance_envelopes: list[dict[str, Any]] = []

    sft_train: list[dict[str, Any]] = []
    classification_train: list[dict[str, Any]] = []
    heldout_eval: list[dict[str, Any]] = []
    excluded = {"quarantine": 0, "off_target_label": 0, "missing_fields": 0, "leak": 0}
    label_counts: dict[str, dict[str, int]] = {"train": {}, "heldout": {}}
    label_provenance: dict[str, dict[str, int]] = {}
    rights_counts: dict[str, int] = {}
    leak_scrubbed = 0
    export_allowed_seen = 0
    sale_allowed_seen = 0
    train_keys: set[str] = set()
    heldout_keys: set[str] = set()
    lineage_rows: list[dict[str, Any]] = []
    # LogosOne curriculum distributions.
    logosone_count = 0
    sign_dist: dict[str, int] = {}
    grade_dist: dict[str, int] = {}
    anchor_dist: dict[str, int] = {}
    spine_dist: dict[str, int] = {}
    pair_id_counts: dict[str, int] = {}
    paired_rows = 0
    unpaired_rows = 0

    # Pre-pass: which signed-pair families actually have both a + and a - example,
    # so pair_status is honest (no fabricated positive counterexamples).
    family_signs: dict[str, set[str]] = {}
    for row in dojo_rows:
        if str((row.get("data_rights") or {}).get("grade")) == "F_QUARANTINE":
            continue
        inc = str(row.get("incident_type") or "")
        if inc in SENTINEL_TRAINING_LABELS:
            family_signs.setdefault(_LOGOSONE_FAMILY[inc], set()).add(_LOGOSONE_LABEL_MAP[inc][0])
    pair_status_by_family = {family: ("paired" if {"+", "-"} <= signs else "unpaired") for family, signs in family_signs.items()}

    for row in dojo_rows:
        rights = as_dict(row.get("data_rights"))
        if str(rights.get("grade")) == "F_QUARANTINE":
            excluded["quarantine"] += 1
            continue
        incident = str(row.get("incident_type") or "")
        if incident not in SENTINEL_TRAINING_LABELS:
            excluded["off_target_label"] += 1
            continue
        input_text = _sentinel_input_text(row)
        if not input_text:
            excluded["missing_fields"] += 1
            continue
        safe_text, _findings, redacted, severe = _scan_source_signal_value(input_text)
        if severe:
            excluded["leak"] += 1
            continue
        if redacted:
            leak_scrubbed += 1
        input_text = safe_text

        if rights.get("export_allowed"):
            export_allowed_seen += 1
        if rights.get("commercial_sale_allowed"):
            sale_allowed_seen += 1

        verdict = _sentinel_verdict(row)
        target = _sentinel_target(row, verdict)
        key = str(row.get("source_id_hash") or row.get("fingerprint") or input_text)
        lineage = {
            "source_pool": "factory_dojo",
            "source_id_hash": str(row.get("source_id_hash") or ""),
            "fingerprint": str(row.get("fingerprint") or ""),
            "incident_type": incident,
            "provenance_type": str(row.get("provenance_type") or "NATURAL_RECEIPT"),
            "data_rights_grade": str(rights.get("grade") or ""),
            "source_lineage": as_dict(row.get("source_lineage"))
            or lineage_lookup.get(str(row.get("source_id_hash") or ""), {}),
        }
        rights_counts[lineage["data_rights_grade"]] = rights_counts.get(lineage["data_rights_grade"], 0) + 1
        provenance_type = lineage["provenance_type"]
        label_provenance.setdefault(incident, {})[provenance_type] = (
            label_provenance.setdefault(incident, {}).get(provenance_type, 0) + 1
        )

        logosone = build_logosone_block(row, incident, pair_status_by_family)
        logosone_count += 1
        sign_dist[logosone["sign"]] = sign_dist.get(logosone["sign"], 0) + 1
        grade_dist[logosone["grade"]] = grade_dist.get(logosone["grade"], 0) + 1
        for anchor in logosone["anchors"]:
            anchor_dist[anchor] = anchor_dist.get(anchor, 0) + 1
        spine_key = " -> ".join(logosone["workflow_spine"])
        spine_dist[spine_key] = spine_dist.get(spine_key, 0) + 1
        pair_id_counts[logosone["pair_id"]] = pair_id_counts.get(logosone["pair_id"], 0) + 1
        if logosone["pair_status"] == "paired":
            paired_rows += 1
        else:
            unpaired_rows += 1

        provenance = build_creator_provenance_envelope(row, commit)
        provenance_envelopes.append(provenance)

        if _sentinel_heldout(key, heldout_pct):
            label_counts["heldout"][incident] = label_counts["heldout"].get(incident, 0) + 1
            heldout_keys.add(key)
            heldout_eval.append({"input": input_text, "label": incident, "expected": target, "logosone": logosone, "metadata": lineage, **provenance})
            split_name = "heldout"
        else:
            label_counts["train"][incident] = label_counts["train"].get(incident, 0) + 1
            train_keys.add(key)
            sft_train.append({
                "messages": [
                    {"role": "system", "content": SENTINEL_SYSTEM_PROMPT},
                    {"role": "user", "content": input_text},
                    {"role": "assistant", "content": json.dumps(target, ensure_ascii=False, sort_keys=True)},
                ],
                "logosone": logosone,
                "metadata": lineage,
                **provenance,
            })
            classification_train.append({"input": input_text, "label": incident, "verdict": verdict, "logosone": logosone, "metadata": lineage, **provenance})
            split_name = "train"
        lineage_rows.append(
            {
                "source_id_hash": lineage["source_id_hash"],
                "fingerprint": lineage["fingerprint"],
                "split": split_name,
                "source_lineage": lineage["source_lineage"],
            }
        )

    # Historical chat segments: counted as unlabeled candidate enrichment only.
    hist_path = historical_chats_root(root) / "historical_chat_segments.jsonl"
    hist_segments = read_jsonl(hist_path) if hist_path.exists() else []
    historical_candidate_unlabeled = sum(1 for s in hist_segments if not s.get("quarantined"))

    sft_path = out_dir / "sft_train.jsonl"
    cls_path = out_dir / "classification_train.jsonl"
    eval_path = out_dir / "heldout_eval.jsonl"
    lineage_path = out_dir / "lineage_manifest.json"
    append_jsonl(sft_path, sft_train)
    append_jsonl(cls_path, classification_train)
    append_jsonl(eval_path, heldout_eval)
    write_json(
        lineage_path,
        {
            "schema_version": "sf.dojo_training_export.lineage.v1",
            "generated_at": now_utc(),
            "row_count": len(lineage_rows),
            "rows": lineage_rows,
        },
    )

    readback = {
        "sft_train": jsonl_row_count(sft_path),
        "classification_train": jsonl_row_count(cls_path),
        "heldout_eval": jsonl_row_count(eval_path),
    }
    readback_matches = (
        readback["sft_train"] == len(sft_train)
        and readback["classification_train"] == len(classification_train)
        and readback["heldout_eval"] == len(heldout_eval)
    )
    no_overlap = train_keys.isdisjoint(heldout_keys)
    all_internal_only = export_allowed_seen == 0 and sale_allowed_seen == 0
    label_coverage = {
        label: {
            "train": label_counts["train"].get(label, 0),
            "heldout": label_counts["heldout"].get(label, 0),
            "total": label_counts["train"].get(label, 0) + label_counts["heldout"].get(label, 0),
            "provenance": label_provenance.get(label, {}),
        }
        for label in SENTINEL_TRAINING_LABELS
    }
    unsupported_labels = [label for label, support in label_coverage.items() if support["total"] == 0]
    train_unsupported_labels = [label for label, support in label_coverage.items() if support["train"] == 0]
    heldout_unsupported_labels = [label for label, support in label_coverage.items() if support["heldout"] == 0]
    broad_label_readiness = not unsupported_labels and not train_unsupported_labels and not heldout_unsupported_labels
    readiness_status = "INHOUSE_READY" if broad_label_readiness else "INHOUSE_PARTIAL_LABEL_COVERAGE"

    curriculum_summary = {
        "curriculum": "LogosOne",
        "schema_version": "sf.logosone_curriculum.v0.1",
        "rights_scope": "internal_only",
        "rows_with_logosone": logosone_count,
        "sign_distribution": sign_dist,
        "grade_distribution": grade_dist,
        "anchor_distribution": anchor_dist,
        "workflow_spine_distribution": spine_dist,
        "pair_id_count": len(pair_id_counts),
        "pair_id_counts": pair_id_counts,
        "paired_rows": paired_rows,
        "unpaired_rows": unpaired_rows,
        "paired_families": [family for family, status in pair_status_by_family.items() if status == "paired"],
        "unpaired_families": [family for family, status in pair_status_by_family.items() if status == "unpaired"],
    }

    provenance_summary = summarize_provenance(provenance_envelopes)

    export_manifest = {
        "schema_version": "sf.dojo_training_export.cerberus_sentinel.v0.1",
        "dataset_id": "cerberus-sentinel-v0.1",
        "status": readiness_status,
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "generated_at": now_utc(),
        "curriculum": "LogosOne",
        "training_target": "claim_evidence_alignment",
        "training_labels": list(SENTINEL_TRAINING_LABELS),
        "sources": {"primary": "factory_dojo_internal", "historical_candidate_unlabeled": historical_candidate_unlabeled},
        "rows_seen": len(dojo_rows),
        "train_count": len(sft_train),
        "heldout_count": len(heldout_eval),
        "label_distribution": label_counts,
        "label_coverage": label_coverage,
        "unsupported_labels": unsupported_labels,
        "train_unsupported_labels": train_unsupported_labels,
        "heldout_unsupported_labels": heldout_unsupported_labels,
        "broad_label_readiness": broad_label_readiness,
        "rights_distribution": rights_counts,
        "logosone_curriculum": curriculum_summary,
        "creator_provenance": provenance_summary,
        "source_commit": commit,
        "excluded": excluded,
        "leak_scrubbed_rows": leak_scrubbed,
        "readback": readback,
        "lineage_manifest_path": rel(root, lineage_path),
        "lineage_row_count": len(lineage_rows),
        "readback_matches": readback_matches,
        "train_heldout_overlap": not no_overlap,
        "all_internal_only": all_internal_only,
        "external_release_allowed": False,
        "commercial_sale_allowed": False,
        "model_training_performed": False,
    }
    write_json(out_dir / "export_manifest.json", export_manifest)

    write_json(out_dir / "provenance_manifest.json", {
        "generated_at": now_utc(),
        "dataset_id": "cerberus-sentinel-v0.1",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "note": "Creator provenance is internal-only; mandatory for curriculum trust, review authority, and producer-quality measurement. Unknown values are explicit; model_name is never inferred from an agent name; human identity is internal-pseudonymous.",
        "source_commit": commit,
        "all_internal_only": all_internal_only,
        **provenance_summary,
        "model_training_performed": False,
    })

    write_json(out_dir / "curriculum_manifest.json", {
        "schema_version": "sf.logosone_curriculum_manifest.v0.1",
        "generated_at": now_utc(),
        "dataset_id": "cerberus-sentinel-v0.1",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "note": "LogosOne is internal/proprietary curriculum metadata; never externalized.",
        "rows_seen": len(dojo_rows),
        "excluded": excluded,
        "all_internal_only": all_internal_only,
        "creator_provenance": provenance_summary,
        **curriculum_summary,
    })

    rights_report = {
        "schema_version": "sf.dojo_training_export.rights.v0.1",
        "generated_at": now_utc(),
        "curriculum": "LogosOne",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "record_count": len(sft_train) + len(heldout_eval),
        "rights_distribution": rights_counts,
        "export_allowed_rows": export_allowed_seen,
        "commercial_sale_rows": sale_allowed_seen,
        "quarantine_excluded": excluded["quarantine"],
        "all_internal_only": all_internal_only,
        "creator_provenance": provenance_summary,
    }
    write_json(out_dir / "rights_report.json", rights_report)

    split_manifest = {
        "schema_version": "sf.dojo_training_export.split.v0.1",
        "generated_at": now_utc(),
        "curriculum": "LogosOne",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "method": "sha256(source_id_hash) % 100 < heldout_pct (key-stable, deterministic)",
        "heldout_pct": int(heldout_pct),
        "train_count": len(sft_train),
        "heldout_count": len(heldout_eval),
        "train_label_distribution": label_counts["train"],
        "heldout_label_distribution": label_counts["heldout"],
        "label_coverage": label_coverage,
        "unsupported_labels": unsupported_labels,
        "train_unsupported_labels": train_unsupported_labels,
        "heldout_unsupported_labels": heldout_unsupported_labels,
        "broad_label_readiness": broad_label_readiness,
        "train_heldout_overlap": not no_overlap,
        "creator_provenance": provenance_summary,
    }
    write_json(out_dir / "split_manifest.json", split_manifest)

    return {
        "status": readiness_status,
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "train_count": len(sft_train),
        "heldout_count": len(heldout_eval),
        "lineage_manifest_path": rel(root, lineage_path),
        "lineage_row_count": len(lineage_rows),
        "label_coverage": label_coverage,
        "unsupported_labels": unsupported_labels,
        "train_unsupported_labels": train_unsupported_labels,
        "heldout_unsupported_labels": heldout_unsupported_labels,
        "broad_label_readiness": broad_label_readiness,
        "rows_with_logosone": logosone_count,
        "sign_distribution": sign_dist,
        "grade_distribution": grade_dist,
        "paired_rows": paired_rows,
        "unpaired_rows": unpaired_rows,
        "excluded": excluded,
        "readback_matches": readback_matches,
        "train_heldout_no_overlap": no_overlap,
        "all_internal_only": all_internal_only,
        "source_commit": commit,
        "provenance_summary": provenance_summary,
        "model_training_performed": False,
        "output_root": rel(root, out_dir),
    }
