from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path.home() / ".agentready")
REPORT_ROOT = AGENTREADY_HOME / "reports" / "deterministic-toolbox"

# Tool Inventory Scope Taxonomy. The AgentReady tool
# inventory is MULTI-SCOPE: a count is meaningless without the scope that produced it, AND each source is
# authoritative for a different thing. Five capability layers map source -> what it authoritatively answers:
#   - instruction tables   -> canonical topology          (what the Factory is DESIGNED to expose)
#   - package metadata      -> total installed capability  (the authoritative TOTAL -- NOT a scan)
#   - AgentGraph index      -> indexed capability
#   - PATH / venv / repo scans -> scoped visibility        (what a given scan SEES, not the total)
#   - live session probe    -> current executable surface  (what THIS session can run right now)
CAPABILITY_LAYERS: dict[str, dict[str, str]] = {
    "canonical_topology": {
        "source": "instruction tables (router step table + doc tool tables)",
        "authoritative_for": "the tools the Factory is DESIGNED to expose (topology)"},
    "total_installed_capability": {
        "source": "installed package metadata and console-script records",
        "authoritative_for": "TOTAL installed Factory capability (the authoritative total -- not a scan)"},
    "indexed_capability": {
        "source": "AgentGraph index",
        "authoritative_for": "what AgentGraph has indexed"},
    "scoped_visibility": {
        "source": "PATH / venv / repo scans",
        "authoritative_for": "what a specific scan can SEE (a scope, never the total)"},
    "current_executable_surface": {
        "source": "live session probe",
        "authoritative_for": "what the current agent session can run right now"},
}

# Each inventory_scope belongs to exactly one capability layer.
SCOPE_LAYER: dict[str, str] = {
    "canonical_topology": "canonical_topology",
    "full_installed_factory_tools": "total_installed_capability",
    "agentgraph_indexed_tools": "indexed_capability",
    "machine_level_path_tools": "scoped_visibility",
    "agentgraph_venv_tools": "scoped_visibility",
    "isolated_tool_venv_tools": "scoped_visibility",
    "repo_local_bin_tools": "scoped_visibility",
    "active_session_visible_tools": "current_executable_surface",
}
INVENTORY_SCOPES = tuple(SCOPE_LAYER)

# This report probes a curated set of deterministic tools (Python modules in THIS venv + a few PATH
# commands) -- the scoped_visibility layer, NOT the authoritative total installed capability.
INVENTORY_SCOPE = "isolated_tool_venv_tools"


def require_inventory_scope(payload: dict[str, Any]) -> None:
    """Enforce the core rule: never report a tool count without the inventory scope that produced it.

    Raises ValueError if a payload carries a tool/installed count but no (valid) ``inventory_scope``, if the
    scope is unknown, or if a declared ``capability_layer`` disagrees with the scope's layer. Called by
    ``write_report`` so a naked-total (or mislayered) report fails loudly rather than shipping.
    """
    has_count = "tool_count" in payload or "installed_count" in payload
    scope = payload.get("inventory_scope")
    if has_count and not scope:
        raise ValueError(
            "tool-count report is missing the required 'inventory_scope' field -- every tool count must "
            "declare the inventory scope that produced it (Tool Inventory Scope Taxonomy)."
        )
    if scope is not None and scope not in INVENTORY_SCOPES:
        raise ValueError(f"unknown inventory_scope {scope!r}; must be one of {INVENTORY_SCOPES}.")
    layer = payload.get("capability_layer")
    if layer is not None and scope is not None and layer != SCOPE_LAYER[scope]:
        raise ValueError(
            f"capability_layer {layer!r} disagrees with inventory_scope {scope!r} "
            f"(expected {SCOPE_LAYER[scope]!r})."
        )


@dataclass
class ToolStatus:
    name: str
    kind: str
    installed: bool
    version: str
    purpose: str


def module_version(name: str) -> str:
    try:
        module = __import__(name)
        return str(getattr(module, "__version__", "installed"))
    except Exception as exc:
        return f"error: {exc}"


