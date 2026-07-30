"""Command execution with live tee + deterministic capture.

run_command runs a wrapped command, streams stdout/stderr live to the terminal (raw — the founder's
own screen), and simultaneously buffers them. On completion it redacts the buffers, writes redacted
log files, hashes the redacted content, captures git state before/after, writes one append-only
``command_run`` event, and returns the event. The wrapped command's exit code is preserved for the
caller. A missing executable is captured as useful data (exit 127, status=error), never a crash."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from factory_capture.common import now_iso, sha256_text
from factory_capture.events import append_event, new_event
from factory_capture.gitstate import capture_git_state, find_repo_root
from factory_capture.redaction import redact_text
from factory_capture.store import Store


def _pump(pipe, sink, buffer: list[str]) -> None:
    for line in iter(pipe.readline, ""):
        sink.write(line)
        sink.flush()
        buffer.append(line)
    pipe.close()


def _exec_tee(
    command: list[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str], int]:
    """Run command, tee both streams live to the terminal while buffering. Returns (out, err, rc)."""
    try:
        proc = subprocess.Popen(  # noqa: S603 - command is the founder's explicit wrapped argv
            command, cwd=str(cwd), env=dict(env) if env is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
    except FileNotFoundError:
        message = f"factory-capture: command not found: {command[0]}\n"
        sys.stderr.write(message)
        return [], [message], 127
    out_buf: list[str] = []
    err_buf: list[str] = []
    threads = [
        threading.Thread(target=_pump, args=(proc.stdout, sys.stdout, out_buf)),
        threading.Thread(target=_pump, args=(proc.stderr, sys.stderr, err_buf)),
    ]
    for thread in threads:
        thread.start()
    proc.wait()
    for thread in threads:
        thread.join()
    return out_buf, err_buf, proc.returncode


def run_command(
    store: Store,
    command: list[str],
    cwd: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    workflow_lane: str = "research",
    provenance: dict | None = None,
) -> dict:
    """Execute `command`, capture it as a command_run event, and return the event."""
    command = list(command)
    cwd = Path(cwd or Path.cwd())
    repo_root = find_repo_root(cwd)
    git_before = capture_git_state(repo_root)

    started = now_iso()
    clock = time.perf_counter()
    out_buf, err_buf, exit_code = _exec_tee(command, cwd, env=env)
    duration_ms = int((time.perf_counter() - clock) * 1000)
    git_after = capture_git_state(repo_root)

    stdout_red, out_findings = redact_text("".join(out_buf))
    stderr_red, err_findings = redact_text("".join(err_buf))

    # the command itself can carry a secret (e.g. an inline token); store it redacted, run it raw
    redacted_command, cmd_findings = [], []
    for arg in command:
        red_arg, findings = redact_text(arg)
        redacted_command.append(red_arg)
        cmd_findings.extend(findings)

    event = new_event("command_run")
    store.logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = store.logs_dir / f"{event['event_id']}.stdout.txt"
    stderr_path = store.logs_dir / f"{event['event_id']}.stderr.txt"
    stdout_path.write_text(stdout_red, encoding="utf-8")
    stderr_path.write_text(stderr_red, encoding="utf-8")

    merged: dict[str, int] = {}
    for finding in (*out_findings, *err_findings, *cmd_findings):
        merged[finding["kind"]] = merged.get(finding["kind"], 0) + finding["count"]
    redaction = {"applied": bool(merged), "findings": [{"kind": k, "count": v} for k, v in sorted(merged.items())]}

    if exit_code == 127:
        status = "error"
    elif exit_code == 0:
        status = "success"
    else:
        status = "failure"

    event.update(
        timestamp_start=started,
        timestamp_end=now_iso(),
        duration_ms=duration_ms,
        cwd=str(cwd),
        repo_root=str(repo_root),
        command=redacted_command,
        exit_code=exit_code,
        git_before=git_before,
        git_after=git_after,
        stdout_log=str(stdout_path.relative_to(store.root)),
        stderr_log=str(stderr_path.relative_to(store.root)),
        stdout_sha256=sha256_text(stdout_red),
        stderr_sha256=sha256_text(stderr_red),
        redaction=redaction,
        workflow_lane=workflow_lane,
        workflow_lane_source="governed_command_surface",
        provenance=provenance or {
            "source_type": "governed_command_surface",
            "capture_runtime": "factory_capture",
        },
        status=status,
    )
    return append_event(store, event)
