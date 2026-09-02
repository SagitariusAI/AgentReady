# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import agent_session_reentry as reentry

REPO_ROOT = Path(__file__).resolve().parents[1]
PROOF_ROOT = REPO_ROOT / "docs" / "proofs"
LEAN_PROOF_TIMEOUT_SECONDS = 60


def _lean_executable() -> str | None:
    candidates = [
        shutil.which("lean"),
        str(Path.home() / ".elan" / "bin" / "lean.exe"),
        str(Path.home() / ".elan" / "bin" / "lean"),
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def test_agentready_lean_proofs_check_when_lean_is_installed() -> None:
    proofs = sorted(PROOF_ROOT.glob("*.lean"))
    assert proofs, "the AgentReady proof directory must contain at least one checked invariant"
    lean = _lean_executable()
    if lean is None:
        pytest.skip("Lean is optional for public contributors; release verification checks this proof")
    for proof in proofs:
        completed = subprocess.run(
            [lean, str(proof)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=LEAN_PROOF_TIMEOUT_SECONDS,
        )
        assert completed.returncode == 0, (
            f"Lean rejected {proof.relative_to(REPO_ROOT)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def test_receipt_ttl_proof_is_bound_to_running_code() -> None:
    proof = (PROOF_ROOT / "session_reentry_worktree.lean").read_text(encoding="utf-8")
    match = re.search(r"^def DEFAULT_RECEIPT_TTL_MINUTES : Nat := (\d+)$", proof, re.MULTILINE)
    assert match, "the receipt TTL proof must declare its modeled default"
    assert int(match.group(1)) == reentry.DEFAULT_TTL_MINUTES
