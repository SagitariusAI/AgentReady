# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from pathlib import Path

from agent_data_foundry_lib.adjudication import (
    commercial_safety_flags as commercial_safety_flags,
)
from agent_data_foundry_lib.adjudication import (
    ensure_natural_provenance_fields as ensure_natural_provenance_fields,  # re-export (mining moved; tests assert adf.X)
)
from agent_data_foundry_lib.adjudication import (
    gold_coordination_row as gold_coordination_row,
)
from agent_data_foundry_lib.adjudication import (
    receipt_gold_row as receipt_gold_row,  # re-export (mining moved; tests assert adf.X)
)
from agent_data_foundry_lib.adjudication import (
    safe_segment as safe_segment,
)
from agent_data_foundry_lib.adjudication import (
    silver_coordination_row as silver_coordination_row,
)
from agent_data_foundry_lib.adjudication import (
    task_fingerprint as task_fingerprint,
)
from agent_data_foundry_lib.adjudication import (
    task_source_id as task_source_id,
)
from agent_data_foundry_lib.claim_evidence_eval import (
    CLAIM_EVIDENCE_EVAL_SPLIT_SEED as CLAIM_EVIDENCE_EVAL_SPLIT_SEED,
)
from agent_data_foundry_lib.claim_evidence_eval import (
    baseline_predict as baseline_predict,  # re-export (test-imported via adf; no central caller)
)
from agent_data_foundry_lib.claim_evidence_eval import (
    build_claim_evidence_eval_split,
    claim_evidence_baseline_eval,
)
from agent_data_foundry_lib.claim_evidence_eval import (
    claim_evidence_baseline_eval_gate as claim_evidence_baseline_eval_gate,
)
from agent_data_foundry_lib.claim_evidence_eval import (
    claim_evidence_eval_split_gate as claim_evidence_eval_split_gate,
)
from agent_data_foundry_lib.claim_evidence_release import (
    CLAIM_EVIDENCE_RELEASE_ARTIFACTS as CLAIM_EVIDENCE_RELEASE_ARTIFACTS,  # re-export (test-imported via adf)
)
from agent_data_foundry_lib.claim_evidence_release import (
    build_claim_evidence_release_gate,
    emit_claim_evidence_checksums,
)
from agent_data_foundry_lib.claim_evidence_release import (
    claim_evidence_checksums_gate as claim_evidence_checksums_gate,  # re-export (test-imported via adf; no central caller)
)
from agent_data_foundry_lib.code_fitness import code_fitness_scan
from agent_data_foundry_lib.controlled_cases import (
    generate_completion_by_deferral_controlled_cases,
    generate_misdirected_verification_controlled_cases,
    generate_supported_claim_controlled_cases,
    generate_unsupported_promotion_controlled_cases,
    generate_vault_code_confusion_controlled_cases,
    promote_controlled_cases,
    validate_controlled_cases,
)
from agent_data_foundry_lib.controlled_cases import (
    staged_controlled_case_rows as staged_controlled_case_rows,
)
from agent_data_foundry_lib.controlled_cases import (
    validate_controlled_case as validate_controlled_case,  # re-export (no central caller; CLI/test surface)
)
from agent_data_foundry_lib.curated_dataset import curated_dataset_root as curated_dataset_root
from agent_data_foundry_lib.curated_dataset_build import (
    SIGNAL_COVERAGE_FAMILIES as SIGNAL_COVERAGE_FAMILIES,  # re-export (test-imported via adf)
)
from agent_data_foundry_lib.curated_dataset_build import (
    build_curated_dataset,
    signal_coverage_report,
    source_signal_safety_report,
)
from agent_data_foundry_lib.curated_dataset_build import (
    build_human_correction_lineage as build_human_correction_lineage,  # re-export (test-imported)
)
from agent_data_foundry_lib.curated_dataset_build import (
    build_model_route_cost as build_model_route_cost,  # re-export (test-imported)
)
from agent_data_foundry_lib.curated_dataset_build import (
    build_signal_coverage as build_signal_coverage,  # re-export (test-imported)
)
from agent_data_foundry_lib.data_rights import data_rights_gate
from agent_data_foundry_lib.dataset_card import (
    dataset_card_gate as dataset_card_gate,
)
from agent_data_foundry_lib.dataset_card import (
    emit_dataset_card,
    emit_label_taxonomy,
)
from agent_data_foundry_lib.dataset_card import (
    label_taxonomy_gate as label_taxonomy_gate,
)

