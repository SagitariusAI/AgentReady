"""Unified public command surface for AgentReady."""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

COMMANDS: dict[str, str] = {
    "bootstrap-repo": "agent_bootstrap_repo",
    "ci": "agent_ci_local",
    "commit-guard": "agent_coordination.commit_guard",
    "coordination": "agent_coordination.cli",
    "factory-capture": "factory_capture.cli",
    "governance-check": "agent_governance_detectors",
    "data-foundry": "agent_data_foundry",
    "data-foundry-event-runner": "agent_data_foundry_event_runner",
    "package-public": "agent_public_package",
    "publication-guard": "agent_publication_guard",
    "history-search": "agent_history_search",
    "release-readiness": "agent_release_readiness",
    "release-scorecard": "agent_release_scorecard",
    "report-contract": "agent_report_contract",
    "security-scan": "agent_security_scan",
    "tool-context": "agent_tool_context",
    "tool-router": "agent_router",
    "version-record": "agent_version_record",
    "workstate": "agent_workstate",
}


def _usage() -> str:
    commands = "\n".join(f"  {name}" for name in sorted(COMMANDS))
    return f"usage: agentready <command> [args]\n\ncommands:\n{commands}"


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    command = sys.argv[1]
    module_name = COMMANDS.get(command)
    if not module_name:
        print(f"Unknown command: {command}\n\n{_usage()}", file=sys.stderr)
        return 2
    module = importlib.import_module(module_name)
    entry: Callable[..., int | None] = getattr(module, "main")
    sys.argv = [f"agentready {command}", *sys.argv[2:]]
    result = entry()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
