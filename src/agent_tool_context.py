"""Model-facing tool context -- source-to-authority scoped tool records.

**Hard rule:** no model-facing tool list may present a flat, unscoped list of tools. Every exposed tool
entry is tied to its source -> authority capability layer (see
`agent_deterministic_toolbox.CAPABILITY_LAYERS`) and its task profile. This module is the canonical
generator and validator for that context, and enriches the router's machine-readable output.

Each entry carries:
  source · capability_layer · inventory_scope · authority_level · visibility_scope · is_authoritative_total
  · durable_logic_owner · adapter_entrypoint · canonical_entrypoint · side_effect_level · safe_for_task_profile

Cross-layer reconciliation marks tools that exist in one layer but not another, instead of calling them
"missing": `unmanaged_external_visible`, `installed_not_visible`, `indexed_not_executable_here`.
"""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import agent_router as router
from agent_deterministic_toolbox import CAPABILITY_LAYERS, INVENTORY_SCOPES, SCOPE_LAYER

AGENTREADY_HOME = Path(__file__).resolve().parents[1]

# Authority levels a tool entry can carry (which capability layer's authority it speaks with).
AUTHORITY_LEVELS = (
    "canonical_topology",   # defined by the instruction tables (the designed surface)
    "authoritative_total",  # the install-manifest total
    "indexed",              # the AgentGraph index
    "scoped_visibility",    # a PATH/venv/repo scan
    "session_surface",      # the live session probe
    "unmanaged",            # visible somewhere but NOT in the canonical topology
)

# Cross-layer reconciliation statuses: what a tool IS once layers are compared (never bare "missing").
TOOL_STATUSES = (
    "factory_tool",                # in the canonical topology -- a real Factory tool
    "unmanaged_external_visible",  # visible in the live session but NOT in the canonical topology
    "installed_not_visible",       # installed (manifest) but not visible (PATH/session)
    "indexed_not_executable_here",  # indexed (AgentGraph) but not session-visible here
)

# The required per-entry fields -- the validator rejects any entry missing one (no flat/unscoped tool).
REQUIRED_ENTRY_FIELDS = (
    "source", "capability_layer", "inventory_scope", "authority_level", "visibility_scope",
    "is_authoritative_total", "durable_logic_owner", "adapter_entrypoint", "canonical_entrypoint",
    "side_effect_level", "safe_for_task_profile",
)

_NETWORK_HINTS = ("research-intake", "web-explorer", "ollama", "research-scheduler", "company-offices",
                  "founder-publish", "registry-tools", "renovate-check")
_STATE_HINTS = ("coordination-init", "task-", "conflict-check", "worktree", "commit-guard")
_ARTIFACT_HINTS = ("package", "sbom", "secret-deep-scan")


@dataclass
class ToolContextEntry:
    name: str
    source: str
    capability_layer: str
    inventory_scope: str
    authority_level: str
    visibility_scope: str
    is_authoritative_total: bool
    durable_logic_owner: str
    adapter_entrypoint: str
    canonical_entrypoint: str
    side_effect_level: str
    safe_for_task_profile: list = field(default_factory=list)
    status: str = "factory_tool"


def cmd_name(command: str) -> str:
    """The bare command (strip args), e.g. 'agent-tool-lease -Action status' -> 'agent-tool-lease'."""
    return command.split()[0]


def _module_for(cmd: str, home: Path = AGENTREADY_HOME) -> str | None:
    """The Python module that owns this tool's durable logic, or None if it is a pure PowerShell adapter."""
    module = cmd.replace("-", "_")
    if (home / "src" / f"{module}.py").exists():
        return module
    # local-llm leaf wrappers fold into the agent_local_llm package CLI
    if cmd.startswith("agent-local-llm"):
        return "agent_local_llm.cli"
    return None


def _side_effect_level(command: str, report: str) -> str:
    cmd = command.lower()
    rep = (report or "").lower()
    if any(h in cmd for h in _NETWORK_HINTS):
        return "network"
    if ".agent-state" in rep or any(h in cmd for h in _STATE_HINTS):
        return "mutates_coordination_state"
    if any(h in cmd for h in _ARTIFACT_HINTS):
        return "writes_artifacts"
    if rep:
        return "writes_reports"
    return "read_only"


