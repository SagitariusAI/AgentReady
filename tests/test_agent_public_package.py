# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from agent_public_package import build
from agent_publication_guard import PYTHON_HEADER, scan_archive, scan_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "AgentReady Test")
    _git(repo, "config", "user.email", "agentready-test@example.invalid")
    (repo / "README.md").write_text("# Safe public source\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "Initial public source")
    return repo


def test_package_is_exact_head_and_contains_no_database(tmp_path: Path):
    repo = _repo(tmp_path)
    out = tmp_path / "out"
    manifest = build(repo, out)
    archive = out / str(manifest["archive"])

    assert manifest["git_head"] == _git(repo, "rev-parse", "HEAD")
    assert manifest["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert scan_archive(archive)[0] == []
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert names == ["README.md", "SOURCE-MANIFEST.json"]
        source_manifest = json.loads(bundle.read("SOURCE-MANIFEST.json"))
    assert source_manifest["git_head"] == manifest["git_head"]
    assert source_manifest["files"][0]["path"] == "README.md"
    assert not any(Path(name).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".duckdb"} for name in names)


def test_package_refuses_dirty_worktree(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dirty working tree"):
        build(repo, tmp_path / "out")


@pytest.mark.parametrize(
    "relative",
    [
        "seed.db",
        "runtime/state.sqlite3",
        "datasets/training.jsonl",
        "logs/agent.log",
    ],
)
def test_guard_rejects_database_and_prepopulated_runtime_payloads(tmp_path: Path, relative: str):
    repo = _repo(tmp_path)
    payload = repo / relative
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text("prepopulated", encoding="utf-8")
    findings, _ = scan_source(repo)
    assert findings
    assert any(item.category in {"persistence_payload", "runtime_path"} for item in findings)


def test_guard_requires_canonical_header_on_python_files(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "missing_header.py").write_text("VALUE = 1\n", encoding="utf-8")
    findings, _ = scan_source(repo)
    assert any(item.category == "python_header" for item in findings)

    (repo / "missing_header.py").write_text(PYTHON_HEADER + "\nVALUE = 1\n", encoding="utf-8")
    findings, _ = scan_source(repo)
    assert not any(item.category == "python_header" for item in findings)


def test_guard_rejects_escaped_paths_private_assets_and_real_email(tmp_path: Path):
    repo = _repo(tmp_path)
    private_name = "Cer" + "berus"
    escaped_path = "D:" + "\\\\" + "AgentReady" + "\\\\" + "config"
    real_email = "person@" + "samplemail.com"
    (repo / "unsafe.py").write_text(
        PYTHON_HEADER
        + "\n"
        + f"PRIVATE_NAME = {private_name!r}\n"
        + f"PRIVATE_PATH = {escaped_path!r}\n"
        + f"CONTACT = {real_email!r}\n",
        encoding="utf-8",
    )
    findings, _ = scan_source(repo)
    categories = {item.category for item in findings}
    assert {"private_asset", "production_path", "email_address"} <= categories
