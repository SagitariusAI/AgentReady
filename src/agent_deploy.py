# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Install AgentReady and optionally onboard a repository.

The human and autonomous-agent modes share one deterministic implementation.
Agent mode is deliberately noninteractive and requires explicit confirmation
plus machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from agent_prerequisites import build_report as build_prerequisite_report
from agent_prerequisites import print_human as print_prerequisites_human


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    status: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _command_path(bin_dir: Path, name: str) -> Path:
    candidates = [bin_dir / name]
    if os.name == "nt":
        candidates = [bin_dir / f"{name}.exe", bin_dir / f"{name}.cmd", bin_dir / name]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _run(
    name: str,
    command: Sequence[str],
    *,
    runner: Runner,
    env: dict[str, str],
    dry_run: bool,
) -> Step:
    argv = [str(value) for value in command]
    if dry_run:
        return Step(name=name, command=argv, status="PLANNED", exit_code=None)
    try:
        result = runner(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Step(name=name, command=argv, status="FAIL", exit_code=1, stderr=str(exc)[:4000])
    return Step(
        name=name,
        command=argv,
        status="PASS" if result.returncode == 0 else "FAIL",
        exit_code=result.returncode,
        stdout=result.stdout.strip()[:16000],
        stderr=result.stderr.strip()[:16000],
    )


def _validate_source(source: Path) -> None:
    missing = [name for name in ("pyproject.toml", "uv.lock") if not (source / name).is_file()]
    if missing:
        raise ValueError(f"AgentReady source is missing required files: {', '.join(missing)}")
    try:
        project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"AgentReady source has an unreadable pyproject.toml: {exc}") from exc
    if not isinstance(project, dict) or project.get("name") != "agentready":
        raise ValueError("AgentReady source pyproject.toml must declare project.name = 'agentready'")


def _validate_target(target_repo: Path | None, source: Path) -> Path | None:
    if target_repo is None:
        return None
    target = target_repo.resolve()
    if not target.is_dir():
        raise ValueError(f"target repository does not exist or is not a directory: {target}")
    if not (target / ".git").exists():
        raise ValueError(f"target repository is not a Git working-tree root: {target}")
    if target == source:
        raise ValueError("target repository must not be the AgentReady source checkout")
    anchor = Path(target.anchor).resolve()
    if target == anchor or target == Path.home().resolve():
        raise ValueError(f"refusing unsafe target repository path: {target}")
    return target


def deploy(
    *,
    source: Path,
    mode: str,
    target_repo: Path | None,
    runtime_home: Path | None,
    force: bool,
    dry_run: bool,
    runner: Runner = subprocess.run,
    uv_path: str | None = None,
) -> dict[str, object]:
    """Install the tool and optionally generate AgentReady files in a target repository."""
    source = source.resolve()
    _validate_source(source)
    target_repo = _validate_target(target_repo, source)
    if mode not in {"human", "agent"}:
        raise ValueError("mode must be 'human' or 'agent'")
    prerequisite_report = build_prerequisite_report("core")
    if prerequisite_report["overall"] != "PASS":
        missing = ", ".join(prerequisite_report["blocking"])
        raise RuntimeError(f"required AgentReady prerequisites are missing: {missing}")

    uv = uv_path or shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required but was not found on PATH")

    env = dict(os.environ)
    if runtime_home:
        env["AGENTREADY_HOME"] = str(runtime_home.resolve())
    install_command = [uv, "tool", "install"]
    if force:
        install_command.append("--force")
    install_command.append(str(source))

    steps: list[Step] = []
    steps.append(_run("install", install_command, runner=runner, env=env, dry_run=dry_run))
    if steps[-1].status == "FAIL":
        return _payload(mode, source, target_repo, runtime_home, steps)

    bin_step = _run(
        "resolve-tool-bin",
        [uv, "tool", "dir", "--bin"],
        runner=runner,
        env=env,
        dry_run=dry_run,
    )
    steps.append(bin_step)
    if bin_step.status == "FAIL":
        return _payload(mode, source, target_repo, runtime_home, steps)

    if dry_run:
        bin_dir = Path("<uv-tool-bin>")
    else:
        if not bin_step.stdout:
            steps.append(Step("resolve-tool-bin-output", [], "FAIL", 1, stderr="uv returned an empty tool bin path"))
            return _payload(mode, source, target_repo, runtime_home, steps)
        bin_dir = Path(bin_step.stdout)

    for command_name in (
        "agentready",
        "agent-deploy",
        "agent-prerequisites",
        "agent-bootstrap-repo",
        "agent-coordination",
        "factory-capture",
    ):
        executable = _command_path(bin_dir, command_name)
        steps.append(
            _run(
                f"verify-{command_name}",
                [str(executable), "--help"],
                runner=runner,
                env=env,
                dry_run=dry_run,
            )
        )
        if steps[-1].status == "FAIL":
            return _payload(mode, source, target_repo, runtime_home, steps)

    if target_repo is not None:
        bootstrap = _command_path(bin_dir, "agent-bootstrap-repo")
        steps.append(
            _run(
                "bootstrap-repository",
                [str(bootstrap), "--repo", str(target_repo)],
                runner=runner,
                env=env,
                dry_run=dry_run,
            )
        )

    return _payload(mode, source, target_repo, runtime_home, steps)


