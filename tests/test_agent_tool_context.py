"""Regression tests for the model-facing tool context (source -> authority, never a flat list)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agent_router as router  # noqa: E402
import agent_tool_context as tc  # noqa: E402
from agent_deterministic_toolbox import SCOPE_LAYER  # noqa: E402


# --------------------------------------------------------------------------- the generated context is scoped
def test_build_tool_context_is_scoped_not_flat():
    ctx = tc.build_tool_context()
    assert isinstance(ctx, dict)  # never a flat list
    assert ctx["inventory_scope"] == "canonical_topology"
    assert ctx["capability_layer"] == SCOPE_LAYER[ctx["inventory_scope"]]
    assert ctx["entries"]
    # every exposed tool entry carries the full source->authority record
    for e in ctx["entries"]:
        for f in tc.REQUIRED_ENTRY_FIELDS:
            assert f in e, f"entry {e['name']} missing {f}"
        assert e["capability_layer"] == SCOPE_LAYER[e["inventory_scope"]]
        assert e["source"] == "instruction_tables"
        assert isinstance(e["safe_for_task_profile"], list)
    tc.require_scoped_tool_context(ctx)  # must not raise


def test_entries_map_console_script_to_canonical_entrypoint():
    ctx = tc.build_tool_context()
    by_name = {e["name"]: e for e in ctx["entries"]}
    ci = by_name["agent-ci-local"]
    assert ci["adapter_entrypoint"] == "agent-ci-local"
    assert ci["canonical_entrypoint"] == "python -m agent_ci_local"
    assert ci["durable_logic_owner"] == "src/agent_ci_local.py"
    assert "change" in ci["safe_for_task_profile"]  # appears in the change profile plan
    assert ci["side_effect_level"] in {"writes_reports", "mutates_coordination_state", "read_only",
                                       "network", "writes_artifacts"}


# --------------------------------------------------------------------------- 1) rejects naked counts
def test_rejects_naked_counts():
    with pytest.raises(ValueError, match="naked tool count"):
        tc.require_scoped_tool_context({"tool_count": 92, "entries": [{"name": "x"}]})
    # a flat list is also forbidden
    with pytest.raises(ValueError, match="flat list"):
        tc.require_scoped_tool_context([{"name": "agent-ci-local"}])


# --------------------------------------------------------------------------- 2) rejects scope/layer mismatch
def test_rejects_mismatched_scope_layer_pairs():
    bad_entry = {
        "name": "agent-ci-local", "source": "instruction_tables",
        "inventory_scope": "repo_local_bin_tools",     # -> scoped_visibility
        "capability_layer": "canonical_topology",      # WRONG layer
        "authority_level": "canonical_topology", "visibility_scope": "repo_local_bin_tools",
        "is_authoritative_total": False, "durable_logic_owner": "src/agent_ci_local.py",
        "adapter_entrypoint": "agent-ci-local", "canonical_entrypoint": "python -m agent_ci_local",
        "side_effect_level": "writes_reports", "safe_for_task_profile": ["change"],
    }
    ctx = {"inventory_scope": "canonical_topology", "capability_layer": "canonical_topology",
           "tool_count": 1, "entries": [bad_entry]}
    with pytest.raises(ValueError, match="capability_layer .* disagrees with inventory_scope"):
        tc.require_scoped_tool_context(ctx)


# --------------------------------------------------------------------------- 3) session-visible, not topology
def test_session_visible_absent_from_topology_is_unmanaged_external_visible():
    assert tc.classify_tool(in_topology=False, installed=False, session_visible=True,
                            indexed=False) == "unmanaged_external_visible"
    ctx = tc.build_tool_context(session_visible=["totally-external-tool"])
    recon = {r["name"]: r["status"] for r in ctx["reconciliation"]}
    assert recon["totally-external-tool"] == "unmanaged_external_visible"
    # it is NOT presented as a Factory tool
    assert "totally-external-tool" not in {e["name"] for e in ctx["entries"]}


# --------------------------------------------------------------------------- 4) installed but not visible
def test_installed_but_not_visible_is_installed_not_visible():
    assert tc.classify_tool(in_topology=True, installed=True, session_visible=False,
                            indexed=False) == "installed_not_visible"
    ctx = tc.build_tool_context(installed=["agent-ci-local"], session_visible=[])
    recon = {r["name"]: r["status"] for r in ctx["reconciliation"]}
    assert recon["agent-ci-local"] == "installed_not_visible"  # marked, not "missing"


# --------------------------------------------------------------------------- 5) indexed, not session-visible
def test_indexed_but_not_session_visible_is_indexed_not_executable_here():
    assert tc.classify_tool(in_topology=True, installed=False, session_visible=False,
                            indexed=True) == "indexed_not_executable_here"
    ctx = tc.build_tool_context(indexed=["agent-repo-map"], session_visible=[])
    recon = {r["name"]: r["status"] for r in ctx["reconciliation"]}
    assert recon["agent-repo-map"] == "indexed_not_executable_here"


# --------------------------------------------------------------------------- the router emits a scoped list
def test_router_json_is_enriched_not_flat(capsys):
    assert router.main(["--profile", "discover", "--mode", "Plan", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool_context_scope"] == "canonical_topology"
    # every step carries the original plan keys AND the source->authority scope fields
    for s in payload["steps"]:
        assert {"command", "reason", "report", "heavy"} <= set(s)  # back-compat
        for f in tc.REQUIRED_ENTRY_FIELDS:
            assert f in s, f"router step {s['command']} missing scope field {f}"
        assert s["capability_layer"] == "canonical_topology"


def test_router_tool_context_mode(capsys):
    assert router.main(["--tool-context"]) == 0
    ctx = json.loads(capsys.readouterr().out)
    tc.require_scoped_tool_context(ctx)
    assert ctx["entries"] and ctx["inventory_scope"] == "canonical_topology"
