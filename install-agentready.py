# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Source-checkout installer for AgentReady."""
from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from agent_deploy import main  # noqa: E402, I001


if __name__ == "__main__":
    arguments = list(sys.argv[1:])
    if "--source" not in arguments:
        arguments.extend(["--source", str(SOURCE_ROOT)])
    raise SystemExit(main(arguments))
