"""Internal Factory Dojo builder + signal-coverage / source-signal-safety reports.

The internal-only Dojo export and its instrumentation reports: ``build_inhouse_dojo`` grades every
labeled claim-evidence record for data_need / data_rights, attaches source-signal capture +
diff-test integrity + tool-call trajectory, computes signal coverage and human-correction lineage
and model-route cost, and writes the internal Dojo JSONL + reports (never under 40_release_ready,
never mutating sealed Cerberus v0.1, historical segments stay unlabeled candidates). The
signal-coverage families (``SIGNAL_COVERAGE_FAMILIES`` / ``SIGNAL_COVERAGE_FAMILY_FIELDS``) and the
``signal_coverage_report`` / ``source_signal_safety_report`` wrappers live here.

Clean leaf: composes the Dojo path (``dojo.inhouse_dojo_root``), the Gold corpus (``gold_corpus``),
the rights inference (``rights``), the source-signal capture + safety scanners
(``source_signals`` / ``safety_scan``), ``io_jsonl``, and the ``paths`` foundation -- no back-import
to agent_data_foundry. The Dojo output files, row counts, coverage/rights/safety reports, schema
strings, and the no-fabricated-labels contract are preserved byte-for-byte from the pre-split module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.dojo import inhouse_dojo_root
from agent_data_foundry_lib.gold_corpus import gold_jsonl_path
from agent_data_foundry_lib.io_jsonl import append_jsonl, as_dict, now_utc, read_jsonl, rel, sha256_file, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME, report_data_foundry_path
from agent_data_foundry_lib.rights import (
    INCIDENT_NEED_MAP,
    infer_data_need_from_incident,
    infer_data_rights_from_record,
    infer_model_origin_from_record,
    quarantine_data_rights_for_signal,
    validate_data_need,
    validate_data_rights,
)
from agent_data_foundry_lib.safety_scan import scan_source_signals
from agent_data_foundry_lib.source_signals import (
    build_diff_test_integrity,
    build_tool_call_trajectory,
    strip_diff_text_from_row,
)

_CLEAN_OUTCOME = "PASS"

SIGNAL_COVERAGE_FAMILIES = [
    "claim_target_alignment",
    "tool_call_trajectory",
    "diff_test_integrity",
    "runtime_build_smoke",
    "human_correction_lineage",
    "model_route_cost",
    "artifact_lifecycle_lineage",
]

# family -> (current "look for" fields, required future-instrumentation fields).
# Dotted names (e.g. "quality.checks") are nested lookups.
SIGNAL_COVERAGE_FAMILY_FIELDS = {
    "claim_target_alignment": (
        ["claim_evidence_alignment", "agent_claim", "abstracted_agent_claim", "evidence_profile", "repo", "source_repo_key", "source_path", "commands", "commands_run"],
        ["claimed_repo", "actual_repo", "claimed_path", "actual_path", "claimed_command", "actual_command", "target_match", "verification_surface_match"],
    ),
    "tool_call_trajectory": (
        ["available_tools", "selected_tools", "commands", "commands_run", "evidence"],
        ["tool_sequence", "tool_inputs", "tool_outputs", "failed_tools", "skipped_relevant_tools", "reason_for_tool_choice"],
    ),
    "diff_test_integrity": (
        ["paths_touched", "changed_files", "quality.checks", "commands", "evidence"],
        ["diff_stat", "diff_entropy", "file_op_types", "assertions_added", "assertions_removed", "mocks_added", "skips_added", "xfail_added", "test_target", "test_exit_code"],
    ),
    "runtime_build_smoke": (
        ["commands", "quality.checks", "evidence", "validation_receipt"],
        ["build_command", "build_exit_code", "runtime_smoke_command", "runtime_smoke_exit_code", "package_receipt", "rollback_receipt"],
    ),
    "human_correction_lineage": (
        ["next_actions", "promotion_blockers", "handoff", "rationale"],
        ["human_correction", "founder_override_reason", "review_decision", "correction_applied"],
    ),
    "model_route_cost": (
        ["agent", "model_origin", "repo", "task_id"],
        ["model_provider", "model_name", "route", "token_input", "token_output", "api_cost", "latency_seconds"],
    ),
    "artifact_lifecycle_lineage": (
        ["state_transition", "artifact_type", "outcome", "promotion_blockers", "release_gate"],
        ["artifact_state_before", "artifact_state_requested", "artifact_state_approved", "post_release_defect", "retrospective_lesson"],
    ),
}


def _record_has_field(record: dict[str, Any], field: str) -> bool:
    if "." in field:
        top, sub = field.split(".", 1)
        nested = record.get(top)
        return isinstance(nested, dict) and bool(nested.get(sub))
    return bool(record.get(field))


def signal_family_status(fields_present: list[str], required_future_fields: list[str]) -> dict[str, Any]:
    fields_missing = [field for field in required_future_fields if field not in fields_present]
    if not fields_present:
        status = "missing"
    elif not fields_missing:
        status = "present"
    else:
        status = "partial"
    return {"status": status, "fields_present": list(fields_present), "fields_missing": fields_missing}


def overall_signal_value(signal_coverage: dict[str, Any], incident_type: str | None = None) -> str:
    _, incident_value = INCIDENT_NEED_MAP.get(str(incident_type or ""), (None, None))
    if incident_value == "CRITICAL":
        return "CRITICAL"
    families = (signal_coverage or {}).get("families") or {}
    present = sum(1 for info in families.values() if info.get("status") == "present")
    partial = sum(1 for info in families.values() if info.get("status") == "partial")
    if present == 0 and partial == 0:
        return "LOW"
    if incident_value == "HIGH" or present >= 3:
        return "HIGH"
    return "MEDIUM"


def _captured_tool_fields(block: Any) -> set[str]:
    """Map a captured tool_call_trajectory block onto the coverage future-field
    names (tool_inputs/tool_outputs are booleans named *_present on the block)."""
    present: set[str] = set()
    if not isinstance(block, dict):
        return present
    if block.get("tool_sequence"):
        present.add("tool_sequence")
    if block.get("tool_inputs_present"):
        present.add("tool_inputs")
    if block.get("tool_outputs_present"):
        present.add("tool_outputs")
    if block.get("failed_tools"):
        present.add("failed_tools")
    if block.get("skipped_relevant_tools"):
        present.add("skipped_relevant_tools")
    if block.get("reason_for_tool_choice"):
        present.add("reason_for_tool_choice")
    return present


def build_human_correction_lineage(record: dict[str, Any]) -> dict[str, Any]:
    """Capture the correction lineage -- claim -> contradiction -> review decision
    -> corrected outcome -> future rule -- from a record's existing claim/evidence
    fields. Most rows are MACHINE adjudication (the sentinel verdict); human and
    founder fields are emitted only when explicitly present, never fabricated, so
    the human-specific signal honestly stays absent until a human actually
    corrects something."""
    alignment = as_dict(record.get("claim_evidence_alignment"))
    state = as_dict(record.get("state_transition"))
    gold = as_dict(record.get("gold_output"))
    input_view = as_dict(record.get("input_view"))
    verdict = str(record.get("verdict") or "")

    claim = str(record.get("abstracted_agent_claim") or input_view.get("claim") or "")
    evidence_contradicts = bool(alignment.get("evidence_contradicts_claim"))
    contradiction_type = str(alignment.get("contradiction_type") or "") or None
    # An explicit upstream human/founder field wins over the machine attribution.
    agent_corrected_after_evidence = bool(record.get("agent_corrected_only_after_evidence") or alignment.get("agent_corrected_only_after_evidence"))
    review_decision = str(record.get("review_decision") or gold.get("verdict") or verdict or "") or None
    corrected_outcome = str(state.get("artifact_state_approved") or gold.get("required_action") or "") or None
    future_rule = str(record.get("future_rule") or gold.get("model_should_learn") or record.get("quality_signal") or "") or None
    downstream_defect = record.get("downstream_defect")
    downstream_defect = str(downstream_defect) if downstream_defect else None
    # An explicit correction_applied wins; otherwise a correction was applied when
    # the adjudication did not simply allow the claim.
    if isinstance(record.get("correction_applied"), bool):
        correction_applied = record.get("correction_applied")
    else:
        correction_applied = (
            bool(review_decision and review_decision.upper() not in ("ALLOW",))
            or (verdict not in ("SAFE", ""))
            or evidence_contradicts
            or state.get("promotion_allowed") is False
        )

    founder_override_reason = record.get("founder_override_reason")
    founder_override_reason = str(founder_override_reason) if founder_override_reason else None
    human_correction = record.get("human_correction")
    human_correction = str(human_correction) if human_correction else None
    human_correction_present = bool(founder_override_reason or human_correction or agent_corrected_after_evidence)

    if founder_override_reason:
        correction_source = "founder_override"
    elif human_correction_present:
        correction_source = "human_review"
    elif review_decision:
        correction_source = "machine_adjudication"
    else:
        correction_source = "none"

    return {
        "schema_version": "sf.human_correction_lineage.v0.1",
        "agent_claim": claim,
        "evidence_contradicts_claim": evidence_contradicts,
        "contradiction_type": contradiction_type,
        "review_decision": review_decision,
        "corrected_outcome": corrected_outcome,
        "correction_applied": correction_applied,
        "future_rule": future_rule,
        "downstream_defect": downstream_defect,
        "founder_override_reason": founder_override_reason,
        "human_correction": human_correction,
        "human_correction_present": human_correction_present,
        "correction_source": correction_source,
    }


def _captured_correction_fields(block: Any) -> set[str]:
    """Map a captured human_correction_lineage block onto the coverage future-field
    names. A machine adjudication captures review_decision + correction_applied;
    human_correction / founder_override_reason stay absent until a human acts."""
    present: set[str] = set()
    if not isinstance(block, dict):
        return present
    if block.get("review_decision"):
        present.add("review_decision")
        present.add("correction_applied")
    if block.get("human_correction_present"):
        present.add("human_correction")
    if block.get("founder_override_reason"):
        present.add("founder_override_reason")
    return present


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _num_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_model_route_cost(record: dict[str, Any]) -> dict[str, Any]:
    """Capture model / route / cost signal from existing fields only. provider and
    execution_mode come from the model_origin attribution; model_name, route,
    tokens, cost, and latency are taken ONLY from explicit per-call fields (a
    router or receipt that actually measured them). Never estimate, never infer
    tokens from character length, never use the agent name as the model name --
    null when absent."""
    origin = as_dict(record.get("model_origin"))
    route_data = as_dict(record.get("model_route"))

    provider = route_data.get("provider") or record.get("model_provider") or origin.get("provider")
    provider = str(provider) if provider and str(provider) not in ("unknown", "") else None
    # model_name comes ONLY from an explicit field -- origin.model_name is the agent
    # name (an anti-pattern) and is deliberately not used here.
    model_name = route_data.get("model_name") or record.get("model_name")
    model_name = str(model_name) if model_name and str(model_name) not in ("unknown", "") else None
    route = route_data.get("route") or record.get("route")
    route = str(route) if route else None
    execution_mode = route_data.get("execution_mode") or origin.get("execution_mode")
    execution_mode = str(execution_mode) if execution_mode and str(execution_mode) not in ("unknown", "") else None

    token_input = _int_or_none(route_data.get("token_input") if route_data.get("token_input") is not None else record.get("token_input"))
    token_output = _int_or_none(route_data.get("token_output") if route_data.get("token_output") is not None else record.get("token_output"))
    api_cost = _num_or_none(route_data.get("api_cost") if route_data.get("api_cost") is not None else record.get("api_cost"))
    latency_seconds = _num_or_none(route_data.get("latency_seconds") if route_data.get("latency_seconds") is not None else record.get("latency_seconds"))

    has_cost = any(value is not None for value in (token_input, token_output, api_cost, latency_seconds))
    if route_data:
        cost_source = "router"
    elif has_cost:
        cost_source = "receipt"
    elif provider or execution_mode:
        cost_source = "model_origin"
    else:
        cost_source = "missing"

    return {
        "schema_version": "sf.model_route_cost.v0.1",
        "provider": provider,
        "model_name": model_name,
        "route": route,
        "execution_mode": execution_mode,
        "token_input": token_input,
        "token_output": token_output,
        "api_cost": api_cost,
        "latency_seconds": latency_seconds,
        "cost_source": cost_source,
        "estimated": False,
    }


def _captured_model_fields(block: Any) -> set[str]:
    """Map a captured model_route_cost block onto the coverage future-field names
    (provider -> model_provider; numeric fields count when measured, even at 0)."""
    present: set[str] = set()
    if not isinstance(block, dict):
        return present
    if block.get("provider"):
        present.add("model_provider")
    if block.get("model_name"):
        present.add("model_name")
    if block.get("route"):
        present.add("route")
    if block.get("token_input") is not None:
        present.add("token_input")
    if block.get("token_output") is not None:
        present.add("token_output")
    if block.get("api_cost") is not None:
        present.add("api_cost")
    if block.get("latency_seconds") is not None:
        present.add("latency_seconds")
    return present


def _captured_present_fields(block: dict[str, Any]) -> set[str]:
    """Leaf field names with a non-empty value in a captured signal block."""
    present: set[str] = set()
    if not isinstance(block, dict):
        return present
    for key, value in block.items():
        if key == "schema_version":
            continue
        if isinstance(value, dict):
            if value:
                present.add(key)
            for sub_key, sub_value in value.items():
                if sub_value not in (None, [], {}, ""):
                    present.add(sub_key)
        elif value not in (None, [], {}, ""):
            present.add(key)
    return present


def build_signal_coverage(record: dict[str, Any]) -> dict[str, Any]:
    """Describe which developer-skill signal families the record carries. Absent
    signals are marked `missing`; partial current evidence is `partial`; only a
    fully instrumented family is `present`. Fields are never fabricated. A captured
    diff_test_integrity block lifts that family's coverage."""
    captured_diff = _captured_present_fields(as_dict(record.get("diff_test_integrity")))
    # An all-`unknown` file_op_types is a forward-looking placeholder, not a
    # discriminated capture, so it must not lift coverage. It counts only once a
    # real op type (created/modified/deleted/renamed) is recorded.
    diff_block = as_dict(record.get("diff_test_integrity"))
    file_ops = as_dict(diff_block.get("file_op_types"))
    if not any(int(file_ops.get(op) or 0) > 0 for op in ("created", "modified", "deleted", "renamed")):
        captured_diff.discard("file_op_types")
    captured_tool = _captured_tool_fields(record.get("tool_call_trajectory"))
    captured_correction = _captured_correction_fields(record.get("human_correction_lineage"))
    captured_model = _captured_model_fields(record.get("model_route_cost"))
    families: dict[str, Any] = {}
    skill_targets: list[str] = []
    for family in SIGNAL_COVERAGE_FAMILIES:
        look_for, future = SIGNAL_COVERAGE_FAMILY_FIELDS[family]
        present = [field for field in (look_for + future) if _record_has_field(record, field)]
        if family == "diff_test_integrity" and captured_diff:
            present = sorted(set(present) | (captured_diff & set(look_for + future)))
        elif family == "tool_call_trajectory" and captured_tool:
            present = sorted(set(present) | (captured_tool & set(look_for + future)))
        elif family == "human_correction_lineage" and captured_correction:
            present = sorted(set(present) | (captured_correction & set(look_for + future)))
        elif family == "model_route_cost" and captured_model:
            present = sorted(set(present) | (captured_model & set(look_for + future)))
        families[family] = signal_family_status(present, future)
        if families[family]["status"] != "missing":
            skill_targets.append(family)
    coverage = {
        "schema_version": "sf.signal_coverage.v0.1",
        "coverage_source": "rapid_prototype",
        "families": families,
        "developer_skill_targets": skill_targets,
        "overall_signal_value": "LOW",
    }
    coverage["overall_signal_value"] = overall_signal_value(coverage, record.get("incident_type"))
    return coverage


