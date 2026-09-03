# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for agent ci local."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[1])
GATE_MARKER_REL = Path(".agentready") / "gate_status.json"
REPO_CI_CONFIG_REL = Path(".agentready") / "ci.json"


def _venv_python() -> Path:
    configured = AGENTREADY_HOME / ".venv" / "Scripts" / "python.exe"
    # Portable checkouts and governed worktrees intentionally do not duplicate
    # the tool venv. In those environments the wrapper's current interpreter is
    # the authoritative, already-running Python runtime.
    return configured if configured.exists() else Path(sys.executable)


def _repo_python(repo: Path) -> Path:
    """Resolve the repository interpreter, falling back to AgentReady's runtime."""
    repo = Path(repo)
    candidates = (
        repo / ".venv" / "Scripts" / "python.exe",
        repo / ".venv" / "bin" / "python",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), _venv_python())


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def detect_steps(repo: Path, *, include_setup: bool = True) -> list[dict]:
    """Ordered steps that would run, byte-faithful to agent-ci-local.ps1 L40-86 detection."""
    repo = Path(repo)
    py = _repo_python(repo)
    steps: list[dict] = []
    repo_ci = _repo_local_ci(repo)
    setup = list(repo_ci.get("setup", [])) if repo_ci and include_setup else []

    if repo_ci and repo_ci["mode"] == "replace":
        return [*setup, *repo_ci["steps"]]

    def has(rel: str) -> bool:
        return (repo / rel).exists()

    if has("lefthook.yml"):
        steps.append({"name": "lefthook run pre-commit", "argv": ["lefthook", "run", "pre-commit"]})
    if has(".pre-commit-config.yaml"):
        steps.append({"name": "pre-commit run --all-files", "argv": ["pre-commit", "run", "--all-files"]})
    has_tox = has("tox.ini")
    if not has_tox and has("pyproject.toml"):
        try:
            has_tox = "[tool.tox]" in (repo / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            has_tox = False
    if has_tox:
        steps.append({"name": "tox", "argv": ["tox"]})
    if has("noxfile.py"):
        steps.append({"name": "nox", "argv": ["nox"]})
    if has("package.json"):
        if has("pnpm-lock.yaml"):
            steps.append({"name": "pnpm test", "argv": ["pnpm", "test"]})
        else:
            steps.append({"name": "npm test", "argv": ["npm", "test"]})
    if list(repo.glob("*.sln")):
        steps.append({"name": "dotnet test", "argv": ["dotnet", "test"]})
    if has("Cargo.toml"):
        steps.append({"name": "cargo test", "argv": ["cargo", "test"]})
    if (repo / "go.mod").is_file():
        steps.append({"name": "go test ./...", "argv": ["go", "test", "./..."]})
    if has("dagger.json") or has("dagger"):
        steps.append({"name": "dagger call test", "argv": ["dagger", "call", "test"]})
    if has("src") and has("tests") and py.exists():
        steps.append({"name": "python compile src",
                      "argv": [str(py), "-m", "compileall", "-q", str(repo / "src")]})
        steps.append({"name": "pytest tests",
                      "argv": [str(py), "-m", "pytest", "-q", str(repo / "tests")],
                      "pythonpath": str(repo / "src")})
    if repo_ci and repo_ci["mode"] == "prepend":
        return [*setup, *repo_ci["steps"], *steps]
    if repo_ci and repo_ci["mode"] == "append":
        return [*setup, *steps, *repo_ci["steps"]]
    return [*setup, *steps]


def _configured_steps(
    repo: Path,
    raw_steps: object,
    *,
    field: str,
    required: bool,
    fail_fast: bool = False,
) -> list[dict]:
    if raw_steps is None and not required:
        return []
    if not isinstance(raw_steps, list) or not raw_steps:
        qualifier = "at least one " if required else "a non-empty "
        raise ValueError(f"{REPO_CI_CONFIG_REL} must declare {qualifier}{field} step")

    steps: list[dict] = []
    for idx, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"{REPO_CI_CONFIG_REL} {field} step {idx} must be an object")
        argv = step.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
            raise ValueError(
                f"{REPO_CI_CONFIG_REL} {field} step {idx} argv must be a non-empty string list"
            )
        entry = {
            "name": str(step.get("name") or f"repo-local {field} step {idx}"),
            "argv": [
                str(_repo_python(repo)) if part == "{repo_python}" else part
                for part in argv
            ],
        }
        pythonpath = step.get("pythonpath")
        if isinstance(pythonpath, str) and pythonpath:
            entry["pythonpath"] = pythonpath
        env = step.get("env")
        if env is not None:
            if not isinstance(env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            ):
                raise ValueError(
                    f"{REPO_CI_CONFIG_REL} {field} step {idx} env must be a string map"
                )
            entry["env"] = dict(env)
        if fail_fast:
            entry["fail_fast"] = True
        steps.append(entry)
    return steps