def _profiles_for(cmd: str) -> list[str]:
    """Task profiles whose plan exposes this tool -- the 'safe_for_task_profile' set."""
    return sorted(p for p, plan in router.PROFILES.items()
                  if any(cmd_name(str(s["command"])) == cmd for s in plan))


def canonical_tool_names() -> set[str]:
    """The canonical topology: every tool name the instruction tables (router profiles) expose."""
    names: set[str] = set()
    for plan in router.PROFILES.values():
        for s in plan:
            names.add(cmd_name(str(s["command"])))
    return names


def _unique_topology_steps() -> list[dict]:
    """One step per distinct tool across all profiles, in first-seen order (the canonical surface)."""
    seen: set[str] = set()
    out: list[dict] = []
    for plan in router.PROFILES.values():
        for s in plan:
            name = cmd_name(str(s["command"]))
            if name not in seen:
                seen.add(name)
                out.append(s)
    return out


def build_entry(step: dict, status: str = "factory_tool") -> ToolContextEntry:
    """A scoped, source->authority tool record for one canonical-topology step."""
    command = str(step["command"])
    cmd = cmd_name(command)
    module = _module_for(cmd)
    return ToolContextEntry(
        name=command,
        source="instruction_tables",
        capability_layer="canonical_topology",
        inventory_scope="canonical_topology",
        authority_level="canonical_topology",
        visibility_scope="installed_console_scripts",
        is_authoritative_total=False,  # the topology is not the install-manifest total
        durable_logic_owner=(f"src/{module.split('.')[0]}.py" if module else "console_script"),
        adapter_entrypoint=cmd,
        canonical_entrypoint=(f"python -m {module}" if module else cmd),
        side_effect_level=_side_effect_level(command, str(step.get("report", ""))),
        safe_for_task_profile=_profiles_for(cmd),
        status=status,
    )


def enrich_step(step: dict) -> dict:
    """Attach the source->authority scope fields to a router plan step (no flat/unscoped model output)."""
    entry = build_entry(step)
    return {**step, **asdict(entry)}


def classify_tool(*, in_topology: bool, installed: bool, session_visible: bool, indexed: bool) -> str:
    """Reconcile a tool across layers -> a status (never bare 'missing').

    Precedence: a tool visible in the session but not in the canonical topology is unmanaged; otherwise an
    installed-but-not-visible tool is installed_not_visible; otherwise an indexed-but-not-session-visible
    tool is indexed_not_executable_here; a topology tool that is visible is a factory_tool.
    """
    if session_visible and not in_topology:
        return "unmanaged_external_visible"
    if installed and not session_visible:
        return "installed_not_visible"
    if indexed and not session_visible:
        return "indexed_not_executable_here"
    if in_topology:
        return "factory_tool"
    return "unmanaged_external_visible"


def reconcile(canonical: set[str], *, session_visible=None, installed=None, indexed=None) -> list[dict]:
    """Classify every tool seen in ANY layer; surface the non-factory_tool reconciliation states."""
    session = set(session_visible or [])
    inst = set(installed or [])
    idx = set(indexed or [])
    out: list[dict] = []
    for name in sorted(canonical | session | inst | idx):
        status = classify_tool(in_topology=name in canonical, installed=name in inst,
                               session_visible=name in session, indexed=name in idx)
        if status != "factory_tool":
            out.append({"name": name, "status": status})
    return out


def build_tool_context(*, session_visible=None, installed=None, indexed=None) -> dict:
    """The canonical model-facing tool context: scoped entries + cross-layer reconciliation. Never flat."""
    entries = [build_entry(s) for s in _unique_topology_steps()]
    canonical = canonical_tool_names()
    return {
        # context is itself scoped (canonical topology) -- no naked count
        "source": "instruction_tables",
        "capability_layer": "canonical_topology",
        "inventory_scope": "canonical_topology",
        "authority_level": "canonical_topology",
        "is_authoritative_total": False,
        "tool_count": len(entries),
        "authoritative_total_installed_source": CAPABILITY_LAYERS["total_installed_capability"]["source"],
        "interpretation": (
            "Model-facing tool context is scoped, not flat. These entries are the 'canonical_topology' "
            "layer (the tools the Factory is DESIGNED to expose); the authoritative total installed "
            "capability lives in the install manifest. Cross-layer differences are reconciled "
            "(unmanaged_external_visible / installed_not_visible / indexed_not_executable_here), never "
            "reported as bare 'missing'."
        ),
        "entries": [asdict(e) for e in entries],
        "reconciliation": reconcile(canonical, session_visible=session_visible, installed=installed,
                                    indexed=indexed),
    }


