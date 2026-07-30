"""Chat seam — port of `Publish-AgentChat` (L402-422) and `Show-AgentUnread` (L424-439).

Best-effort, NEVER-throws launchers that mirror coordination into the live team chat (Matrix) and push
unread directed messages into an agent's context. The transport is injectable so tests stub it (NO live
network); the default transport subprocesses the existing Python `agent_matrix` / `agent_comms` modules
exactly as the PowerShell did (only when configured/reachable, short timeout, output suppressed). The
network module is invoked via subprocess (not imported) so the coordination foundation stays decoupled.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[2])


def _python() -> Path:
    venv = AGENTREADY_HOME / ".venv" / "Scripts" / "python.exe"
    return venv if venv.exists() else Path(sys.executable)


def _default_publish(agent: str, text: str) -> None:
    matrix = AGENTREADY_HOME / "src" / "agent_matrix.py"
    cfg = AGENTREADY_HOME / "config" / "matrix.json"
    if not (agent and matrix.exists() and cfg.exists()):
        return
    env = {**os.environ, "AGENTREADY_MATRIX_TIMEOUT": "4"}
    subprocess.run([str(_python()), str(matrix), "post", "--as", agent, "--text", text],
                   capture_output=True, text=True, timeout=15, check=False, env=env)


def _default_unread(repo: str) -> str:
    comms = AGENTREADY_HOME / "src" / "agent_comms.py"
    if not comms.exists():
        return ""
    out = subprocess.run([str(_python()), str(comms), "banner", "--repo", str(repo)],
                         capture_output=True, text=True, timeout=15, check=False)
    return out.stdout


def publish_chat(agent: str, text: str, transport: Callable[[str, str], None] | None = None) -> None:
    """Mirror a coordination event to chat. Best-effort; never raises (PS try/catch{})."""
    transport = transport or _default_publish
    try:
        transport(agent, text)
    except Exception:  # noqa: BLE001 - chat is best-effort; it must never break a coordination action
        return


def show_unread(repo, transport: Callable[[str], str] | None = None) -> str:
    """Return the unread-messages banner (or ''). Best-effort; never raises (PS try/catch{})."""
    transport = transport or _default_unread
    try:
        return transport(str(repo)) or ""
    except Exception:  # noqa: BLE001 - best-effort surface; never break the command that triggered it
        return ""
