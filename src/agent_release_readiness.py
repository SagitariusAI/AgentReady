from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _argv(command: list[str]) -> list[str]:
    resolved = shutil.which(command[0]) or command[0]
    if os.name == "nt" and Path(resolved).suffix.casefold() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline([resolved, *command[1:]])]
    return [resolved, *command[1:]]


def run_check(
    name: str,
    command: list[str],
    *,
    repo: Path,
    log_path: Path | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        _argv(command),
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    return {
        "name": name,
        "exit_code": int(completed.returncode),
        "log_path": str(log_path) if log_path else "",
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
    manifest_path = out_dir / "security" / "security-manifest.json"
    try:
        security_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        security_manifest = None
    payload = {
        "schema": "agentready.release_readiness.v1",
        "generated_at": now_iso(),
        "repo": str(repo),
        "security_manifest": str(manifest_path),
        "checks": checks,
        **build_verdict(checks, security_manifest),
    }
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# AgentReady Release Readiness",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Repo: `{repo}`",
        f"- Overall: `{payload['overall']}`",
        f"- Failed checks: `{payload['failed_checks']}`",
        f"- Security failures: `{payload['security_failures']}`",
        f"- Security timeouts: `{payload['security_timeouts']}`",
        "",
        "| Check | Exit | Log |",
        "| --- | ---: | --- |",
    ]
    lines.extend(
        f"| {check['name']} | {check['exit_code']} | `{check['log_path']}` |"
        for check in checks
    )
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def run_release_readiness(repo: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    checks = [
        run_check("stack-check", ["agent-stack-check"], repo=repo, log_path=out_dir / "tool-availability.txt"),
        run_check("gap-report", ["agent-gap-report", "-Repo", str(repo), "-OutDir", str(out_dir / "gap")], repo=repo),
        run_check("vault-code-separation", ["agent-vault-code-separation", "-Repo", str(repo)], repo=repo),
        run_check("sbom", ["agent-sbom", "-Repo", str(repo), "-OutDir", str(out_dir / "sbom")], repo=repo),
        run_check(
            "security-scan",
            ["agent-security-scan", "-Repo", str(repo), "-OutDir", str(out_dir / "security")],
            repo=repo,
        ),
    ]
    (out_dir / "git-status.txt").write_text(
        subprocess.run(["git", "status", "--short"], cwd=str(repo), capture_output=True, text=True, check=False).stdout,
        encoding="utf-8",
    )
    (out_dir / "git-head.txt").write_text(
        subprocess.run(["git", "log", "-1", "--oneline"], cwd=str(repo), capture_output=True, text=True, check=False).stdout,
        encoding="utf-8",
    )
    return write_report(repo, out_dir, checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical AgentReady release-readiness evidence.")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / ".agent-reports" / "release-readiness"
    payload = run_release_readiness(repo, out_dir)
    print(f"Release readiness report written to {out_dir}")
    return 0 if payload["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