# Re-exported for tests (imported from agent_data_foundry / asserted via adf.X); not
# referenced directly here, so the redundant `as` alias marks them as intentional
# re-exports for ruff F401. Most lost their only direct user when the Sentinel exporter
from agent_data_foundry_lib.eval_gate import (
    baseline_sentinel_predict as baseline_sentinel_predict,
)
from agent_data_foundry_lib.eval_gate import (
    claim_evidence_sentinel_baseline_eval,
    claim_evidence_sentinel_eval_and_gate,
)
from agent_data_foundry_lib.eval_gate import (
    claim_evidence_sentinel_export_root as claim_evidence_sentinel_export_root,
)
from agent_data_foundry_lib.gold_corpus import (
    claim_evidence_case_schema as claim_evidence_case_schema,  # re-export only (no central caller)
)
from agent_data_foundry_lib.gold_corpus import (
    existing_gold_fingerprints as existing_gold_fingerprints,  # re-export (mining moved; tests assert adf.X)
)
from agent_data_foundry_lib.gold_corpus import (
    gold_jsonl_path as gold_jsonl_path,
)
from agent_data_foundry_lib.gold_corpus import (
    validate_claim_evidence_case as validate_claim_evidence_case,
)
from agent_data_foundry_lib.gold_corpus import (
    write_claim_evidence_schema as write_claim_evidence_schema,
)
from agent_data_foundry_lib.harvest import (
    build_data_foundry,
    harvest_coordination_records,
)
from agent_data_foundry_lib.historical_chat import (
    historical_chats_root as historical_chats_root,
)
from agent_data_foundry_lib.historical_chat import (
    import_historical_chats,
    sample_historical_chats,
)
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl as append_jsonl,
)
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl_rows as append_jsonl_rows,
)
from agent_data_foundry_lib.io_jsonl import (
    jsonl_row_count as jsonl_row_count,
)
from agent_data_foundry_lib.io_jsonl import (
    now_utc as now_utc,
)
from agent_data_foundry_lib.io_jsonl import (
    read_json as read_json,
)
from agent_data_foundry_lib.io_jsonl import (
    read_jsonl as read_jsonl,
)
from agent_data_foundry_lib.io_jsonl import (
    rel as rel,
)
from agent_data_foundry_lib.io_jsonl import (
    sha256_file as sha256_file,
)
from agent_data_foundry_lib.io_jsonl import (
    write_json as write_json,
)
from agent_data_foundry_lib.mining import (
    mine_misdirected_verification,
    mine_supported_claims,
    mine_unsupported_promotions,
    mine_unsupported_promotions_v2,
    mine_vault_code_confusion,
    upgrade_claim_evidence_gold_schema,
)
from agent_data_foundry_lib.paired_curriculum import (
    _PAIRED_CURRICULUM_FAMILY as _PAIRED_CURRICULUM_FAMILY,
)
from agent_data_foundry_lib.paired_curriculum import (
    _PAIRED_CURRICULUM_LABEL_MAP as _PAIRED_CURRICULUM_LABEL_MAP,
)
from agent_data_foundry_lib.paired_curriculum import (
    build_paired_curriculum_block as build_paired_curriculum_block,
)
from agent_data_foundry_lib.paths import (
    AGENTREADY_HOME,
)
from agent_data_foundry_lib.paths import (
    _current_git_commit as _current_git_commit,  # re-export (used by eval_gate/training_export + agent_report_submit compat)
)
from agent_data_foundry_lib.paths import (
    claim_evidence_release_root as claim_evidence_release_root,
)
from agent_data_foundry_lib.paths import (
    default_release_id as default_release_id,
)
from agent_data_foundry_lib.paths import (
    report_data_foundry_path as report_data_foundry_path,
)
from agent_data_foundry_lib.paths import (
    run_id_utc as run_id_utc,
)

# _classify_product_status is imported only by tests (from agent_data_foundry); the
# redundant `as` alias marks it as an intentional re-export for ruff F401.
from agent_data_foundry_lib.product_state import (
    _classify_product_status as _classify_product_status,
)
from agent_data_foundry_lib.product_state import (
    product_reality_brief_post,
    product_state_scan,
)
from agent_data_foundry_lib.provenance import (
    CREATOR_PROVENANCE_SCHEMA as CREATOR_PROVENANCE_SCHEMA,
)
from agent_data_foundry_lib.provenance import (
    build_creator_provenance_envelope as build_creator_provenance_envelope,
)
from agent_data_foundry_lib.provenance import (
    summarize_provenance as summarize_provenance,
)
from agent_data_foundry_lib.receipts import (
    PROMOTABLE_POLICIES as PROMOTABLE_POLICIES,
)
from agent_data_foundry_lib.receipts import (
    discover_receipts as discover_receipts,
)
from agent_data_foundry_lib.rights import (
    INCIDENT_NEED_MAP as INCIDENT_NEED_MAP,
)
from agent_data_foundry_lib.rights import (
    data_rights_gate_row as data_rights_gate_row,  # re-export (data_rights_gate moved; compat surface)
)