def _payload(
    mode: str,
    source: Path,
    target_repo: Path | None,
    runtime_home: Path | None,
    steps: list[Step],
) -> dict[str, object]:
    overall = "PASS" if all(step.status in {"PASS", "PLANNED"} for step in steps) else "FAIL"
    if steps and all(step.status == "PLANNED" for step in steps):
        overall = "PLANNED"
    return {
        "schema": "agentready.deployment.v1",
        "overall": overall,
        "mode": mode,
        "source": str(source),
        "target_repo": str(target_repo) if target_repo else None,
        "runtime_home": str(runtime_home.resolve()) if runtime_home else None,
        "steps": [asdict(step) for step in steps],
    }


def _print_human(payload: dict[str, object]) -> None:
    print(f"AgentReady deployment: {payload['overall']}")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        print(f"- {step['name']}: {step['status']}")
        if step.get("stderr"):
            print(f"  {step['stderr']}", file=sys.stderr)
    if payload["overall"] == "PASS":
        print("Run 'agentready --help' to view the command surface.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install AgentReady for a human operator or an autonomous AI agent."
    )
    parser.add_argument("--mode", choices=("human", "agent"), default="human")
    parser.add_argument(
        "--source",
        type=Path,
        help="AgentReady source checkout; defaults to the current directory.",
    )
    parser.add_argument("--target-repo", type=Path)
    parser.add_argument("--runtime-home", type=Path)
    parser.add_argument(
        "--prerequisites-only",
        action="store_true",
        help="List/check prerequisites without installing or changing a repository.",
    )
    parser.add_argument(
        "--prerequisite-profile",
        choices=("core", "recommended", "full", "development"),
        default="recommended",
    )
    parser.add_argument(
        "--strict-prerequisites",
        action="store_true",
        help="Treat every missing item in the selected prerequisite profile as blocking.",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing uv tool installation.")
    parser.add_argument("--yes", action="store_true", help="Confirm installation without a prompt.")
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable JSON result.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print the deployment plan.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source or Path.cwd()
    if args.mode == "agent" and (not args.yes or not args.json):
        print("Agent mode requires both --yes and --json.", file=sys.stderr)
        return 2
    if args.prerequisites_only:
        report = build_prerequisite_report(
            args.prerequisite_profile,
            strict=args.strict_prerequisites,
        )
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print_prerequisites_human(report)
        return 0 if report["overall"] == "PASS" else 1
    if not args.yes and not args.dry_run:
        if not sys.stdin.isatty():
            print("Noninteractive deployment requires --yes.", file=sys.stderr)
            return 2
        answer = input(f"Install AgentReady from {source.resolve()}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Deployment cancelled.")
            return 2
    try:
        payload = deploy(
            source=source,
            mode=args.mode,
            target_repo=args.target_repo,
            runtime_home=args.runtime_home,
            force=args.force,
            dry_run=args.dry_run,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {
            "schema": "agentready.deployment.v1",
            "overall": "FAIL",
            "mode": args.mode,
            "error": str(exc),
            "steps": [],
        }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_human(payload)
    return 0 if payload["overall"] in {"PASS", "PLANNED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
