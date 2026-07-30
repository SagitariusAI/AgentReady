# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Human-readable and machine-readable AgentReady prerequisite catalog."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from typing import Any

SCHEMA = "agentready.prerequisites.v1"
PROFILES = ("core", "recommended", "full", "development")

CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "windows",
        "name": "Windows",
        "tier": "core",
        "required": True,
        "capability": "Supported operating system for this public AgentReady release.",
        "check": {"kind": "platform", "platform": "win32"},
        "download_url": "https://www.microsoft.com/windows/",
        "install_commands": [],
        "verify_commands": ["winver"],
        "publicly_available": True,
    },
    {
        "id": "python",
        "name": "Python",
        "tier": "core",
        "required": True,
        "capability": "Runs AgentReady. Version 3.11 or newer is required.",
        "check": {"kind": "python", "minimum": [3, 11]},
        "download_url": "https://www.python.org/downloads/windows/",
        "install_commands": [],
        "verify_commands": ["python --version"],
        "publicly_available": True,
    },
    {
        "id": "git",
        "name": "Git",
        "tier": "core",
        "required": True,
        "capability": "Repository identity, worktrees, hooks, package manifests, and release evidence.",
        "check": {"kind": "command", "commands": ["git"]},
        "download_url": "https://git-scm.com/downloads/win",
        "install_commands": [],
        "verify_commands": ["git --version"],
        "publicly_available": True,
    },
    {
        "id": "uv",
        "name": "uv",
        "tier": "core",
        "required": True,
        "capability": "Installs AgentReady and its isolated Python tool environment.",
        "check": {"kind": "command", "commands": ["uv"]},
        "download_url": "https://docs.astral.sh/uv/getting-started/installation/",
        "install_commands": [
            'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        ],
        "verify_commands": ["uv --version"],
        "publicly_available": True,
    },
    {
        "id": "powershell",
        "name": "PowerShell 7",
        "tier": "recommended",
        "required": False,
        "capability": "Recommended Windows command shell for the documented workflows.",
        "check": {"kind": "command", "commands": ["pwsh"]},
        "download_url": "https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows",
        "install_commands": ["winget install --id Microsoft.PowerShell --source winget"],
        "verify_commands": ["pwsh --version"],
        "publicly_available": True,
    },
    {
        "id": "serena",
        "name": "Serena",
        "tier": "recommended",
        "required": False,
        "capability": "MCP semantic code intelligence, symbol-aware editing, and durable agent memory.",
        "check": {"kind": "command", "commands": ["serena"]},
        "download_url": "https://github.com/oraios/serena",
        "install_commands": ["uv tool install -p 3.13 serena-agent", "serena init"],
        "verify_commands": ["serena --help"],
        "publicly_available": True,
        "notes": "Configure the Serena MCP server in the chosen AI client after installation.",
    },
    {
        "id": "graphify",
        "name": "Graphify",
        "tier": "recommended",
        "required": False,
        "capability": "Creates and queries repository or document knowledge graphs.",
        "check": {"kind": "command", "commands": ["graphify"]},
        "download_url": "https://github.com/Graphify-Labs/graphify",
        "install_commands": [
            'uv tool install "graphifyy[mcp]"',
            "graphify agents install",
        ],
        "verify_commands": ["graphify --help"],
        "publicly_available": True,
        "notes": "The official package is graphifyy with two y characters; the command is graphify.",
    },
    {
        "id": "agentgraph",
        "name": "AgentGraph",
        "tier": "optional",
        "required": False,
        "capability": "AgentReady-compatible repository graph and gap-report provider.",
        "check": {"kind": "command", "commands": ["agentgraph"]},
        "download_url": None,
        "install_commands": [],
        "verify_commands": ["agentgraph --help"],
        "publicly_available": False,
        "notes": (
            "No public AgentGraph distribution is currently available. It is not required for AgentReady; "
            "use Graphify or another MCP-compatible graph provider unless a trusted AgentGraph package is supplied."
        ),
    },
    {
        "id": "qdrant-mcp",
        "name": "Qdrant MCP server",
        "tier": "optional",
        "required": False,
        "capability": "Optional semantic-memory store for MCP-capable AI clients.",
        "check": {"kind": "command", "commands": ["mcp-server-qdrant"]},
        "download_url": "https://github.com/qdrant/mcp-server-qdrant",
        "install_commands": ["uv tool install mcp-server-qdrant"],
        "verify_commands": ["mcp-server-qdrant --help"],
        "publicly_available": True,
        "notes": "Use QDRANT_LOCAL_PATH for local storage or configure an explicit QDRANT_URL.",
    },
    {
        "id": "ollama",
        "name": "Ollama",
        "tier": "optional",
        "required": False,
        "capability": "Optional local-model enrichment for capture summaries and Graphify.",
        "check": {"kind": "command", "commands": ["ollama"]},
        "download_url": "https://ollama.com/download/windows",
        "install_commands": [],
        "verify_commands": ["ollama --version", "ollama list"],
        "publicly_available": True,
        "notes": "Models are separate downloads and can require tens to hundreds of gigabytes.",
    },
    {
        "id": "docker",
        "name": "Docker Desktop",
        "tier": "optional",
        "required": False,
        "capability": "Optional container runtime for a local Qdrant server or other user-selected services.",
        "check": {"kind": "command", "commands": ["docker"]},
        "download_url": "https://docs.docker.com/desktop/setup/install/windows-install/",
        "install_commands": [],
        "verify_commands": ["docker version"],
        "publicly_available": True,
        "notes": "Review Docker Desktop licensing and run local services on loopback unless exposure is intentional.",
    },
    {
        "id": "toolbox-extra",
        "name": "AgentReady toolbox extra",
        "tier": "development",
        "required": False,
        "capability": "DuckDB, NetworkX, pandas, SymPy, and Z3 deterministic/data tools.",
        "check": {
            "kind": "modules",
            "modules": ["duckdb", "networkx", "pandas", "sympy", "z3"],
        },
        "packages": [
            "duckdb==1.5.3",
            "networkx==3.6.1",
            "pandas==3.0.3",
            "sympy==1.14.0",
            "z3-solver==4.16.0.0",
        ],
        "download_url": None,
        "install_commands": ["uv sync --frozen --extra toolbox"],
        "verify_commands": ["uv run agentready tool-context"],
        "publicly_available": True,
    },
    {
        "id": "development-tools",
        "name": "AgentReady development tools",
        "tier": "development",
        "required": False,
        "capability": "Tests, linting, type checking, coverage, build, and security analysis.",
        "check": {
            "kind": "modules",
            "modules": ["pytest", "ruff", "pyright", "coverage", "build", "bandit"],
        },
        "packages": [
            "bandit>=1.8",
            "build>=1.2",
            "coverage>=7.10",
            "pyright>=1.1",
            "pytest>=8.4",
            "ruff>=0.12",
        ],
        "download_url": None,
        "install_commands": ["uv sync --frozen --group dev"],
        "verify_commands": ["uv run pytest --version", "uv run ruff --version", "uv run pyright --version"],
        "publicly_available": True,
    },
)