# default_data_need / default_data_rights are no longer referenced directly here
# agent_data_foundry, so the redundant `as` alias marks them as intentional
# re-exports for ruff F401.
from agent_data_foundry_lib.rights import (
    default_data_need as default_data_need,
)
from agent_data_foundry_lib.rights import (
    default_data_rights as default_data_rights,
)
from agent_data_foundry_lib.rights import (
    infer_data_need_from_incident as infer_data_need_from_incident,
)
from agent_data_foundry_lib.rights import (
    infer_data_rights_from_record as infer_data_rights_from_record,
)
from agent_data_foundry_lib.rights import (
    infer_model_origin_from_record as infer_model_origin_from_record,
)
from agent_data_foundry_lib.rights import (
    quarantine_data_rights_for_signal as quarantine_data_rights_for_signal,
)
from agent_data_foundry_lib.rights import (
    validate_data_need as validate_data_need,
)
from agent_data_foundry_lib.rights import (
    validate_data_rights as validate_data_rights,
)
from agent_data_foundry_lib.safety_scan import (
    _scan_source_signal_value as _scan_source_signal_value,
)
from agent_data_foundry_lib.safety_scan import scan_source_signals as scan_source_signals
from agent_data_foundry_lib.schemas import (
    CLAIM_EVIDENCE_PRODUCT_ID as CLAIM_EVIDENCE_PRODUCT_ID,
)
from agent_data_foundry_lib.schemas import (
    CLAIM_EVIDENCE_REQUIRED_LABELS as CLAIM_EVIDENCE_REQUIRED_LABELS,
)
from agent_data_foundry_lib.schemas import (
    CLAIM_EVIDENCE_SCHEMA_VERSION as CLAIM_EVIDENCE_SCHEMA_VERSION,  # re-export (mining moved; widely imported via adf)
)
from agent_data_foundry_lib.schemas import (
    SENTINEL_TRAINING_LABELS as SENTINEL_TRAINING_LABELS,
)
from agent_data_foundry_lib.source_signals import (
    build_diff_test_integrity as build_diff_test_integrity,
)
from agent_data_foundry_lib.source_signals import (
    build_tool_call_trajectory as build_tool_call_trajectory,
)

# The following are re-exported for tests and agent_report_submit.py (which import
# them from agent_data_foundry); they are not referenced directly here, so the
# redundant `as` alias marks them as intentional re-exports for ruff F401.
# (harvest_source_signals lost its only direct user here when the gold-row builders
from agent_data_foundry_lib.source_signals import (
    derive_assertion_delta as derive_assertion_delta,
)
from agent_data_foundry_lib.source_signals import (
    derive_file_op_types as derive_file_op_types,
)
from agent_data_foundry_lib.source_signals import (
    derive_mock_skip_signals as derive_mock_skip_signals,
)
from agent_data_foundry_lib.source_signals import (
    extract_diff_text as extract_diff_text,
)
from agent_data_foundry_lib.source_signals import (
    harvest_source_signals as harvest_source_signals,
)
from agent_data_foundry_lib.source_signals import (
    normalize_git_file_status as normalize_git_file_status,
)
from agent_data_foundry_lib.source_signals import (
    strip_diff_text_from_row as strip_diff_text_from_row,
)
from agent_data_foundry_lib.training_export import export_claim_evidence_sentinel_training

# ARCHIVE_PAYLOAD_BUDGET_BYTES + EXPORT_FOLDERS + COORDINATION_HARVEST_SCHEMA +

# and re-imported above.


# and re-imported below. The coordination-harvest / product-state / code-fitness
# schema strings stay here until their own domain leaf is extracted.



# and re-imported below.

# Data Rights / Needs grading layer (DATA_RIGHTS_AND_NEEDS_GRADING_DOCTRINE.md).
# data_need (technical value) and data_rights (export eligibility) are orthogonal:
# commercial eligibility is never inferred from technical value.
# DATA_NEED_PRIMARY_VALUES, TECHNICAL_VALUE_VALUES, DATA_RIGHTS_GRADES, and

# only referenced by the moved rights helpers. INCIDENT_NEED_MAP is re-imported
# below for the staying signal-coverage helper. DATASET_INTENDED_USES + data_rights_gate

# re-imported above.


# re-imported below for the signal-coverage helper.

# Factory Signal Coverage prototype (v0.1). Each internal Dataset row carries a
# signal_coverage block describing which developer-skill signal families are
# present / partial / missing. This is a coverage prototype, NOT full
# instrumentation -- absent signals are marked missing, never fabricated.






# now_utc, rel, sha256_file, _sha256_text, read_json, write_json, _jsonl_dumps,
# jsonl_row_count, append_jsonl_rows, read_jsonl, read_json_from_line, append_jsonl

# at the top of this module.












# safe_segment, task_source_id, task_fingerprint, task_evidence_profile, task_verdict,
# silver_coordination_row, claim_evidence_alignment, commercial_safety_flags, and

# and re-imported above (the self-contained adjudication leaf).



# and re-imported below.















# The receipt_* adjudication helpers, receipt_gold_row, gold_output, state_transition,
# HUMAN_CORRECTION_CARRY_FIELDS, carry_human_correction_fields, and gold_coordination_row

# whole cluster is self-contained (io_jsonl/schemas/source_signals + stdlib only); no
# central back-import. Schema strings, labels, verdicts, and defaults are unchanged.








# schema, schema-version gate, and validation failure tokens are unchanged.





# Controlled-case family subtype registries (VAULT_CODE_CONFUSION / UNSUPPORTED_PROMOTION /




# Controlled-case path helpers (controlled_cases_parent_root / controlled_case_family_slug /




# Controlled-case Gold row builders (vault_code_confusion / unsupported_promotion /




# Controlled-case orchestration (the five generate_*_controlled_cases CLI actions,




# Canonical ClaimEvidence label taxonomy. The release gate and the emitted
# label_taxonomy.json both read from this single source of truth.






# Dataset-card / label-taxonomy report writers (corpus_provenance_breakdown, emit_label_taxonomy,