def require_scoped_tool_context(context) -> None:
    """Enforce the hard rule: model-facing tool context is scoped, never a flat/unscoped list.

    Raises if ``context`` is a bare list, carries a naked count (a tool/installed count without an
    ``inventory_scope``), has a scope/layer mismatch, or contains an entry missing any required scope field.
    """
    if isinstance(context, list):
        raise ValueError(
            "model-facing tool context must be a scoped structure, not a flat list of tools "
            "(every exposed tool must carry its source->authority layer and task profile)."
        )
    if not isinstance(context, dict):
        raise TypeError(f"tool context must be a dict, got {type(context).__name__}.")

    has_count = "tool_count" in context or "installed_count" in context
    scope = context.get("inventory_scope")
    if has_count and not scope:
        raise ValueError("naked tool count: model-facing context carries a count without an inventory_scope.")
    if scope is not None:
        if scope not in INVENTORY_SCOPES:
            raise ValueError(f"unknown inventory_scope {scope!r}; must be one of {INVENTORY_SCOPES}.")
        layer = context.get("capability_layer")
        if layer is not None and layer != SCOPE_LAYER[scope]:
            raise ValueError(f"capability_layer {layer!r} disagrees with inventory_scope {scope!r}.")

    entries = context.get("entries")
    if not entries:
        raise ValueError("model-facing tool context has no scoped entries (a flat/empty list is forbidden).")
    for e in entries:
        missing = [f for f in REQUIRED_ENTRY_FIELDS if f not in e]
        if missing:
            raise ValueError(f"tool entry {e.get('name')!r} is unscoped -- missing fields {missing}.")
        if e["inventory_scope"] not in INVENTORY_SCOPES:
            raise ValueError(f"tool entry {e.get('name')!r}: unknown inventory_scope {e['inventory_scope']!r}.")
        if e["capability_layer"] != SCOPE_LAYER[e["inventory_scope"]]:
            raise ValueError(
                f"tool entry {e.get('name')!r}: capability_layer {e['capability_layer']!r} disagrees with "
                f"inventory_scope {e['inventory_scope']!r} (expected {SCOPE_LAYER[e['inventory_scope']]!r})."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        "agent_tool_context",
        description="Emit the scoped, source->authority model-facing tool context (never a flat list).")
    parser.add_argument("--json", action="store_true", help="emit the context as JSON")
    parser.add_argument("--probe-path", action="store_true",
                        help="probe PATH for each canonical tool to populate session visibility")
    args = parser.parse_args(argv)

    session_visible = None
    if args.probe_path:
        session_visible = [n for n in canonical_tool_names() if shutil.which(n)]

    context = build_tool_context(session_visible=session_visible)
    require_scoped_tool_context(context)  # never ship an unscoped/flat context

    if args.json:
        print(json.dumps(context, indent=2, ensure_ascii=True))
        return 0

    print(f"Model-facing tool context: {context['tool_count']} tools in the "
          f"'{context['inventory_scope']}' scope (capability layer: {context['capability_layer']}).")
    print(f"Authoritative total installed capability lives in: {context['authoritative_total_installed_source']}.")
    by_effect: dict[str, int] = {}
    for e in context["entries"]:
        by_effect[e["side_effect_level"]] = by_effect.get(e["side_effect_level"], 0) + 1
    print("By side-effect level: " + ", ".join(f"{k}={v}" for k, v in sorted(by_effect.items())))
    if context["reconciliation"]:
        print(f"Cross-layer reconciliation: {len(context['reconciliation'])} non-factory_tool entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
