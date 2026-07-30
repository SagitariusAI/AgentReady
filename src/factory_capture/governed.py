"""Automatic capture bootstrap for governed AgentReady Python command surfaces."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

from factory_capture.runner import run_command
from factory_capture.store import Store, resolve_store

ACTIVE_ENV = "FACTORY_CAPTURE_ACTIVE"
LANE_ENV = "AGENTREADY_WORKFLOW_LANE"
VALID_LANES = {"personal", "business", "research"}


def _is_factory_capture_command(command: Sequence[str]) -> bool:
    normalized = " ".join(str(part).replace("\\", "/").lower() for part in command)
    return "factory_capture" in normalized or "factory-capture" in normalized


def governed_store(cwd: Path) -> Store | None:
    """Resolve an initialized local store, falling back to AgentReady's store."""
    local = resolve_store(cwd)
    if local.exists():
        return local
    home = os.environ.get("AGENTREADY_HOME")
    if home:
        fallback = Store(Path(home) / ".factory_capture")
        if fallback.exists():
            return fallback
    return None


def auto_capture_current_process(
    *,
    surface: str,
    argv: Sequence[str] | None = None,
    cwd: Path | None = None,
) -> int | None:
    """Respawn the current CLI once through capture and preserve its exit code."""
    if os.environ.get(ACTIVE_ENV) == "1":
        return None
    command = [sys.executable, *(list(argv) if argv is not None else sys.argv)]
    if _is_factory_capture_command(command):
        return None
    working_dir = Path(cwd or Path.cwd())
    store = governed_store(working_dir)
    if store is None:
        return None
    lane = os.environ.get(LANE_ENV, "research").strip().lower()
    if lane not in VALID_LANES:
        raise ValueError(f"{LANE_ENV} must be one of {sorted(VALID_LANES)}")
    child_env = dict(os.environ)
    child_env[ACTIVE_ENV] = "1"
    event = run_command(
        store,
        command,
        cwd=working_dir,
        env=child_env,
        workflow_lane=lane,
        provenance={
            "source_type": "agentready_command_surface",
            "surface": surface,
            "automatic": True,
        },
    )
    return int(event.get("exit_code") or 0)