# ClaimEvidence claim-evidence eval cluster (CLAIM_EVIDENCE_EVAL_SPLIT_SEED / CLAIM_EVIDENCE_HELDOUT_FRACTION,
# build_claim_evidence_eval_split, claim_evidence_eval_split_gate, baseline_predict, claim_evidence_baseline_eval,




# Artifacts sealed by checksums. Deliberately excludes the release gate report
# (regenerated each gate run) and the Gold corpus (grows via the event runner),
# so the seal stays stable and never hashes itself into a circular pretzel.




# default_data_need, default_data_rights, infer_data_need_from_incident,
# infer_data_rights_from_record, validate_data_need, validate_data_rights, and

# B3) and re-imported below. Behavior, grades, and conservative defaults unchanged.


# Signal-coverage helpers, human-correction-lineage / model-route-cost builders,






# import (import_historical_chats), pilot sampler (sample_historical_chats),
# historical_chats_root, and their private helpers + STRONG_KEYWORD_DEFAULTS are a
# near-leaf: the module imports only io_jsonl / safety_scan / rights + stdlib, never
# back from here, so there is no import cycle. Restricted-use grading, hashed IDs,
# redaction/quarantine (severe secret drops segment text), the U+2028/U+2029 JSONL
# readback, word-boundary keyword matching, strong/weak scoring, every output file
# (historical_chat_* + pilot_*) and schema string (sf.historical_chat_*.v0.1) are
# unchanged. The CLI dispatch + the exporter's historical enrichment call the
# re-imported functions.



# shared by the training exporter + the Sentinel eval) and re-imported above.

# SENTINEL_SYSTEM_PROMPT / _SENTINEL_RISK and the sentinel build helpers
# (_sentinel_verdict, _sentinel_input_text, _sentinel_target, _sentinel_heldout)




# H1, the sentinel dataset's eval home) and re-imported above; the training exporter
# below + tests use the re-import. Path string unchanged.


# PairedCurriculum records signed pairs, anchors, grade bands, workflow spines,
# and insufficiency-repair metadata for auditable dataset curation.
# label -> (sign, anchors)


# top of this module.


# Creator Provenance Envelope v0.1: the constants (CREATOR_PROVENANCE_SCHEMA,
# REVIEW_PROVENANCE_SCHEMA, FACTORY_CREATOR_DISPLAY, FACTORY_PROVIDER, _PROV_STAGE_KEYS),
# _prov_stage, _human_correction_signal, _model_signal, build_creator_provenance_envelope,

# re-exported via the import at the top of this module. _current_git_commit stays here --
# it is shared by the exporter and the eval gate.



# (eval_gate / training_export now import it directly from paths -- the lazy back-imports are gone.)


# A false SAFE on these labels is the most dangerous Sentinel error: the agent
# claimed a higher state than evidence supports and the Sentinel waved it through.


# (CRITICAL_SENTINEL_LABELS, _VERDICT_DEFAULT_LABEL, _SENTINEL_SCHEMA,
# STRICT_JSON_THRESHOLD, _parse_sentinel_input, baseline_sentinel_predict,
# claim_evidence_sentinel_baseline_eval, _coerce_prediction, _predicted_sign,
# claim_evidence_sentinel_eval_and_gate) is a near-leaf: it imports io_jsonl / paired_curriculum /
# provenance / schemas + stdlib, with the owner-pinned _current_git_commit reached
# via a call-time lazy import (no module-level cycle). All metrics, output files,
# schema strings, and the promotion gate (default NOT_PROMOTED; BASELINE_REQUIRED with
# no baseline; PROMOTED only on beating the baseline with no false-SAFE / critical-
# recall regression; training loss never accepted) are unchanged.


# ---- Product State Scanner + Reality Brief Runner v0.1 --------------------
# Deterministic, DRY-RUN / report-only. Maps a declared component registry to
# EVIDENCE-DERIVED states -- a well-defined document is NOT proof of
# implementation. Never upgrades past DEFINED without code/test/gate/artifact/
# owner evidence; never assigns PRODUCTION_READY/RELEASE_CANDIDATE/sell-ready
# from prose; never writes under 40_release_ready; never makes a release or
# commercial claim. The local model is meant to reason over these reports, not
# raw repo chaos -- so the component list is explicit, and evidence is discovered.



# scanner (product_state_scan), the brief post (product_reality_brief_post), the
# _PS_* constants, the _PRODUCT_STATE_COMPONENTS registry, and the _ps_* /
# classify / scan / validate / brief helpers are a near-leaf: the module imports
# only io_jsonl / safety_scan + stdlib, never back from here, so no import cycle.
# The component registry references other subsystems by string locators only; its
# product_state.scanner self-locator was updated to the new file. Dry-run/report-
# only behavior, the evidence bar (docs alone never reach BUILT; RELEASE_CANDIDATE
# / PRODUCTION_READY / sell-ready never inferred), every output file + schema
# string, the CHAT_UNAVAILABLE != POSTED rule, the secret gate, and "posting never
# mutates product state" are all unchanged. The CLI dispatch calls the re-imports.




# _cf_* helpers + code_fitness_scan are a near-leaf: the module imports only io_jsonl
# + stdlib (ast/re/subprocess/shutil/sys), never back from here, so no import cycle.
# Dry-run/report-only, no code mutation, no 40_release_ready writes, git-ls-files
# scanning, optional-scanner availability, BLOCK/WARN/INFO + PairedCurriculum curriculum
# fields, every report file, sf.code_fitness.v0.1, and the tracked 5-BLOCK baseline
# are all unchanged. The CLI dispatch calls the re-imported code_fitness_scan.