def module_status(name: str, purpose: str, import_name: str | None = None) -> ToolStatus:
    import_name = import_name or name
    installed = importlib.util.find_spec(import_name) is not None
    return ToolStatus(name=name, kind="python", installed=installed, version=module_version(import_name) if installed else "", purpose=purpose)


def command_status(name: str, purpose: str) -> ToolStatus:
    path = shutil.which(name)
    version = ""
    if path:
        try:
            probe = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=8)
            version = (probe.stdout or probe.stderr).splitlines()[0][:160] if (probe.stdout or probe.stderr) else path
        except Exception:
            version = path
    return ToolStatus(name=name, kind="command", installed=path is not None, version=version, purpose=purpose)


def run_smokes() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})

    try:
        import sympy as sp

        x = sp.symbols("x")
        roots = sp.solve(sp.Eq(x**2 - 5 * x + 6, 0), x)
        record("sympy_quadratic", roots == [2, 3], f"roots={roots}")
    except Exception as exc:
        record("sympy_quadratic", False, str(exc))

    try:
        from z3 import And, Bool, Not, Solver, sat

        a = Bool("a")
        b = Bool("b")
        solver = Solver()
        solver.add(And(a, Not(b)))
        result = solver.check()
        record("z3_boolean_logic", result == sat, f"result={result}; model={solver.model() if result == sat else ''}")
    except Exception as exc:
        record("z3_boolean_logic", False, str(exc))

    try:
        import pandas as pd

        frame = pd.DataFrame({"office": ["eng", "eng", "qa"], "tickets": [2, 3, 4]})
        grouped = getattr(frame.groupby("office")["tickets"].sum(), "to_dict")()
        record("pandas_groupby", grouped == {"eng": 5, "qa": 4}, f"grouped={grouped}")
    except Exception as exc:
        record("pandas_groupby", False, str(exc))

    try:
        import duckdb

        row = duckdb.sql("select sum(x) from (values (2), (3), (5)) t(x)").fetchone()
        value = row[0] if row is not None else None
        record("duckdb_sql", value == 10, f"sum={value}")
    except Exception as exc:
        record("duckdb_sql", False, str(exc))

    try:
        import networkx as nx

        graph = nx.DiGraph()
        graph.add_edges_from([("request", "ticket"), ("ticket", "agent"), ("agent", "evidence")])
        path = nx.shortest_path(graph, "request", "evidence")
        record("networkx_path", path == ["request", "ticket", "agent", "evidence"], f"path={path}")
    except Exception as exc:
        record("networkx_path", False, str(exc))

    return results


def build_payload(run_smoke: bool) -> dict[str, Any]:
    tools = [
        module_status("numpy", "Numerical arrays and vector checks."),
        module_status("scipy", "Scientific computing and statistical primitives."),
        module_status("pandas", "Tabular data checks and summaries."),
        module_status("polars", "Fast tabular scans for larger local datasets."),
        module_status("sympy", "Symbolic math, algebra, exact simplification, equation solving."),
        module_status("z3-solver", "Boolean logic, satisfiability, constraints, proof-oriented checks.", "z3"),
        module_status("duckdb", "Local SQL analytics over CSV/Parquet/SQLite-like data extracts."),
        module_status("statsmodels", "Statistical modeling and confidence checks."),
        module_status("scikit-learn", "Classical ML metrics, clustering, validation helpers.", "sklearn"),
        module_status("networkx", "Graph and dependency reasoning."),
        command_status("python", "General deterministic execution baseline."),
        command_status("node", "JavaScript/JSON/tooling checks."),
        command_status("sqlite3", "SQLite cabinet and local database inspection."),
        command_status("jq", "JSON inspection and transformation."),
        command_status("rg", "Fast local text search."),
        command_status("matlab", "Specialist numerical environment if installed."),
        command_status("octave", "Open MATLAB-like numerical environment if installed."),
        command_status("Rscript", "R statistical scripts if installed."),
        command_status("julia", "Julia numerical scripts if installed."),
    ]
    smokes = run_smokes() if run_smoke else []
    count = len(tools)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        # --- Tool Inventory Scope contract (never a naked count) ---
        "inventory_scope": INVENTORY_SCOPE,
        "capability_layer": SCOPE_LAYER[INVENTORY_SCOPE],
        "tool_count": count,
        "installed_count": sum(1 for tool in tools if tool.installed),
        "topology_source": "src/agent_deterministic_toolbox.py:build_payload (curated deterministic-tool topology)",
        "visibility_source": f"importlib.util.find_spec + shutil.which on {sys.executable} / machine PATH",
        # This is a scoped_visibility report (a venv/PATH scan), NOT the install manifest -> null total here.
        "authoritative_total_installed_count": None,
        "authoritative_total_installed_source": CAPABILITY_LAYERS["total_installed_capability"]["source"],
        "interpretation": (
            "Software Factory tool inventory is multi-scope. The largest count from the full-install "
            "inventory is authoritative for total installed capability. Smaller counts describe scoped "
            "runtime/index/PATH visibility and are not contradictions unless they claim the same scope. "
            f"This report is the '{INVENTORY_SCOPE}' scope ({count} curated deterministic tools probed in "
            "this venv/PATH) in the 'scoped_visibility' layer -- the authoritative total installed "
            "capability lives in the install manifest (not in any scan), and the canonical topology lives "
            "in the instruction tables."
        ),
        "tools": [asdict(tool) for tool in tools],
        "smoke_tests": smokes,
        "smoke_ok": all(item["ok"] for item in smokes) if smokes else None,
        "local_model_rule": "Local models must cite deterministic tool output for math, boolean logic, data checks, estimates, and source-freshness claims when available.",
    }


