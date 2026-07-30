# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_report_contract import normalize_report

SKIP_DIRS = [
    ".agent-reports",
    ".agent-state",
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "cache",
    "coordination",
    "code-graph/mirrors",
    "credentials",
    "data",
    "dist",
    "node_modules",
    "obsidian-vault",
    "opt",
    "programdata",
    "reports",
    "services/data",
    "src/scip",
    "src/shim",
    "worktrees",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def external_tool_env() -> dict[str, str]:
    """Return an environment safe for non-AgentReady scanner subprocesses."""
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if upper.startswith("PYTHON") or upper in {"UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV"}:
            env.pop(key, None)
    # Semgrep is a Python application. On Windows it otherwise inherits the
    # active ANSI code page and can write JSON containing non-UTF-8 bytes,
    # which makes an otherwise successful report unreadable to release gates.
    env["PYTHONUTF8"] = "1"
    return env


OSV_LOCKFILE_NAMES = {
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "go.mod",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "packages.lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}


def is_osv_dependency_source(name: str) -> bool:
    """Return inputs OSV can inspect directly, including pip requirements files."""
    folded = name.casefold()
    return folded in OSV_LOCKFILE_NAMES or (
        folded.startswith("requirements") and folded.endswith(".txt")
    )


def discover_osv_lockfiles(repo: Path) -> list[Path]:
    """Return supported lockfiles without asking OSV v2 to walk Windows roots."""
    found: list[Path] = []
    skip_paths = {Path(name).as_posix().casefold().strip("/") for name in SKIP_DIRS}
    for root, dirs, files in os.walk(repo):
        root_path = Path(root)
        kept: list[str] = []
        for name in dirs:
            relative = (root_path / name).relative_to(repo).as_posix().casefold()
            if any(relative == skip or relative.startswith(skip + "/") for skip in skip_paths):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in files:
            if is_osv_dependency_source(name):
                found.append(Path(root) / name)
    return sorted(found, key=lambda path: str(path).casefold())


def run_security_tool(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    output_paths: list[Path] | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> dict[str, Any]:
    output_paths = output_paths or []
    stale_removed: list[str] = []
    for path in output_paths:
        if path.exists():
            path.unlink()
            stale_removed.append(str(path))
    started = now_iso()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=external_tool_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        timed_out = False
        exit_code = int(completed.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout: str = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else bytes(exc.stdout or b"").decode(errors="replace")
        )
        stderr: str = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else bytes(exc.stderr or b"").decode(errors="replace")
        )
        stdout = str(stdout)
        stdout += f"\nTIMEOUT {name} exceeded {timeout_seconds} seconds.\n"
        timed_out = True
        exit_code = 124

    finished = now_iso()
    if stdout_path and not timed_out:
        stdout_path.write_text(stdout, encoding="utf-8")
    if stderr_path and not timed_out:
        stderr_path.write_text(stderr, encoding="utf-8")
    if timed_out:
        for path in output_paths:
            if path.exists():
                path.unlink()
    combined = stdout
    if stderr:
        combined += ("\n" if combined else "") + stderr
    log_path.write_text(combined, encoding="utf-8")

    return {
        "name": name,
        "command": command,
        "started_at": started,
        "finished_at": finished,
        "timeout_seconds": timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "log_path": str(log_path),
        "stdout_path": str(stdout_path) if stdout_path else "",
        "stderr_path": str(stderr_path) if stderr_path else "",
        "output_paths": [str(path) for path in output_paths],
        "outputs_present": {str(path): path.exists() for path in output_paths},
        "stale_removed": stale_removed,
    }


def resolve_command(command: str) -> str | None:
    resolved = shutil.which(command)
    if resolved:
        return resolved
    probe = subprocess.run(["where.exe", command], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return None
    first = (probe.stdout or "").splitlines()[0].strip()
    return first or None


def build_steps(out_dir: Path, repo: Path | None = None) -> list[dict[str, Any]]:
    gitleaks_json = out_dir / "gitleaks.json"
    osv_json = out_dir / "osv-scanner.json"
    trivy_json = out_dir / "trivy-fs.json"
    grype_json = out_dir / "grype.json"
    semgrep_json = out_dir / "semgrep.json"

    # OSV Scanner 2.4 can collapse an absolute Windows repo path to the drive
    # root during recursive source walking. Pass each discovered lockfile
    # explicitly, which is also the precise release-evidence boundary.
    osv_args = [
        "osv-scanner",
        "scan",
        "source",
        "--no-resolve",
        "--allow-no-lockfiles",
    ]
    osv_lockfiles = discover_osv_lockfiles(repo) if repo else []
    for lockfile in osv_lockfiles:
        osv_args.extend(["--lockfile", str(lockfile)])
    osv_args.extend(["--format", "json"])

    # --timeout 15m: the misconfig/helm analyzer on a large repo exceeds trivy's
    # default 5m deadline ("context deadline exceeded"), failing the whole scan
    # even though vuln+secret completed. Trivy's own recommendation is a higher
    # timeout. This is a scanner-runtime bound, not a finding threshold.
    trivy_args = ["trivy", "fs", "--scanners", "vuln,secret,misconfig", "--timeout", "15m"]
    for skip_dir in SKIP_DIRS:
        trivy_args.extend(["--skip-dirs", skip_dir])
    # Trivy's literal "__pycache__" directory skip does not match nested
    # caches on Windows. Generated bytecode can contain test fixture strings
    # that look like secrets, so exclude the generated artifact formats rather
    # than suppressing any secret rule or result.
    trivy_args.extend(["--skip-dirs", "**/__pycache__"])
    trivy_args.extend(["--skip-files", "**/*.pyc", "--skip-files", "**/*.pyo"])
    trivy_args.extend(["--format", "json", "--output", str(trivy_json), "."])

    grype_args = ["grype", "dir:."]
    for skip_dir in SKIP_DIRS:
        grype_args.extend(["--exclude", f"./{skip_dir}/**"])
    for local_tool in ("scip.exe", "scip-python.exe", "scip-typescript.exe"):
        grype_args.extend(["--exclude", f"./bin/{local_tool}"])
    grype_args.extend(["-o", "json"])

    semgrep_args = ["semgrep", "scan", "--config", "auto"]
    for skip_dir in SKIP_DIRS:
        semgrep_args.extend(["--exclude", skip_dir])
    semgrep_args.extend(["--json", "--output", str(semgrep_json)])

    gitleaks_args = ["gitleaks", "detect", "--source", ".", "--no-banner", "--redact"]
    if repo and (repo / ".gitleaks.toml").is_file():
        gitleaks_args.extend(["--config", str(repo / ".gitleaks.toml")])
    gitleaks_args.extend(["--report-format", "json", "--report-path", str(gitleaks_json)])

    return [
        {
            "name": "gitleaks",
            "command": gitleaks_args,
            "log_path": out_dir / "gitleaks.txt",
            "output_paths": [gitleaks_json],
        },
        {
            "name": "osv-scanner",
            "command": osv_args,
            "skip_reason": "no supported dependency lockfiles found" if repo and not osv_lockfiles else "",
            "log_path": out_dir / "osv-scanner.txt",
            "stdout_path": osv_json,
            "stderr_path": out_dir / "osv-scanner.txt",
            "output_paths": [osv_json],
        },
        {
            "name": "trivy",
            "command": trivy_args,
            "log_path": out_dir / "trivy-fs.txt",
            "output_paths": [trivy_json],
        },
        {
            "name": "grype",
            "command": grype_args,
            "log_path": out_dir / "grype.txt",
            "stdout_path": grype_json,
            "stderr_path": out_dir / "grype.txt",
            "output_paths": [grype_json],
        },
        {
            "name": "semgrep",
            "command": semgrep_args,
            "log_path": out_dir / "semgrep.txt",
            "output_paths": [semgrep_json],
        },
    ]


_HTTP_URL = re.compile(r"http://[^\s\"')]+", re.IGNORECASE)


def _is_local_http(url: str) -> bool:
    hostname = urlsplit(url).hostname
    if not hostname:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def adjudicate_semgrep(repo: Path, path: Path) -> dict[str, Any]:
    """Adjudicate only findings carrying narrow, source-verifiable evidence.

    Insecure cleartext transport is accepted only when every HTTP literal in
    the matched source file targets loopback, link-local, or RFC1918 space.
    Dynamic urllib audit findings are accepted only when the exact reported
    line contains the explicit ``# nosec B310`` review marker. Everything else
    remains unresolved and fails the scan.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = list(payload.get("results") or [])
    accepted: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for finding in results:
        rule_id = str(finding.get("check_id") or "")
        relative = str(finding.get("path") or "")
        source_path = repo / relative
        source = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
        start = finding.get("start") if isinstance(finding.get("start"), dict) else {}
        line_number = int(start.get("line") or 0)
        source_lines = source.splitlines()
        matched_line = source_lines[line_number - 1] if 0 < line_number <= len(source_lines) else ""
        row = {"rule_id": rule_id, "path": relative, "line": str(line_number)}
        urls = _HTTP_URL.findall(source)
        if "insecure-transport" in rule_id and urls and all(_is_local_http(url) for url in urls):
            row["reason"] = "all HTTP literals in source target loopback, link-local, or RFC1918 space"
            accepted.append(row)
        elif "dynamic-urllib-use-detected" in rule_id and "# nosec B310" in matched_line:
            row["reason"] = "exact audited urllib call carries explicit B310 review marker"
            accepted.append(row)
        else:
            unresolved.append(row)
    return {
        "schema_version": 1,
        "raw_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "policy": (
            "insecure HTTP only when every source-file HTTP literal is loopback/link-local/RFC1918; "
            "dynamic urllib only with an exact-line # nosec B310 review marker"
        ),
        "accepted": accepted,
        "unresolved": unresolved,
        "accepted_count": len(accepted),
        "unresolved_count": len(unresolved),
    }


def write_manifest(repo: Path, out_dir: Path, results: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fail = sum(1 for result in results if result["exit_code"] not in {0})
    timeouts = sum(1 for result in results if result["timed_out"])
    payload = {
        "generated_at": now_iso(),
        "repo": str(repo),
        "overall": "FAIL" if fail else "PASS",
        "failures": fail,
        "timeouts": timeouts,
        "results": results,
    }
    manifest = out_dir / "security-manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# AgentReady Security Scan",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Repo: `{repo}`",
        f"- Overall: **{payload['overall']}**",
        f"- Failures: {fail}",
        f"- Timeouts: {timeouts}",
        "",
        "| Tool | Exit | Timed out | Log |",
        "| --- | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(f"| {result['name']} | {result['exit_code']} | {result['timed_out']} | `{result['log_path']}` |")
    md_path = out_dir / "security-manifest.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    normalize_report(
        repo=repo,
        surface="security",
        report_dir=out_dir,
        primary=manifest,
        status="fail" if fail else "ok",
        summary=f"{len(results)} security tool(s) completed with {fail} failure(s) and {timeouts} timeout(s).",
    )
    return manifest


def run_scan(repo: Path, out_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for step in build_steps(out_dir, repo):
        name = str(step["name"])
        skip_reason = str(step.get("skip_reason") or "")
        if skip_reason:
            log_path = Path(step["log_path"])
            stdout_path = Path(step["stdout_path"])
            payload = {"results": [], "scan_status": "skipped", "reason": skip_reason}
            stdout_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            log_path.write_text(f"SKIP {name}: {skip_reason}\n", encoding="utf-8")
            stamp = now_iso()
            results.append(
                {
                    "name": name,
                    "command": step["command"],
                    "started_at": stamp,
                    "finished_at": stamp,
                    "timeout_seconds": timeout_seconds,
                    "timed_out": False,
                    "exit_code": 0,
                    "log_path": str(log_path),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(step.get("stderr_path") or ""),
                    "output_paths": [str(path) for path in step.get("output_paths", [])],
                    "outputs_present": {str(stdout_path): True},
                    "stale_removed": [],
                    "skipped": True,
                    "skip_reason": skip_reason,
                }
            )
            continue
        executable = str(step["command"][0])
        resolved = resolve_command(executable)
        if not resolved:
            log_path = Path(step["log_path"])
            log_path.write_text(f"SKIP {name}: command not found: {executable}\n", encoding="utf-8")
            results.append(
                {
                    "name": name,
                    "command": step["command"],
                    "started_at": now_iso(),
                    "finished_at": now_iso(),
                    "timeout_seconds": timeout_seconds,
                    "timed_out": False,
                    "exit_code": 127,
                    "log_path": str(log_path),
                    "stdout_path": "",
                    "stderr_path": "",
                    "output_paths": [str(path) for path in step.get("output_paths", [])],
                    "outputs_present": {str(path): False for path in step.get("output_paths", [])},
                    "stale_removed": [],
                }
            )
            continue
        command = list(step["command"])
        command[0] = resolved
        result = run_security_tool(
                name=name,
                command=command,
                cwd=repo,
                log_path=Path(step["log_path"]),
                timeout_seconds=timeout_seconds,
                output_paths=list(step.get("output_paths", [])),
                stdout_path=step.get("stdout_path"),
                stderr_path=step.get("stderr_path"),
            )
        if name == "semgrep" and not result["timed_out"] and Path(step["output_paths"][0]).is_file():
            adjudication = adjudicate_semgrep(repo, Path(step["output_paths"][0]))
            adjudication_path = out_dir / "semgrep-adjudication.json"
            adjudication_path.write_text(json.dumps(adjudication, indent=2) + "\n", encoding="utf-8")
            result["semgrep_adjudication"] = str(adjudication_path)
            result["accepted_findings"] = adjudication["accepted_count"]
            result["unresolved_findings"] = adjudication["unresolved_count"]
            if result["exit_code"] == 0 and adjudication["unresolved_count"]:
                result["exit_code"] = 1
        results.append(result)
    manifest = write_manifest(repo, out_dir, results)
    return {"manifest": str(manifest), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded AgentReady security scans.")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--tool-timeout-seconds", type=int, default=480)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / ".agent-reports" / "security"
    result = run_scan(repo, out_dir, max(1, args.tool_timeout_seconds))
    print(f"Security scan written to {out_dir}")
    print(f"Security manifest: {result['manifest']}")
    return 1 if any(item["exit_code"] != 0 for item in result["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
