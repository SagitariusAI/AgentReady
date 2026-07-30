# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Prerequisite catalog and machine-readable preflight contracts."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import agent_prerequisites as prerequisites


def _commands_present(monkeypatch, missing: set[str] | None = None) -> None:
    missing = missing or set()
    monkeypatch.setattr(
        prerequisites.shutil,
        "which",
        lambda command: None if command in missing else f"C:\\tools\\{command}.exe",
    )


def test_core_profile_passes_when_required_commands_exist(monkeypatch) -> None:
    _commands_present(monkeypatch)
    report = prerequisites.build_report("core")
    assert report["overall"] == "PASS"
    assert report["blocking"] == []
    assert [entry["id"] for entry in report["entries"]] == ["windows", "python", "git", "uv"]


def test_missing_required_command_blocks_core(monkeypatch) -> None:
    _commands_present(monkeypatch, {"git"})
    report = prerequisites.build_report("core")
    assert report["overall"] == "FAIL"
    assert report["blocking"] == ["git"]


def test_missing_optional_tools_do_not_block_unless_strict(monkeypatch) -> None:
    _commands_present(monkeypatch, {"pwsh", "serena", "graphify", "agentgraph", "mcp-server-qdrant", "ollama", "docker"})
    normal = prerequisites.build_report("full")
    strict = prerequisites.build_report("full", strict=True)
    assert normal["overall"] == "PASS"
    assert strict["overall"] == "FAIL"
    assert "agentgraph" in strict["blocking"]


def test_catalog_identifies_public_and_unavailable_companions() -> None:
    by_id = {entry["id"]: entry for entry in prerequisites.CATALOG}
    assert by_id["serena"]["install_commands"][0] == "uv tool install -p 3.13 serena-agent"
    assert by_id["graphify"]["install_commands"][0] == 'uv tool install "graphifyy[mcp]"'
    assert by_id["agentgraph"]["publicly_available"] is False
    assert by_id["agentgraph"]["download_url"] is None


def test_json_cli_contract(monkeypatch, capsys) -> None:
    _commands_present(monkeypatch)
    assert prerequisites.main(["--profile", "recommended", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentready.prerequisites.v1"
    assert payload["profile"] == "recommended"
    assert {entry["id"] for entry in payload["entries"]} >= {"python", "git", "uv", "serena", "graphify"}


def test_python_package_lists_match_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in prerequisites.CATALOG}
    assert by_id["toolbox-extra"]["packages"] == project["project"]["optional-dependencies"]["toolbox"]
    assert by_id["development-tools"]["packages"] == project["dependency-groups"]["dev"]