def write_report(payload: dict[str, Any], report_root: Path | None = None) -> Path:
    require_inventory_scope(payload)  # core rule: no tool count ships without its inventory scope
    report_root = report_root or REPORT_ROOT
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_root / f"deterministic-toolbox-{stamp}.json"
    md_path = report_root / f"deterministic-toolbox-{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    authoritative = payload.get("authoritative_total_installed_count")
    auth_source = payload.get("authoritative_total_installed_source", "the install manifest")
    lines = [
        "# AgentReady Deterministic Toolbox",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Python: `{payload['python']}`",
        # Scope-labeled count -- never a naked total. (Core rule: a count without its scope is meaningless.)
        f"- Inventory scope: `{payload['inventory_scope']}` (capability layer: `{payload.get('capability_layer', 'scoped_visibility')}` -- a scan, NOT the authoritative total)",
        f"- Installed in this scope: {payload['installed_count']} / {payload['tool_count']}",
        f"- Authoritative total installed: {authoritative if authoritative is not None else f'n/a here -- lives in {auth_source}'}",
        f"- Smoke OK: `{payload['smoke_ok']}`",
        "",
        "## Inventory Scope",
        "",
        payload.get("interpretation", ""),
        "",
        "## Local Model Rule",
        "",
        payload["local_model_rule"],
        "",
        "## Tool Inventory",
        "",
        "| Tool | Kind | Installed | Version | Purpose |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for tool in payload["tools"]:
        version = str(tool["version"]).replace("|", "/")
        purpose = str(tool["purpose"]).replace("|", "/")
        lines.append(f"| {tool['name']} | {tool['kind']} | {tool['installed']} | {version} | {purpose} |")
    if payload["smoke_tests"]:
        lines.extend(["", "## Smoke Tests", "", "| Check | OK | Detail |", "| --- | ---: | --- |"])
        for item in payload["smoke_tests"]:
            detail = str(item["detail"]).replace("|", "/")
            lines.append(f"| {item['name']} | {item['ok']} | {detail} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_root / "latest.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    (report_root / "latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and smoke-test deterministic tools for AgentReady agents and local model staff.")
    parser.add_argument("--no-smoke", action="store_true", help="Only inventory tools; skip smoke tests.")
    parser.add_argument("--out-dir", type=Path, help="Report directory (defaults under AGENTREADY_HOME).")
    args = parser.parse_args()
    payload = build_payload(run_smoke=not args.no_smoke)
    report = write_report(payload, args.out_dir)
    print(f"AgentReady deterministic toolbox: {report}")
    if payload["smoke_ok"] is False:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