def _repo_local_ci(repo: Path) -> dict | None:
    """Load optional repo-local CI declaration from `.agentready/ci.json`.

    The config intentionally accepts argv lists, not shell command strings, so the
    repo chooses its gate without reintroducing shell parsing ambiguity.
    """
    path = Path(repo) / REPO_CI_CONFIG_REL
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{REPO_CI_CONFIG_REL} must contain a JSON object")
    if raw.get("version") != 1:
        raise ValueError(f"{REPO_CI_CONFIG_REL} must declare version 1")
    mode = str(raw.get("mode", "replace")).lower()
    if mode not in {"replace", "prepend", "append"}:
        raise ValueError(f"{REPO_CI_CONFIG_REL} mode must be replace, prepend, or append")
    setup = _configured_steps(
        repo,
        raw.get("setup"),
        field="setup",
        required=False,
        fail_fast=True,
    )
    steps = _configured_steps(repo, raw.get("steps"), field="CI", required=True)
    return {"mode": mode, "setup": setup, "steps": steps}


def repo_setup_steps(repo: Path) -> list[dict]:
    """Return the idempotent environment setup declared for this repository."""
    contract = _repo_local_ci(Path(repo))
    return list(contract.get("setup", [])) if contract else []


def run_steps(repo: Path, steps: list[dict], *, echo: bool = True) -> dict:
    """Run each step (Invoke-Step port): tee output to the log, capture exit, aggregate failures."""
    repo = Path(repo)
    log: list[str] = [f"Agent local CI: {repo}", f"Generated: {_now()}", ""]
    failures: list[str] = []
    steps_run = 0

    def emit(line: str) -> None:
        log.append(line)
        if echo:
            print(line)

    for s in steps:
        steps_run += 1
        step_failed = False
        emit(f"===== {s['name']} =====")
        env = {**os.environ}
        if s.get("pythonpath"):
            env["PYTHONPATH"] = s["pythonpath"]
        if s.get("env"):
            env.update(s["env"])
        try:
            proc = subprocess.run(
                s["argv"],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                # Native tools may mix UTF-8 with arbitrary status bytes. Keep
                # those bytes visible without allowing the Windows locale codec
                # to turn a healthy command into a setup-runner exception.
                errors="backslashreplace",
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            for line in out.splitlines():
                emit(line)
            code = proc.returncode
            emit(f"EXIT {s['name']} = {code}")
            if code != 0:
                failures.append(f"{s['name']} exited {code}")
                step_failed = True
        except Exception as exc:  # noqa: BLE001 - mirror PS try/catch step error capture
            emit(f"ERROR {s['name']} = {exc}")
            failures.append(f"{s['name']} error: {exc}")
            step_failed = True
        emit("")
        if step_failed and s.get("fail_fast"):
            emit(f"ABORT remaining CI steps: required environment setup failed at {s['name']}")
            break

    if not steps_run:
        emit("WARN no known CI/test entrypoints detected")
    if failures:
        emit("===== CI SUMMARY =====")
        for f in failures:
            emit(f"FAIL {f}")
    return {"steps_run": steps_run, "failures": failures, "log": "\n".join(log)}


def _combine_step_results(*results: dict | None) -> dict:
    """Combine sequential setup and gate phases into one truthful receipt."""
    present = [result for result in results if result is not None]
    return {
        "steps_run": sum(result["steps_run"] for result in present),
        "failures": [failure for result in present for failure in result["failures"]],
        "log": "\n".join(result["log"] for result in present),
    }


def decide(failures: list[str], steps_run: int) -> dict:
    """Pass/fail aggregation (PS L92-121). gate 'pass' needs >=1 step + zero failures."""
    report_status = "fail" if failures else ("warn" if steps_run == 0 else "ok")
    gate_status = "fail" if (failures or steps_run == 0) else "pass"
    exit_code = 1 if failures else 0
    return {"report_status": report_status, "gate_status": gate_status, "exit_code": exit_code}


def write_marker(repo: Path, gate_status: str, *, no_mark: bool = False) -> bool:
    """Best-effort gate-marker refresh via agent_workstate.py mark. Returns True if it wrote.

    Gated on AGENTREADY_CI_NO_MARK / no_mark. NEVER raises -- a marker failure must not change the CI
    result (PS L111-118).
    """
    if no_mark or os.environ.get("AGENTREADY_CI_NO_MARK"):
        return False
    try:
        ws = AGENTREADY_HOME / "src" / "agent_workstate.py"
        subprocess.run([str(_venv_python()), str(ws), "mark", "--repo", str(repo),
                        "--status", gate_status, "--kind", "agent_ci_local"],
                       capture_output=True, text=True, timeout=60, check=False)
        return True
    except Exception:  # noqa: BLE001 - marker is best-effort; never change the CI result
        return False


def _report_contract(repo: Path, report_dir: Path, primary: Path, status: str, summary: str) -> None:
    try:
        rc = AGENTREADY_HOME / "src" / "agent_report_contract.py"
        subprocess.run([str(_venv_python()), str(rc), "--surface", "ci", "--repo", str(repo),
                        "--report-dir", str(report_dir), "--primary", str(primary),
                        "--status", status, "--summary", summary],
                       capture_output=True, text=True, timeout=60, check=False)
    except Exception:  # noqa: BLE001 - best-effort, like the marker
        return


def run(repo: Path, *, no_mark: bool = False, echo: bool = True, write_outputs: bool = True) -> dict:
    """Full CI run: detect -> run -> decide (+ optional log/report-contract/marker writes)."""
    repo = Path(repo)
    setup_steps = repo_setup_steps(repo)
    setup_result = run_steps(repo, setup_steps, echo=echo) if setup_steps else None
    if setup_result and setup_result["failures"]:
        result = setup_result
    else:
        # Setup may have created the repository venv. Resolve the gate argv only
        # after setup so {repo_python} names the environment that will run it.
        gate_result = run_steps(repo, detect_steps(repo, include_setup=False), echo=echo)
        result = _combine_step_results(setup_result, gate_result)
    verdict = decide(result["failures"], result["steps_run"])
    result.update(verdict)
    if write_outputs:
        out_dir = repo / ".agent-reports" / "ci"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = out_dir / f"agent-ci-local-{stamp}.log"
        log_path.write_text(result["log"] + "\n", encoding="utf-8")
        shutil.copyfile(log_path, out_dir / "agent-ci-local-latest.log")
        summary = ("No known CI/test entrypoints detected." if result["steps_run"] == 0
                   else f"{result['steps_run']} CI step(s) executed; {len(result['failures'])} failure(s).")
        _report_contract(repo, out_dir, log_path, result["report_status"], summary)
        if echo:
            print(f"Agent local CI report: {log_path}")
        write_marker(repo, result["gate_status"], no_mark=no_mark)
        result["log_path"] = str(log_path)
    return result


def _read_marker(repo: Path) -> dict | None:
    path = repo / GATE_MARKER_REL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _head(repo: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10, check=False)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def shadow(repo: Path) -> int:
    """Compute the Python verdict and write a comparison vs the authoritative marker. Always returns 0."""
    repo = Path(repo)
    result = run(repo, no_mark=True, echo=False, write_outputs=False)
    verdict = decide(result["failures"], result["steps_run"])
    marker = _read_marker(repo)
    head = _head(repo)
    agrees = bool(marker) and marker.get("status") == verdict["gate_status"] and marker.get("ref") == head
    comparison = {
        "at": _now(),
        "head": head,
        "python": {**verdict, "steps_run": result["steps_run"], "failures": result["failures"]},
        "authoritative_marker": marker,
        "agrees": agrees,
    }
    out_dir = repo / ".agent-reports" / "ci" / "shadow"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"agent-ci-local-shadow-{stamp}.json"
    out.write_text(json.dumps(comparison, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Agent local CI SHADOW: {out} (agrees={agrees})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_ci_local")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--no-mark", action="store_true")
    parser.add_argument("--shadow", action="store_true",
                        help="compute the Python verdict + comparison report; do NOT write the marker")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.shadow:
        return shadow(repo)
    return run(repo, no_mark=args.no_mark)["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
