# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Truth checks for the public deployment and operating manual."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "USER_MANUAL.md"


def test_manual_covers_every_installed_console_command() -> None:
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    text = MANUAL.read_text(encoding="utf-8")
    missing = [name for name in scripts if f"`{name}`" not in text]
    assert missing == []


def test_manual_documents_deterministic_agent_contract() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    for required in ("--mode agent", "--yes", "--json", "--dry-run", "PLANNED", "PASS"):
        assert required in text
    assert "--capture-dir" not in text
    assert "fleet deploy" not in text
    assert "PREREQUISITES.md" in text
    assert "--prerequisites-only" in text


def test_prerequisite_download_list_covers_companion_stack() -> None:
    text = (ROOT / "docs" / "PREREQUISITES.md").read_text(encoding="utf-8")
    for name in ("Serena", "Graphify", "AgentGraph", "Qdrant", "Ollama", "Docker Desktop"):
        assert name in text
    assert "no public AgentGraph distribution" in text
    assert "agentready.prerequisites.v1" in text


def test_all_local_markdown_links_resolve() -> None:
    failures = []
    for document in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (document.parent / relative).resolve().exists():
                failures.append(f"{document.relative_to(ROOT)} -> {target}")
    assert failures == []
