"""Public API compatibility contract for the Agent Data Foundry.

After the modularization campaign, `agent_data_foundry` is a thin compatibility/CLI shell that
re-exports every public name from the `agent_data_foundry_lib` leaf modules. This test FREEZES that
contract: the listed names MUST keep resolving on `agent_data_foundry` (existing imports and the CLI
must not break), the package `__all__` must keep exporting the leaf surface, the leaf dependency
graph must stay acyclic, and the `AGENTREADY_HOME` / report-path consolidation must hold (single
source of truth in `paths.py`). Adding a public name is fine; silently dropping one is a breaking
change and should fail here on purpose.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import agent_data_foundry as adf
import agent_data_foundry_lib as adfl

# --- The frozen compatibility surface on `agent_data_foundry` (import path users depend on) -------
# CLI action entrypoints + the leaf APIs that tests / sibling modules import via `from
# agent_data_foundry import X`. This is a contract: removing any of these is a breaking change.
FROZEN_ADF_NAMES = {
    # build / harvest / mining
    "build_data_foundry", "harvest_coordination_records", "discover_receipts",
    "mine_supported_claims", "mine_unsupported_promotions", "mine_unsupported_promotions_v2",
    "mine_vault_code_confusion", "mine_misdirected_verification", "upgrade_cerberus_gold_schema",
    # controlled cases
    "generate_vault_code_confusion_controlled_cases", "generate_unsupported_promotion_controlled_cases",
    "generate_misdirected_verification_controlled_cases", "generate_completion_by_deferral_controlled_cases",
    "generate_supported_claim_controlled_cases", "validate_controlled_case", "validate_controlled_cases",
    "promote_controlled_cases",
    # dataset card / taxonomy
    "emit_dataset_card", "emit_label_taxonomy", "dataset_card_gate", "label_taxonomy_gate",
    # cerberus eval / release
    "build_cerberus_eval_split", "cerberus_baseline_eval", "cerberus_eval_split_gate",
    "cerberus_baseline_eval_gate", "baseline_predict", "build_cerberus_release_gate",
    "emit_cerberus_checksums", "cerberus_checksums_gate",
    # dojo / signal coverage / data rights
    "build_inhouse_dojo", "signal_coverage_report", "source_signal_safety_report", "data_rights_gate",
    "build_signal_coverage", "build_human_correction_lineage", "build_model_route_cost",
    # sentinel eval / training export / product state / code fitness / historical chat
    "cerberus_sentinel_baseline_eval", "cerberus_sentinel_eval_and_gate", "export_cerberus_sentinel_training",
    "product_state_scan", "product_reality_brief_post", "code_fitness_scan",
    "import_historical_chats", "sample_historical_chats",
    # gold corpus / validation / source signals / safety / rights / provenance
    "gold_jsonl_path", "existing_gold_fingerprints", "validate_cerberus_case", "write_cerberus_schema",
    "scan_source_signals", "harvest_source_signals", "normalize_git_file_status",
    "data_rights_gate_row", "summarize_provenance", "build_creator_provenance_envelope",
    # shared foundation
    "AGENTREADY_HOME", "report_data_foundry_path", "cerberus_release_root", "run_id_utc",
    "default_release_id", "_current_git_commit", "CERBERUS_PRODUCT_ID", "CERBERUS_SCHEMA_VERSION",
    "CERBERUS_REQUIRED_LABELS",
}

LEAVES = sorted(p.stem for p in Path("src/agent_data_foundry_lib").glob("*.py") if p.stem != "__init__")


def test_frozen_public_names_resolve_on_agent_data_foundry():
    missing = sorted(n for n in FROZEN_ADF_NAMES if not hasattr(adf, n))
    assert not missing, f"breaking change: names dropped from agent_data_foundry: {missing}"


def test_package_all_exports_key_names():
    # the package __all__ must keep exporting the leaf surface (additions allowed, drops are breaking)
    expected = {
        "build_data_foundry", "build_inhouse_dojo", "build_cerberus_release_gate", "emit_dataset_card",
        "data_rights_gate", "mine_supported_claims", "export_cerberus_sentinel_training",
        "product_state_scan", "code_fitness_scan", "validate_cerberus_case", "AGENTREADY_HOME",
        "CERBERUS_PRODUCT_ID", "CERBERUS_SCHEMA_VERSION",
    }
    missing = sorted(expected - set(adfl.__all__))
    assert not missing, f"breaking change: names dropped from agent_data_foundry_lib.__all__: {missing}"
    assert len(adfl.__all__) >= 110  # the campaign exported ~120 names; guard against silent shrinkage


def test_every_leaf_imports_without_cycle():
    # importing each leaf in isolation proves the dependency graph is acyclic and self-consistent
    for name in LEAVES:
        importlib.import_module(f"agent_data_foundry_lib.{name}")
    assert len(LEAVES) == 27


def test_central_module_is_a_thin_shell():
    import ast

    tree = ast.parse(Path("src/agent_data_foundry.py").read_text(encoding="utf-8"))
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    consts = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
    # the central module owns only the CLI dispatch -- no business-logic functions, no constants
    assert funcs == ["main"], f"central module grew a non-CLI function: {funcs}"
    assert consts == [], f"central module grew a top-level constant: {consts}"


def test_agentready_home_is_a_single_shared_object():
    # consolidation contract: every leaf that takes a default root resolves AGENTREADY_HOME to the
    # one canonical object defined in paths.py -- no recomputed copies that could drift.
    import agent_data_foundry_lib.paths as paths

    for name in ("code_fitness", "controlled_cases", "eval_gate", "historical_chat",
                 "product_state", "training_export", "mining", "harvest", "dataset_card",
                 "cerberus_eval", "data_rights", "dojo_build"):
        m = importlib.import_module(f"agent_data_foundry_lib.{name}")
        assert m.AGENTREADY_HOME is paths.AGENTREADY_HOME, f"{name}.AGENTREADY_HOME is not the paths singleton"


def test_report_path_helper_is_shared_not_recomputed():
    import agent_data_foundry_lib.controlled_cases as cc
    import agent_data_foundry_lib.paths as paths

    assert cc.report_data_foundry_path is paths.report_data_foundry_path
    assert not hasattr(cc, "_report_data_foundry_path")  # the private recompute is gone
