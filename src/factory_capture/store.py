# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""The local capture store: data-root resolution + on-disk layout + SQLite index init.

Default data root is repo-local — ``<repo_root>/.factory_capture`` — because capture and git hooks
are inherently per-repo (this mirrors the repo's existing per-repo coordination stores rather than
inventing a second global universe). Override with the ``FACTORY_CAPTURE_DIR`` environment variable.
The AgentReady factory home (``AGENTREADY_HOME``) remains the central factory root; the capture store
is deliberately repo-scoped and gitignored. JSONL is the source of truth; SQLite is a query index."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from factory_capture.common import now_iso, write_json
from factory_capture.gitstate import find_repo_root

STORE_DIRNAME = ".factory_capture"
STORE_SCHEMA = "sf.capture_store.v0.1"
VERSION = "0.1"


@dataclass(frozen=True)
class Store:
    root: Path  # the .factory_capture directory

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def index_path(self) -> Path:
        return self.root / "index.sqlite"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def hooks_dir(self) -> Path:
        return self.root / "hooks"

    def exists(self) -> bool:
        return self.config_path.exists()

    def ensure_dirs(self) -> None:
        for directory in (self.root, self.logs_dir, self.artifacts_dir, self.sessions_dir, self.hooks_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.index_path))
        con.execute(
            """
            create table if not exists events (
                event_id text primary key,
                event_type text,
                timestamp_start text,
                timestamp_end text,
                duration_ms integer,
                exit_code integer,
                status text,
                command text,
                repo_root text,
                commit_after text,
                dirty_after integer
            )
            """
        )
        return con

    def init(self, *, force: bool = False, repo_root: Path | None = None) -> dict:
        """Create the store layout + config + SQLite index. Refuses to clobber unless force=True.

        Returns {"created": bool, "root": str, "already_existed": bool}.
        """
        already = self.exists()
        if already and not force:
            return {"created": False, "already_existed": True, "root": str(self.root)}
        self.ensure_dirs()
        con = self.connect()
        con.commit()
        con.close()
        write_json(self.config_path, {
            "schema": STORE_SCHEMA,
            "version": VERSION,
            "created_utc": now_iso(),
            "repo_root": str(repo_root or find_repo_root(self.root.parent)),
        })
        return {"created": True, "already_existed": already, "root": str(self.root)}


def resolve_store(start: Path | None = None) -> Store:
    """Resolve the capture store for the given start dir.

    FACTORY_CAPTURE_DIR (absolute) wins; otherwise <repo_root>/.factory_capture.
    """
    override = os.environ.get("FACTORY_CAPTURE_DIR")
    if override:
        return Store(Path(override))
    repo_root = find_repo_root(start or Path.cwd())
    return Store(repo_root / STORE_DIRNAME)
