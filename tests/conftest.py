# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Shared test isolation for the AgentReady test suite.

Two stores are redirected away from the real environment so running the suite
never writes into the user's coordination or re-entry store. They are frozen at
different times, so they need different mechanisms:

1. ``COORDINATION_ROOT`` is a module-level constant in ``agent_runtime_paths``,
   frozen at import, and coordination stores are created under it. A per-test
   fixture is too late -- by the time it runs the constant is already frozen at
   the real store, so any test that creates a coordination store would write into
   it. The dedicated ``AGENTREADY_COORDINATION_ROOT`` seam (which normal use never
   sets) is therefore set here, at conftest import time, before any module imports
   ``agent_runtime_paths``.

2. ``AGENTREADY_SESSION_REENTRY_DIR`` (the re-entry receipt store) is read
   dynamically on every call, so a per-test fixture is sufficient and gives each
   test its own directory.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# (1) freeze-time isolation: must run before any module imports agent_runtime_paths.
if not os.environ.get("AGENTREADY_COORDINATION_ROOT", "").strip():
    _session_coord = tempfile.mkdtemp(prefix="agentready-test-coord-")
    os.environ["AGENTREADY_COORDINATION_ROOT"] = _session_coord
    atexit.register(shutil.rmtree, _session_coord, ignore_errors=True)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_agentready_state(tmp_path_factory, monkeypatch):
    # (2) per-test isolation for the dynamically-resolved re-entry store.
    state = tmp_path_factory.mktemp("agentready-state")
    monkeypatch.setenv("AGENTREADY_SESSION_REENTRY_DIR", str(state / "session-reentry"))
