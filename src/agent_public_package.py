# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Build a deterministic, commit-bound public AgentReady source archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from agent_publication_guard import scan_archive, scan_source


def _git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict").strip()


def _tracked_files(repo: Path) -> list[str]:
    raw = _git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD", binary=True)
    if not isinstance(raw, bytes):
        raise TypeError("git tree inventory must be returned as bytes")
    return sorted(item for item in raw.decode("utf-8").split("\0") if item)


def _blob(repo: Path, path: str) -> bytes:
    data = _git(repo, "show", f"HEAD:{path}", binary=True)
    if not isinstance(data, bytes):
        raise TypeError("git blob must be returned as bytes")
    return data


def _project_version(repo: Path) -> str:
    pyproject = tomllib.loads(_blob(repo, "pyproject.toml").decode("utf-8", errors="strict"))
    version = pyproject.get("project", {}).get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!-]*", version):
        raise RuntimeError("pyproject.toml must define a filename-safe project.version")
    return version


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(repo: Path, out_dir: Path) -> dict[str, object]:
    status = _git(repo, "status", "--porcelain")
    if status:
        raise RuntimeError("refusing to package a dirty working tree")
    source_findings, _ = scan_source(repo)
    if source_findings:
        raise RuntimeError(f"publication guard found {len(source_findings)} source finding(s)")

    head = str(_git(repo, "rev-parse", "HEAD"))
    version = _project_version(repo)
    archive = out_dir / f"AgentReady-{version}-source.zip"
    files = _tracked_files(repo)
    inventory: list[dict[str, object]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            data = _blob(repo, path)
            inventory.append({"path": path, "sha256": _sha256(data), "bytes": len(data)})
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
        source_manifest = {
            "schema": "agentready.source_manifest.v1",
            "git_head": head,
            "files": inventory,
        }
        data = json.dumps(source_manifest, indent=2, sort_keys=True).encode("utf-8")
        info = zipfile.ZipInfo("SOURCE-MANIFEST.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        bundle.writestr(info, data)

    archive_findings, archive_file_count = scan_archive(archive)
    if archive_findings:
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"publication guard found {len(archive_findings)} archive finding(s)")
    archive_bytes = archive.read_bytes()
    manifest = {
        "schema": "agentready.package_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "version": version,
        "archive": archive.name,
        "archive_sha256": _sha256(archive_bytes),
        "archive_bytes": len(archive_bytes),
        "archive_file_count": archive_file_count,
        "tracked_file_count": len(files),
        "inventory_sha256": _sha256(json.dumps(inventory, sort_keys=True).encode("utf-8")),
    }
    (out_dir / "package-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the public AgentReady source package.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    out_dir = args.out_dir or repo / ".agent-reports" / "package-public"
    try:
        manifest = build(repo, out_dir.resolve())
    except (OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f"AgentReady public package: FAIL: {exc}")
        return 1
    print(
        "AgentReady public package: PASS "
        f"{manifest['archive']} sha256={manifest['archive_sha256']} head={manifest['git_head']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