def _selected_tiers(profile: str) -> set[str]:
    if profile == "core":
        return {"core"}
    if profile == "recommended":
        return {"core", "recommended"}
    if profile == "development":
        return {"core", "development"}
    if profile == "full":
        return {"core", "recommended", "optional", "development"}
    raise ValueError(f"unknown prerequisite profile: {profile}")


def _check(entry: dict[str, Any]) -> tuple[bool, str]:
    check = entry["check"]
    kind = check["kind"]
    if kind == "platform":
        expected = str(check["platform"])
        return sys.platform == expected, sys.platform
    if kind == "python":
        minimum = tuple(check["minimum"])
        found = sys.version_info[:2]
        return found >= minimum, f"{found[0]}.{found[1]}.{sys.version_info.micro}"
    if kind == "command":
        found = [shutil.which(command) for command in check["commands"]]
        installed = all(found)
        return installed, ", ".join(path or "not found" for path in found)
    if kind == "modules":
        missing = [module for module in check["modules"] if importlib.util.find_spec(module) is None]
        return not missing, "available" if not missing else f"missing: {', '.join(missing)}"
    raise ValueError(f"unsupported prerequisite check kind: {kind}")


def build_report(profile: str = "recommended", *, strict: bool = False) -> dict[str, Any]:
    """Return prerequisite availability without installing or changing anything."""
    tiers = _selected_tiers(profile)
    entries: list[dict[str, Any]] = []
    for source in CATALOG:
        if source["tier"] not in tiers:
            continue
        installed, detail = _check(source)
        entry = {key: value for key, value in source.items() if key != "check"}
        entry.update({"installed": installed, "check_detail": detail})
        entries.append(entry)
    blocking = [
        entry["id"]
        for entry in entries
        if not entry["installed"] and (entry["required"] or strict)
    ]
    return {
        "schema": SCHEMA,
        "profile": profile,
        "strict": strict,
        "overall": "PASS" if not blocking else "FAIL",
        "blocking": blocking,
        "summary": {
            "selected": len(entries),
            "installed": sum(1 for entry in entries if entry["installed"]),
            "missing": sum(1 for entry in entries if not entry["installed"]),
        },
        "entries": entries,
    }


def print_human(report: dict[str, Any]) -> None:
    print(f"AgentReady prerequisites: {report['overall']} (profile={report['profile']})")
    for entry in report["entries"]:
        status = "INSTALLED" if entry["installed"] else "MISSING"
        requirement = "required" if entry["required"] else entry["tier"]
        print(f"- {entry['name']}: {status} [{requirement}]")
        print(f"  Purpose: {entry['capability']}")
        if entry.get("download_url"):
            print(f"  Download: {entry['download_url']}")
        for command in entry.get("install_commands", []):
            print(f"  Install: {command}")
        if entry.get("notes"):
            print(f"  Note: {entry['notes']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "agent-prerequisites",
        description="List and check AgentReady core, companion, optional, and development prerequisites.",
    )
    parser.add_argument("--profile", choices=PROFILES, default="recommended")
    parser.add_argument("--strict", action="store_true", help="Treat every missing item in the profile as blocking.")
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable JSON document.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(args.profile, strict=args.strict)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
