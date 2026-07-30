# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for agent history search."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from agent_coordination.store import ensure_state

_RG_EXCLUDES = ("!*.sqlite*", "!*.db", "!*.png", "!*.jpg", "!*.zip", "!*.exe", "!*.msi")


def search(state: Path, query: str, *, search_fn=None) -> list[str]:
    if search_fn is not None:
        return search_fn(state, query)
    if shutil.which("rg"):
        args = ["rg", "-n", "--hidden"]
        for glob in _RG_EXCLUDES:
            args += ["--glob", glob]
        args += ["--", query, str(state)]
        out = subprocess.run(args, capture_output=True, text=True, check=False)
        return [ln for ln in out.stdout.replace("\r\n", "\n").split("\n") if ln]
    # stdlib fallback: grep each text file under the state root
    results = []
    for path in state.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if query in line:
                results.append(f"{path}:{i}:{line}")
    return results


def run(*, repo: str, query: str, search_fn=None) -> dict:
    state = ensure_state(repo)
    results = search(state, query, search_fn=search_fn)
    return {"state": state, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_history_search")
    parser.add_argument("-Repo", "--repo", default=os.getcwd())
    parser.add_argument("-Query", "--query", required=True)
    args = parser.parse_args(argv)
    result = run(repo=args.repo, query=args.query)
    if not result["results"]:
        print(f"No AgentReady history matches for: {args.query}")
        return 0
    for line in result["results"]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