# re-imported below. The per-row eligibility logic (grade = class, export_allowed
# = clearance; candidate != cleared) is unchanged. The data_rights_gate dataset
# wrapper below stays here and calls the re-imported data_rights_gate_row.









# ClaimEvidence label-mining cluster (receipt_*_candidate detectors, append_mined_gold_rows, the five




# Coordination harvest + ARCHIVE build pipeline (harvest_coordination_records, write_rejections,
# copy_raw_receipt, file_record, write_archive_plan, write_manifest, write_report, build_data_foundry)



def main(argv: list[str] | None = None) -> int:
    if argv is None:
        from factory_capture.governed import auto_capture_current_process

        captured_exit = auto_capture_current_process(surface="agent-data-foundry")
        if captured_exit is not None:
            return captured_exit
    parser = argparse.ArgumentParser(description="Curate AgentReady receipts into standard training dataset exports.")
    parser.add_argument(
        "-Action",
        "--action",
        choices=(
            "status",
            "build",
            "harvest-coordination",
            "mine-supported-claims",
            "mine-unsupported-promotions",
            "mine-unsupported-promotions-v2",
            "mine-vault-code-confusion",
            "mine-misdirected-verification",
            "generate-vault-code-confusion-controlled-cases",
            "generate-unsupported-promotion-controlled-cases",
            "generate-misdirected-verification-controlled-cases",
            "generate-completion-by-deferral-controlled-cases",
            "generate-supported-claim-controlled-cases",
            "emit-dataset-card",
            "emit-label-taxonomy",
            "build-claim_evidence-eval-split",
            "claim_evidence-baseline-eval",
            "emit-claim_evidence-checksums",
            "build-curated-dataset",
            "data-rights-gate",
            "signal-coverage-report",
            "source-signal-safety-report",
            "import-historical-chats",
            "sample-historical-chats",
            "export-claim_evidence-sentinel-training",
            "claim_evidence-sentinel-baseline-eval",
            "claim_evidence-sentinel-eval-gate",
            "product-state-scan",
            "product-reality-brief",
            "code-fitness-scan",
            "validate-controlled-cases",
            "promote-controlled-cases",
            "upgrade-claim_evidence-gold",
            "claim_evidence-release-gate",
        ),
        default="status",
    )
    parser.add_argument("-Root", "--root", default=str(AGENTREADY_HOME))
    parser.add_argument("-ReleaseId", "--release-id", default="")
    parser.add_argument("-MinScore", "--min-score", type=int, default=70)
    parser.add_argument("-CoordinationRoot", "--coordination-root", default="")
    parser.add_argument("-MaxRoots", "--max-roots", type=int, default=100)
    parser.add_argument("-LimitPerRoot", "--limit-per-root", type=int, default=250)
    parser.add_argument("-DatasetPath", "--dataset-path", default="")
    parser.add_argument("-IntendedUse", "--intended-use", default="internal_research")
    parser.add_argument("-OutputPath", "--output-path", default="")
    parser.add_argument("-Keywords", "--keywords", default="")
    parser.add_argument("-StrongKeywords", "--strong-keywords", default="")
    parser.add_argument("-Limit", "--limit", type=int, default=20)
    parser.add_argument("-HeldoutPct", "--heldout-pct", type=int, default=20)
    parser.add_argument("-BriefMode", "--brief-mode", choices=["file", "chat", "both"], default="file")
    parser.add_argument("-Regenerate", "--brief-regenerate", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.action == "status":
        latest = root / "reports" / "data-foundry" / "latest.json"
        if latest.exists():
            print(f"AgentReady Data Foundry latest: {latest}")
            print(latest.read_text(encoding="utf-8"))
            return 0
        print("AgentReady Data Foundry has not built a release yet.")
        return 2
    if args.action == "harvest-coordination":
        result = harvest_coordination_records(
            root,
            coordination_root=Path(args.coordination_root) if args.coordination_root else None,
            max_roots=args.max_roots,
            limit_per_root=args.limit_per_root,
        )
        print("AgentReady Data Foundry coordination harvest")
        print(f"Manifest: {root / result['manifest_path']}")
        print(f"Gold rows: {result['summary']['gold_rows']} Captured: {result['summary']['captured']}")
        return 0
    if args.action == "claim_evidence-release-gate":
        result = build_claim_evidence_release_gate(root)
        print(f"AgentReady ClaimEvidence release gate: {result['status']}")
        print(f"Report: {root / 'data' / 'training-library' / '40_release_ready' / result['product_id'] / 'release_gate_report.json'}")
        return 0 if result["status"] == "RELEASE_READY" else 2
    if args.action == "mine-supported-claims":
        result = mine_supported_claims(root, coordination_root=Path(args.coordination_root) if args.coordination_root else None)
        print("AgentReady ClaimEvidence supported-claim mining")
        print(f"Mined: {result['mined']} Skipped: {result['skipped']}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-mine-supported-claims-latest.json'}")
        return 0
    if args.action == "mine-unsupported-promotions":
        result = mine_unsupported_promotions(root, coordination_root=Path(args.coordination_root) if args.coordination_root else None)
        print("AgentReady ClaimEvidence unsupported-promotion mining")
        print(f"Mined: {result['mined']} Skipped: {result['skipped']}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-mine-unsupported-promotions-latest.json'}")
        return 0
    if args.action == "mine-unsupported-promotions-v2":
        result = mine_unsupported_promotions_v2(root, coordination_root=Path(args.coordination_root) if args.coordination_root else None)
        print("AgentReady ClaimEvidence unsupported-promotion v2 mining")
        print(f"Mined: {result['mined']} Skipped: {result['skipped']}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-mine-unsupported-promotions-v2-latest.json'}")
        return 0
    if args.action == "mine-vault-code-confusion":
        result = mine_vault_code_confusion(root, coordination_root=Path(args.coordination_root) if args.coordination_root else None)
        print("AgentReady ClaimEvidence vault/code-confusion mining")
        print(f"Mined: {result['mined']} Skipped: {result['skipped']}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-mine-vault-code-confusion-latest.json'}")
        return 0
    if args.action == "mine-misdirected-verification":
        result = mine_misdirected_verification(root, coordination_root=Path(args.coordination_root) if args.coordination_root else None)
        print("AgentReady ClaimEvidence misdirected-verification mining")
        print(f"Mined: {result['mined']} Skipped: {result['skipped']}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-mine-misdirected-verification-latest.json'}")
        return 0
    if args.action == "generate-vault-code-confusion-controlled-cases":
        result = generate_vault_code_confusion_controlled_cases(root)
        print("AgentReady ClaimEvidence vault/code controlled-case generation")
        print(f"Generated: {result['generated']} Validated: {result['validated']} Promoted to Gold: {result['promoted_to_gold']}")
        print(f"Staging: {root / result['staging_path']}")
        return 0 if result["validated"] else 2
    if args.action == "generate-unsupported-promotion-controlled-cases":
        result = generate_unsupported_promotion_controlled_cases(root)
        print("AgentReady ClaimEvidence unsupported-promotion controlled-case generation")
        print(f"Generated: {result['generated']} Validated: {result['validated']} Promoted to Gold: {result['promoted_to_gold']}")
        print(f"Staging: {root / result['staging_path']}")
        return 0 if result["validated"] else 2
    if args.action == "generate-misdirected-verification-controlled-cases":
        result = generate_misdirected_verification_controlled_cases(root)
        print("AgentReady ClaimEvidence misdirected-verification controlled-case generation")
        print(f"Generated: {result['generated']} Validated: {result['validated']} Promoted to Gold: {result['promoted_to_gold']}")
        print(f"Staging: {root / result['staging_path']}")
        return 0 if result["validated"] else 2
    if args.action == "generate-completion-by-deferral-controlled-cases":
        result = generate_completion_by_deferral_controlled_cases(root)
        print("AgentReady ClaimEvidence completion-by-deferral controlled-case generation")
        print(f"Generated: {result['generated']} Validated: {result['validated']} Promoted to Gold: {result['promoted_to_gold']}")
        print(f"Staging: {root / result['staging_path']}")
        return 0 if result["validated"] else 2
    if args.action == "generate-supported-claim-controlled-cases":
        result = generate_supported_claim_controlled_cases(root)
        print("AgentReady ClaimEvidence supported-claim controlled-case generation")
        print(f"Generated: {result['generated']} Validated: {result['validated']} Promoted to Gold: {result['promoted_to_gold']}")
        print(f"Staging: {root / result['staging_path']}")
        return 0 if result["validated"] else 2
    if args.action == "emit-dataset-card":
        result = emit_dataset_card(root)
        print("AgentReady ClaimEvidence dataset card")
        print(f"Records: {result['total_records']} Natural: {result['natural_records']} Controlled: {result['controlled_records']} ({result['controlled_pct']}%)")
        print(f"Card: {root / result['path']}")
        return 0
    if args.action == "emit-label-taxonomy":
        result = emit_label_taxonomy(root)
        print("AgentReady ClaimEvidence label taxonomy")
        print(f"Labels: {', '.join(result['labels'])}")
        print(f"Taxonomy: {root / result['path']}")
        return 0
    if args.action == "build-claim_evidence-eval-split":
        result = build_claim_evidence_eval_split(root)
        print("AgentReady ClaimEvidence eval split")
        print(f"Total: {result['total_cases']} Heldout: {result['heldout_count']} Heldout controlled proportion: {result['heldout_controlled_proportion']}")
        print(f"SAFE heldout natural-majority: {result['safe_heldout_natural_majority']} All six labels in heldout: {result['all_six_labels_in_heldout']}")
        print(f"Manifest: {root / result['manifest_path']}")
        return 0
    if args.action == "claim_evidence-baseline-eval":
        result = claim_evidence_baseline_eval(root)
        m = result["metrics"]
        print("AgentReady ClaimEvidence baseline eval (provider-neutral, deterministic)")
        print(f"Heldout: {result['heldout_case_count']} verdict_accuracy: {m['verdict_accuracy']} macro_f1: {m['macro_f1']}")
        print(f"natural_acc: {m['natural_subset_accuracy']} controlled_acc: {m['controlled_subset_accuracy']} delta: {m['natural_vs_controlled_delta']}")
        print(f"SAFE_FPR: {m['SAFE_false_positive_rate']} BLOCK_FNR: {m['BLOCK_false_negative_rate']}")
        return 0
    if args.action == "emit-claim_evidence-checksums":
        result = emit_claim_evidence_checksums(root)
        print("AgentReady ClaimEvidence checksums + release receipt")
        print(f"Checksummed: {result['checksummed']} Missing: {result['missing']}")
        print(f"Release status: {result['release_status']} Gate: {result['gate_pass_count']}")
        print(f"Receipt: {root / result['receipt_path']}")
        return 0
    if args.action == "build-curated-dataset":
        result = build_curated_dataset(root)
        print("AgentReady Curated Dataset internal export (restricted-use)")
        print(f"Status: {result['status']} Seen: {result['rows_seen']} Emitted: {result['rows_emitted']} Rejected: {result['rows_rejected']}")
        print(f"External release allowed: {result['external_release_allowed']} Commercial sale allowed: {result['commercial_sale_allowed']}")
        print(f"Manifest: {root / result['manifest_path']}")
        return 0
    if args.action == "data-rights-gate":
        result = data_rights_gate(
            root,
            dataset_path=Path(args.dataset_path) if args.dataset_path else None,
            intended_use=args.intended_use,
        )
        print("AgentReady data rights gate")
        print(f"Intended use: {result['intended_use']} Status: {result['status']}")
        print(f"Seen: {result['rows_seen']} Passed: {result['rows_passed']} Failed: {result['rows_failed']}")
        if result["failure_reasons"]:
            print(f"Failure reasons: {result['failure_reasons']}")
        return 0 if result["status"] == "PASS" else 2
    if args.action == "signal-coverage-report":
        result = signal_coverage_report(root)
        print("AgentReady Curated Dataset signal coverage report")
        print(f"Records: {result['records_with_signal_coverage']} Value counts: {result['overall_signal_value_counts']}")
        print(f"Recommended next instrumentation: {result['recommended_next_instrumentation']}")
        return 0
    if args.action == "source-signal-safety-report":
        result = source_signal_safety_report(root)
        print("AgentReady Curated Dataset source-signal safety report")
        print(f"Rows scanned: {result['rows_scanned']} Status counts: {result['status_counts']}")
        print(f"Detector counts: {result['detector_counts']} All clear: {result['all_clear']}")
        return 0 if result["all_clear"] else 2
    if args.action == "import-historical-chats":
        result = import_historical_chats(root, source_path=args.dataset_path or None)
        print("AgentReady historical chat import (restricted-use)")
        print(f"Status: {result['status']} Sessions: {result['session_count']} Segments: {result['segment_count']}")
        print(f"Quarantined segments: {result['quarantined_segments']} Redacted: {result['redacted_segments']}")
        print(f"All restricted use: {result['all_restricted_use']} Output: {root / result['output_root']}")
        return 0 if result["all_restricted_use"] else 2
    if args.action == "sample-historical-chats":
        result = sample_historical_chats(
            args.dataset_path or None,
            args.output_path or None,
            keywords=args.keywords,
            limit=args.limit,
            strong_keywords=args.strong_keywords,
        )
        print("AgentReady historical chat pilot sampler")
        print(f"Source conversations: {result['source_conversation_count']} Selected: {result['selected_count']}")
        print(f"Keywords: {result['keywords']}")
        print(f"Pilot conversations: {result['pilot_conversations_path']}")
        print(f"Pilot manifest: {result['pilot_manifest_path']}")
        return 0
    if args.action == "export-claim_evidence-sentinel-training":
        result = export_claim_evidence_sentinel_training(root, heldout_pct=args.heldout_pct)
        print("AgentReady Dataset training exporter -- ClaimEvidence Sentinel (restricted-use, export-only, PairedCurriculum curriculum)")
        print(f"Status: {result['status']} Train: {result['train_count']} Heldout: {result['heldout_count']}")
        print(f"PairedCurriculum rows: {result['rows_with_paired_curriculum']} Signs: {result['sign_distribution']} Grades: {result['grade_distribution']} Paired/Unpaired: {result['paired_rows']}/{result['unpaired_rows']}")
        print(f"Excluded: {result['excluded']}")
        print(f"Readback matches: {result['readback_matches']} No overlap: {result['train_heldout_no_overlap']} All restricted use: {result['all_restricted_use']}")
        prov = result["provenance_summary"]
        print(f"Provenance source_commit: {result['source_commit']} Human/Model/Factory: {prov['human_vs_model_vs_factory']}")
        print(f"Provenance review_status: {prov['review_status_distribution']} Unknown creator/model_version: {prov['unknown_creator_count']}/{prov['unknown_model_version_count']}")
        print(f"Model training performed: {result['model_training_performed']} Output: {root / result['output_root']}")
        ok = result["readback_matches"] and result["train_heldout_no_overlap"] and result["all_restricted_use"]
        return 0 if ok else 2
    if args.action == "claim_evidence-sentinel-baseline-eval":
        result = claim_evidence_sentinel_baseline_eval(root)
        print("AgentReady ClaimEvidence Sentinel heldout baseline eval (eval-only, deterministic)")
        print(f"Status: {result['status']} Evaluated: {result['evaluated_rows']} Excluded: {result['excluded_rows']}")
        print(f"Verdict accuracy: {result['verdict_accuracy']} Label macro F1: {result['label_macro_f1']} False-SAFE rate: {result['false_safe_rate']}")
        print(f"Critical-label recall: {result['critical_label_recall']}")
        print(f"Model training performed: {result['model_training_performed']} Output: {root / result['output_root']}")
        return 0
    if args.action == "claim_evidence-sentinel-eval-gate":
        result = claim_evidence_sentinel_eval_and_gate(root, predictions_path=args.dataset_path or None)
        print("AgentReady ClaimEvidence Sentinel eval + promotion gate (pure-Python, runtime-independent)")
        print(f"Decision: {result['decision']} Promoted: {result['promoted']}")
        print(f"Heldout: {result['total_heldout_rows']} Matched: {result['matched_predictions']} Missing: {result['missing_predictions']} Extra: {result['extra_predictions']}")
        print(f"Verdict acc: {result['verdict_accuracy']} Label macro F1: {result['label_macro_f1']} Sign acc: {result['sign_accuracy']} False-SAFE: {result['false_safe_rate']} Strict-JSON: {result['strict_json_validity']}")
        print(f"Output: {root / result['output_root']}")
        return 0 if result["decision"] != "BASELINE_REQUIRED" else 2
    if args.action == "product-state-scan":
        result = product_state_scan(root)
        print("AgentReady Product State Scanner (deterministic, dry-run/report-only)")
        print(f"Mode: {result['mode']} Components: {result['components_scanned']} Gate green: {result['gate_green']}")
        print(f"Status distribution: {result['status_distribution']}")
        print(f"Schema valid: {result['schema_valid']} Errors: {result['schema_errors']}")
        print(f"Wrote release-ready: {result['wrote_release_ready']} Model wiring: {result['model_wiring_performed']}")
        print(f"Output: {root / result['output_root']}")
        return 0 if result["schema_valid"] else 2
    if args.action == "product-reality-brief":
        result = product_reality_brief_post(root, brief_mode=args.brief_mode, regenerate=args.brief_regenerate)
        print("AgentReady Product Reality Brief post (advisory; never modifies product state)")
        print(f"Mode: {result['receipt']['mode']} Post status: {result['post_status']} Posted at: {result['receipt']['posted_at']}")
        print(f"Brief sha256: {result['receipt']['brief_sha256']} Scan run id: {result['receipt']['scan_run_id']}")
        print(f"Defined-not-built: {result['receipt']['defined_not_built_count']} Blocked: {result['receipt']['blocked_count']} Sealed: {result['receipt']['sealed_count']}")
        print(f"Channel: {result['receipt']['channel']} Message id: {result['receipt']['message_id']} Dry-run: {result['receipt']['dry_run']}")
        print(f"Output: {root / result['output_root']}")
        return 0 if result["ok"] else 2
    if args.action == "code-fitness-scan":
        result = code_fitness_scan(root)
        print("AgentReady Code Fitness Runner (deterministic, dry-run/report-only)")
        print(f"Mode: {result['mode']} No mutation: {result['no_mutation']} Files scanned: {result['files_scanned']}")
        print(f"Score: {result['score']} Severity counts: {result['severity_counts']}")
        print(f"Lint clean: {result['lint_clean']} Tools: {result['tools']}")
        print(f"Wrote release-ready: {result['wrote_release_ready']} Output: {root / result['output_root']}")
        return 0
    if args.action == "validate-controlled-cases":
        result = validate_controlled_cases(root)
        print("AgentReady ClaimEvidence controlled-case validation")
        print(f"Checked: {result['checked']} Validated: {result['validated']} Eligible: {result['eligible_for_promotion']}")
        print(f"Report: {root / result['validation_report_path']}")
        return 0 if result["validated"] else 2
    if args.action == "promote-controlled-cases":
        result = promote_controlled_cases(root)
        print("AgentReady ClaimEvidence controlled-case promotion")
        print(f"Validated: {result['validated']} Promoted: {result['promoted']} Skipped duplicates: {result['skipped_duplicates']}")
        print(f"Receipt: {root / result['promotion_receipt_path']}")
        return 0 if result["validated"] else 2
    if args.action == "upgrade-claim_evidence-gold":
        result = upgrade_claim_evidence_gold_schema(root)
        print("AgentReady ClaimEvidence Gold schema upgrade")
        print(f"Rewritten: {result['rewritten']} Skipped: {len(result['skipped'])}")
        print(f"Report: {root / 'reports' / 'data-foundry' / 'claim_evidence-gold-schema-upgrade-latest.json'}")
        return 0
    result = build_data_foundry(
        root,
        args.release_id or None,
        args.min_score,
        coordination_root=Path(args.coordination_root) if args.coordination_root else None,
    )
    print(f"AgentReady Data Foundry release: {result['release_id']}")
    print(f"Manifest: {root / result['manifest_path']}")
    print(f"ARCHIVE plan: {root / result['archive_plan_path']}")
    print(f"Promoted: {result['summary']['promoted']} Rejected: {result['summary']['rejected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