def _signal_coverage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    family_status_counts = {family: {"present": 0, "partial": 0, "missing": 0} for family in SIGNAL_COVERAGE_FAMILIES}
    overall_signal_value_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    missing_counter: dict[str, int] = {}
    family_missing_weight = {family: 0 for family in SIGNAL_COVERAGE_FAMILIES}
    with_coverage = 0
    for row in rows:
        coverage = row.get("signal_coverage") if isinstance(row.get("signal_coverage"), dict) else None
        if not coverage:
            continue
        with_coverage += 1
        for family, info in (coverage.get("families") or {}).items():
            status = info.get("status")
            if family in family_status_counts and status in family_status_counts[family]:
                family_status_counts[family][status] += 1
            fields_missing = info.get("fields_missing") or []
            if family in family_missing_weight:
                family_missing_weight[family] += len(fields_missing)
            for missing in fields_missing:
                missing_counter[missing] = missing_counter.get(missing, 0) + 1
        value = coverage.get("overall_signal_value")
        if value in overall_signal_value_counts:
            overall_signal_value_counts[value] += 1
    top_missing = [field for field, _ in sorted(missing_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    # Recommend the families with the largest missing-signal gap first.
    recommended = [family for family, _ in sorted(family_missing_weight.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    return {
        "schema_version": "sf.factory_dojo.signal_coverage_report.v0.1",
        "generated_at": now_utc(),
        "records_seen": len(rows),
        "records_with_signal_coverage": with_coverage,
        "family_status_counts": family_status_counts,
        "overall_signal_value_counts": overall_signal_value_counts,
        "top_missing_fields": top_missing,
        "recommended_next_instrumentation": recommended,
    }


def build_inhouse_dojo(root: Path | str = AGENTREADY_HOME) -> dict[str, Any]:
    """Internal-only Factory Dojo export. Grades every record for data_need /
    data_rights / model_origin, keeps only technically valuable, non-quarantine,
    valid rows, and emits an INHOUSE_READY internal dataset. Never RELEASE_READY,
    never under 40_release_ready, never externally exportable."""
    root = Path(root)
    dojo_root = inhouse_dojo_root(root)
    dojo_root.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(gold_jsonl_path(root))

    emitted: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    technical_value_counts: dict[str, int] = {}
    grade_counts: dict[str, int] = {}
    primary_need_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    safety_status_counts: dict[str, int] = {
        _CLEAN_OUTCOME: 0,
        "REDACTED": 0,
        "QUARANTINE": 0,
    }
    safety_detector_counts: dict[str, int] = {}
    rows_scanned = 0

    for index, record in enumerate(rows, start=1):
        need = infer_data_need_from_incident(record)
        rights = infer_data_rights_from_record(record)
        origin = infer_model_origin_from_record(record)
        # Redaction / quarantine gate: never let an unredacted source_signals
        # envelope become a dataset row. Severe secret material quarantines the
        # row; usernames/emails are scrubbed in place.
        safe_signals, safety = scan_source_signals(record.get("source_signals"))
        if isinstance(record.get("source_signals"), dict):
            rows_scanned += 1
            safety_status_counts[safety["scan_status"]] = safety_status_counts.get(safety["scan_status"], 0) + 1
            for finding in safety["findings"]:
                safety_detector_counts[finding["detector"]] = safety_detector_counts.get(finding["detector"], 0) + 1
        if safety["scan_status"] == "QUARANTINE":
            rights = quarantine_data_rights_for_signal(safety["quarantine_reason"])
        reasons: list[str] = []
        if need.get("technical_value") not in ("MEDIUM", "HIGH", "CRITICAL"):
            reasons.append(f"technical_value:{need.get('technical_value')}")
        if rights.get("grade") == "F_QUARANTINE":
            reasons.append("grade:F_QUARANTINE")
        if safety["scan_status"] == "QUARANTINE":
            reasons.append(f"source_signal_quarantine:{safety['quarantine_reason']}")
        if (need_failures := validate_data_need(need)):
            reasons.append(f"data_need_invalid:{need_failures}")
        if (rights_failures := validate_data_rights(rights)):
            reasons.append(f"data_rights_invalid:{rights_failures}")
        if reasons:
            rejections.append({"row": index, "fingerprint": record.get("fingerprint"), "reasons": reasons})
            continue
        augmented = {**record, "data_need": need, "data_rights": rights, "model_origin": origin}
        if isinstance(record.get("source_signals"), dict):
            augmented["source_signals"] = safe_signals
        augmented["source_signal_safety"] = safety
        augmented["diff_test_integrity"] = build_diff_test_integrity(augmented)
        augmented["tool_call_trajectory"] = build_tool_call_trajectory(augmented)
        augmented["human_correction_lineage"] = build_human_correction_lineage(augmented)
        augmented["model_route_cost"] = build_model_route_cost(augmented)
        augmented["signal_coverage"] = build_signal_coverage(augmented)
        # Training rows keep only DERIVED counts, never the raw/redacted patch
        # text. Counts were just derived above; now drop the diff text so it
        # never survives into Dojo output.
        augmented = strip_diff_text_from_row(augmented)
        emitted.append(augmented)
        technical_value_counts[need["technical_value"]] = technical_value_counts.get(need["technical_value"], 0) + 1
        grade_counts[rights["grade"]] = grade_counts.get(rights["grade"], 0) + 1
        primary_need_counts[need["primary_need"]] = primary_need_counts.get(need["primary_need"], 0) + 1
        provenance = str(record.get("provenance_type") or "NATURAL_RECEIPT")
        source_counts[provenance] = source_counts.get(provenance, 0) + 1

    jsonl_path = dojo_root / "factory_dojo_internal.jsonl"
    append_jsonl(jsonl_path, emitted)

    manifest = {
        "schema_version": "agentready.data_foundry.inhouse_dojo.v1",
        "dataset_id": "factory-dojo-internal",
        "status": "INHOUSE_READY",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "record_count": len(emitted),
        "source_counts": source_counts,
        "technical_value_counts": technical_value_counts,
        "data_rights_grade_counts": grade_counts,
        "primary_need_counts": primary_need_counts,
        "generated_at": now_utc(),
        "external_release_allowed": False,
        "commercial_sale_allowed": False,
        "jsonl_path": rel(root, jsonl_path),
    }
    write_json(dojo_root / "factory_dojo_manifest.json", manifest)

    export_rows = sum(1 for row in emitted if row["data_rights"].get("export_allowed"))
    sale_rows = sum(1 for row in emitted if row["data_rights"].get("commercial_sale_allowed"))
    quarantine_rows = sum(1 for row in emitted if row["data_rights"].get("grade") == "F_QUARANTINE")
    rights_report = {
        "schema_version": "agentready.data_foundry.inhouse_dojo_rights.v1",
        "generated_at": now_utc(),
        "record_count": len(emitted),
        "export_allowed_rows": export_rows,
        "commercial_sale_rows": sale_rows,
        "quarantine_rows": quarantine_rows,
        "rows_missing_data_rights": sum(1 for row in emitted if not row.get("data_rights")),
        "rows_missing_data_need": sum(1 for row in emitted if not row.get("data_need")),
        "all_internal_only": export_rows == 0 and sale_rows == 0 and quarantine_rows == 0,
        "data_rights_grade_counts": grade_counts,
    }
    write_json(dojo_root / "factory_dojo_rights_report.json", rights_report)

    rejection_path = dojo_root / "factory_dojo_rejections.jsonl"
    append_jsonl(rejection_path, rejections)
    quality_report = {
        "schema_version": "agentready.data_foundry.inhouse_dojo_quality.v1",
        "generated_at": now_utc(),
        "rows_seen": len(rows),
        "rows_emitted": len(emitted),
        "rows_rejected": len(rejections),
        "rejections": rejections[:50],
        "rejections_complete": len(rejections) <= 50,
        "rejections_path": rel(root, rejection_path),
        "rejections_sha256": sha256_file(rejection_path),
        "technical_value_distribution": technical_value_counts,
        "rights_grade_distribution": grade_counts,
        "primary_need_distribution": primary_need_counts,
    }
    write_json(dojo_root / "factory_dojo_quality_report.json", quality_report)
    write_json(dojo_root / "factory_dojo_signal_coverage_report.json", _signal_coverage_report(emitted))

    quarantined_rows = sum(
        1 for rej in rejections
        if any(str(reason).startswith("source_signal_quarantine:") for reason in rej.get("reasons", []))
    )
    safety_report = {
        "schema_version": "sf.factory_dojo.source_signal_safety_report.v0.1",
        "scope": "full_scan_including_quarantined",
        "generated_at": now_utc(),
        "rows_scanned": rows_scanned,
        "status_counts": safety_status_counts,
        "detector_counts": safety_detector_counts,
        "quarantined_rows": quarantined_rows,
        "all_clear": safety_status_counts.get("QUARANTINE", 0) == 0 and quarantined_rows == 0,
    }
    write_json(dojo_root / "factory_dojo_source_signal_safety_report.json", safety_report)
    write_json(report_data_foundry_path(root, "cerberus-inhouse-dojo-latest.json"), manifest)

    return {
        "status": "INHOUSE_READY",
        "workflow_lane": "research",
        "data_lane": "research",
        "machinery_zone": "FACTORY",
        "rows_seen": len(rows),
        "rows_emitted": len(emitted),
        "rows_rejected": len(rejections),
        "external_release_allowed": False,
        "commercial_sale_allowed": False,
        "jsonl_path": rel(root, jsonl_path),
        "manifest_path": rel(root, dojo_root / "factory_dojo_manifest.json"),
    }


def signal_coverage_report(root: Path | str = AGENTREADY_HOME) -> dict[str, Any]:
    """Re-derive the signal-coverage report from the emitted internal Dojo rows."""
    root = Path(root)
    dojo_root = inhouse_dojo_root(root)
    dojo_root.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(dojo_root / "factory_dojo_internal.jsonl")
    report = _signal_coverage_report(rows)
    write_json(dojo_root / "factory_dojo_signal_coverage_report.json", report)
    return report


def source_signal_safety_report(root: Path | str = AGENTREADY_HOME) -> dict[str, Any]:
    """Re-derive the source-signal safety summary from the emitted Dojo rows'
    attached source_signal_safety blocks. Quarantined rows never reach the
    emitted set, so this reports PASS/REDACTED on what survived the gate."""
    root = Path(root)
    dojo_root = inhouse_dojo_root(root)
    dojo_root.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(dojo_root / "factory_dojo_internal.jsonl")
    status_counts: dict[str, int] = {
        _CLEAN_OUTCOME: 0,
        "REDACTED": 0,
        "QUARANTINE": 0,
    }
    detector_counts: dict[str, int] = {}
    rows_scanned = 0
    for row in rows:
        safety = row.get("source_signal_safety")
        if not isinstance(safety, dict):
            continue
        if isinstance(row.get("source_signals"), dict):
            rows_scanned += 1
        status = str(safety.get("scan_status") or "PASS")
        status_counts[status] = status_counts.get(status, 0) + 1
        for finding in safety.get("findings") or []:
            detector = str(finding.get("detector") or "unknown")
            detector_counts[detector] = detector_counts.get(detector, 0) + 1
    report = {
        "schema_version": "sf.factory_dojo.source_signal_safety_report.v0.1",
        "scope": "emitted_survivors_only",
        "generated_at": now_utc(),
        "rows_scanned": rows_scanned,
        "status_counts": status_counts,
        "detector_counts": detector_counts,
        "all_clear": status_counts.get("QUARANTINE", 0) == 0,
    }
    write_json(dojo_root / "factory_dojo_source_signal_safety_report.json", report)
    return report
