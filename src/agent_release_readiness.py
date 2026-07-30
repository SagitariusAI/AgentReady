"""Exact-commit release-readiness evidence for the public AgentReady distribution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_publication_guard import scan_archive


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _check(name: str, ok: bool, detail: str, evidence: Path | str = "") -> dict[str, Any]:
    return {
        "name": name,
        "exit_code": 0 if ok else 1,
        "detail": detail,
        "log_path": str(evidence),
    }


def build_verdict(checks: list[dict[str, Any]], security_manifest: dict[str, Any] | None) -> dict[str, Any]:
    failed_checks = sum(1 for check in checks if int(check.get("exit_code") or 0) != 0)
    if security_manifest is None:
        security_failures, security_timeouts = 1, 0
    else:
        security_failures = int(security_manifest.get("failures") or 0)
        security_timeouts = int(security_manifest.get("timeouts") or 0)
    overall = "FAIL" if failed_checks or security_failures or security_timeouts else "PASS"
    return {
        "overall": overall,
        "failed_checks": failed_checks,
        "security_failures": security_failures,
        "security_timeouts": security_timeouts,
    }


def write_report(repo: Path, out_dir: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical_security = repo / ".agent-reports" / "security" / "security-manifest.json"
    fixture_security = out_dir / "security" / "security-manifest.json"
    manifest_path = canonical_security if canonical_security.exists() else fixture_security
    security_manifest = _load_json(manifest_path)
    head = _git(repo, "rev-parse", "HEAD")
    payload = {
        "schema": "agentready.public_release_readiness.v1",
        "generated_at": now_iso(),
        "repo": str(repo),
        "git_head": head or None,
        "security_manifest": str(manifest_path),
        "checks": checks,
        **build_verdict(checks, security_manifest),
    }
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# AgentReady Public Release Readiness",
        "",
        f"- Git head: `{payload['git_head']}`",
        f"- Overall: `{payload['overall']}`",
        "",
        "| Check | Status | Detail | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {item['name']} | {'PASS' if item['exit_code'] == 0 else 'FAIL'} | "
        f"{str(item.get('detail', '')).replace('|', '/')} | `{item.get('log_path', '')}` |"
        for item in checks
    )
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def run_release_readiness(repo: Path, out_dir: Path) -> dict[str, Any]:
    reports = repo / ".agent-reports"
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    checks = [_check("git-clean", bool(head) and not status, "exact committed tree is clean")]

    ci_logs = sorted((reports / "ci").glob("agent-ci-local-*.log"))
    ci_log = ci_logs[-1] if ci_logs else None
    ci_text = ci_log.read_text(encoding="utf-8", errors="replace") if ci_log else ""
    ci_ok = bool(ci_log) and re.search(r"EXIT .+ = [1-9]\d*", ci_text) is None
    checks.append(_check("local-ci", ci_ok, "latest local CI has no nonzero exits", ci_log or ""))

    security_path = reports / "security" / "security-manifest.json"
    security = _load_json(security_path)
    security_ok = bool(security) and security.get("overall") == "PASS"
    checks.append(_check("security", security_ok, "security manifest is PASS", security_path))

    guard_path = reports / "publication-guard" / "latest.json"
    guard = _load_json(guard_path)
    guard_ok = bool(guard) and guard.get("overall") == "PASS" and guard.get("git_head") == head
    checks.append(_check("publication-guard", guard_ok, "guard PASS is bound to HEAD", guard_path))

    package_path = reports / "package-public" / "package-manifest.json"
    package = _load_json(package_path)
    package_data = package or {}
    archive = reports / "package-public" / str(package_data.get("archive", ""))
    package_ok = bool(package) and package_data.get("git_head") == head and archive.is_file()
    if package_ok:
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive_findings, archive_count = scan_archive(archive)
        package_ok = (
            digest == package_data.get("archive_sha256")
            and not archive_findings
            and archive_count == package_data.get("archive_file_count")
        )
    checks.append(_check("public-package", package_ok, "archive hash, inventory, guard, and HEAD agree", package_path))
    return write_report(repo, out_dir, checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build public AgentReady release-readiness evidence.")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / ".agent-reports" / "release-readiness"
    payload = run_release_readiness(repo, out_dir)
    print(f"AgentReady public release readiness: {payload['overall']} {out_dir / 'latest.json'}")
    return 0 if payload["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
