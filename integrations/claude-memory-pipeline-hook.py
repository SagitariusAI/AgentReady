#!/usr/bin/env python3
# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Optional low-latency Claude hook for the public memory pipeline.

Correctness remains with the watcher and watchdog. The hook only requests an
immediate source scan when AGENTREADY_MEMORY_PIPELINE_CONFIG is configured.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    config = os.environ.get("AGENTREADY_MEMORY_PIPELINE_CONFIG")
    if not config:
        return 0
    subprocess.run(
        [sys.executable, "-m", "agent_memory_pipeline", "--config", config, "enqueue"],
        capture_output=True,
        check=False,
        timeout=15,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
