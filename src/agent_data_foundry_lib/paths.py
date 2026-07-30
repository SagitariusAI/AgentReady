"""Shared low-level foundation for the Agent Data Foundry: path roots, run identity, and
git-commit provenance.

These are the primitives that belong to no single Cerberus subsystem — the Factory home, the
data-foundry report and release path roots, the run-id / release-id stamps, and the best-effort
HEAD-sha provenance helper. They have no intra-foundry dependencies (stdlib + the schemas
product-id constant only), so every subsystem leaf and the central module can import them without
a cycle. Extracting them here (Phase N) removes the last lazy back-imports of `_current_git_commit`
from eval_gate / training_export and stops `report_data_foundry_path` / `cerberus_release_root` /
`AGENTREADY_HOME` from being defined centrally. Paths, the env-home default, the run-id formats, and
the git-sha behavior are preserved byte-for-byte from the pre-split module.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from agent_data_foundry_lib.schemas import CERBERUS_PRODUCT_ID

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path.home() / ".agentready")


def run_id_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def default_release_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def report_data_foundry_path(root: Path, name: str) -> Path:
    return root / "reports" / "data-foundry" / name


def cerberus_release_root(root: Path, product_id: str = CERBERUS_PRODUCT_ID) -> Path:
    return root / "data" / "training-library" / "40_release_ready" / product_id


def _current_git_commit(root: Path | str) -> str | None:
    """Best-effort current HEAD sha for provenance source_commit. Returns None (an
    EXPLICIT unknown) when not a git repo or git is unavailable -- never fabricated."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None
