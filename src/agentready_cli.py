# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Unified public command surface for AgentReady."""
from __future__ import annotations

import sys

COMMANDS: dict[str, str] = {
    "bootstrap-repo": "agent_bootstrap_repo",
    "ci": "agent_ci_local",
    "commit-guard": "agent_coordination.commit_guard",
    "coordination": "agent_coordination.cli",
    "factory-capture": "factory_capture.cli",
    "governance-check": "agent_governance_detectors",
    "data-foundry": "agent_data_foundry",
    "data-foundry-event-runner": "agent_data_foundry_event_runner",
    "deploy": "agent_deploy",
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


def _entrypoint(command: str):
    """Resolve only a compile-time allowlisted module; user input never becomes an import name."""
    if command == "bootstrap-repo":
        from agent_bootstrap_repo import main
    elif command == "ci":
        from agent_ci_local import main
    elif command == "commit-guard":
        from agent_coordination.commit_guard import main
    elif command == "coordination":
        from agent_coordination.cli import main
    elif command == "factory-capture":
        from factory_capture.cli import main
    elif command == "governance-check":
        from agent_governance_detectors import main
    elif command == "data-foundry":
        from agent_data_foundry import main
    elif command == "data-foundry-event-runner":
        from agent_data_foundry_event_runner import main
    elif command == "deploy":
        from agent_deploy import main
    elif command == "package-public":
        from agent_public_package import main
    elif command == "publication-guard":
        from agent_publication_guard import main
    elif command == "history-search":
        from agent_history_search import main
    elif command == "release-readiness":
        from agent_release_readiness import main
    elif command == "release-scorecard":
        from agent_release_scorecard import main
    elif command == "report-contract":
        from agent_report_contract import main
    elif command == "security-scan":
        from agent_security_scan import main
    elif command == "tool-context":
        from agent_tool_context import main
    elif command == "tool-router":
        from agent_router import main
    elif command == "version-record":
        from agent_version_record import main
    elif command == "workstate":
        from agent_workstate import main
    else:
        raise KeyError(command)
    return main


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"Unknown command: {command}\n\n{_usage()}", file=sys.stderr)
        return 2
    entry = _entrypoint(command)
    sys.argv = [f"agentready {command}", *sys.argv[2:]]
    result = entry()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
