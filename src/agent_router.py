"""Deterministic tool routing for the public AgentReady command surface."""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

MODULE_FALLBACKS = {
    "agent-bootstrap-repo": "agent_bootstrap_repo",
    "agent-ci-local": "agent_ci_local",
    "agent-coordination": "agent_coordination.cli",
    "agent-governance-detectors": "agent_governance_detectors",
    "agent-package-public": "agent_public_package",
    "agent-publication-guard": "agent_publication_guard",
    "agent-release-readiness": "agent_release_readiness",
    "agent-release-scorecard": "agent_release_scorecard",
    "agent-report-contract": "agent_report_contract",
    "agent-security-scan": "agent_security_scan",
    "agent-tool-context": "agent_tool_context",
}


def step(command: str, reason: str, report: str = "", heavy: bool = False) -> dict[str, object]:
    return {"command": command, "reason": reason, "report": report, "heavy": heavy}


COMMON = [
    step("agent-tool-context", "Inspect the installed public command surface."),
    step("agent-coordination task-status", "Read current task and claim state."),
    step("agent-governance-detectors", "Check repository governance markers and boundaries."),
]
DISCOVER: list[dict[str, object]] = []
CHANGE = [
    step("agent-ci-local", "Run repository-aware local CI.", ".agent-reports/ci/latest.json"),
]
SECURITY = [
    step("agent-security-scan", "Run configured local security scanners.", ".agent-reports/security/security-manifest.json"),
    step(
        "agent-publication-guard",
        "Reject credentials, private topology, runtime databases, datasets, and machine-specific state.",
        ".agent-reports/publication-guard/latest.json",
    ),
]
RELEASE = [
    *CHANGE,
    *SECURITY,
    step(
        "agent-package-public",
        "Build a commit-bound public source archive and manifest.",
        ".agent-reports/package-public/package-manifest.json",
        heavy=True,
    ),
    step(
        "agent-release-readiness",
        "Combine exact release evidence.",
        ".agent-reports/release-readiness/latest.json",
    ),
    step(
        "agent-release-scorecard",
        "Produce the final local release verdict.",
        ".agent-reports/release-scorecard/latest.json",
    ),
]
PROFILES: dict[str, list[dict[str, object]]] = {
    "discover": [*COMMON, *DISCOVER],
    "change": [*COMMON, *DISCOVER, *CHANGE],
    "debug": [*COMMON, *DISCOVER, *CHANGE],
    "dependency": [*COMMON, *DISCOVER, *SECURITY, *CHANGE],
    "security": [*COMMON, *DISCOVER, *SECURITY],
    "release": [*COMMON, *DISCOVER, *RELEASE],
    "services": [*COMMON, *DISCOVER],
    "full": [*COMMON, *DISCOVER, *RELEASE],
}


def select_profile(task: str) -> str:
    text = task.lower()
    if any(word in text for word in ("publish", "package", "release", "deliver", "distribution")):
        return "release"
    if any(word in text for word in ("secret", "security", "privacy", "credential", "threat")):
        return "security"
    if any(word in text for word in ("dependency", "upgrade", "lockfile", "sbom")):
        return "dependency"
    if any(word in text for word in ("bug", "debug", "failure", "error")):
        return "debug"
    if any(word in text for word in ("change", "implement", "build", "fix", "edit")):
        return "change"
    return "discover"


def build_plan(profile: str) -> list[dict[str, object]]:
    try:
        return list(PROFILES[profile])
    except KeyError as exc:
        raise ValueError(f"unknown profile: {profile}") from exc


def resolve_step_command(command: str) -> list[str] | None:
    parts = shlex.split(command, posix=False)
    if not parts:
        return None
    executable = shutil.which(parts[0])
    if executable:
        return [executable, *parts[1:]]
    module = MODULE_FALLBACKS.get(parts[0])
    if module:
        return [sys.executable, "-m", module, *parts[1:]]
    return None


def _report_exists(repo: Path, report: str) -> bool:
    return not report or (repo / report).exists()


def _print_plan(profile: str, plan: list[dict[str, object]]) -> None:
    print(f"AgentReady selected profile: {profile}")
    for item in plan:
        suffix = " [heavy]" if item["heavy"] else ""
        print(f"- {item['command']}{suffix}: {item['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select and run public AgentReady tools.")
    parser.add_argument("--task", default="")
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--mode", type=str.lower, choices=("plan", "audit", "run"), default="plan")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--include-heavy", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--tool-context",
        action="store_true",
        help="emit the complete scoped tool context as JSON",
    )
    args = parser.parse_args(argv)

    from agent_tool_context import build_tool_context, enrich_step, require_scoped_tool_context

    if args.tool_context:
        context = build_tool_context()
        require_scoped_tool_context(context)
        print(json.dumps(context, indent=2, ensure_ascii=True))
        return 0

    profile = args.profile or select_profile(args.task)
    plan = build_plan(profile)
    if args.json:
        print(
            json.dumps(
                {
                    "profile": profile,
                    "source": "instruction_tables",
                    "capability_layer": "canonical_topology",
                    "tool_context_scope": "canonical_topology",
                    "inventory_scope": "canonical_topology",
                    "steps": [enrich_step(item) for item in plan],
                },
                indent=2,
            )
        )
        return 0
    if args.mode == "plan":
        _print_plan(profile, plan)
        return 0

    repo = args.repo.resolve()
    failures: list[str] = []
    if args.mode == "audit":
        for item in plan:
            resolved = resolve_step_command(str(item["command"]))
            tool_ok = resolved is not None
            report_ok = _report_exists(repo, str(item["report"]))
            status = "PASS" if tool_ok and report_ok else "FAIL"
            print(f"{status}: {item['command']} tool={tool_ok} report={report_ok}")
            if status == "FAIL":
                failures.append(str(item["command"]))
        return 1 if failures else 0

    for item in plan:
        if item["heavy"] and not args.include_heavy:
            print(f"SKIP heavy: {item['command']}")
            continue
        resolved = resolve_step_command(str(item["command"]))
        if resolved is None:
            print(f"FAIL missing tool: {item['command']}", file=sys.stderr)
            failures.append(str(item["command"]))
            continue
        print(f"RUN: {item['command']}")
        result = subprocess.run(resolved, cwd=repo, check=False)
        if result.returncode:
            failures.append(str(item["command"]))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
