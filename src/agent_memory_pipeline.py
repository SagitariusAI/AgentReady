#!/usr/bin/env python3
# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Durable, writer-agnostic orchestration for local memory graph pipelines."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, path)


@dataclass(frozen=True)
class Stage:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class PipelineConfig:
    config_path: Path
    root: Path
    state_dir: Path
    source_globs: tuple[str, ...]
    stages: tuple[Stage, ...]
    settle_seconds: float = 20.0
    poll_seconds: float = 10.0
    retry_base_seconds: float = 30.0
    command_timeout: int = 3600

    @property
    def health(self) -> Path:
        return self.state_dir / "health.json"

    @classmethod
    def load(cls, config_path: Path) -> "PipelineConfig":
        path = config_path.resolve()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("pipeline configuration must be a JSON object")
        root_value = Path(str(raw.get("root", ".")))
        root = (path.parent / root_value).resolve() if not root_value.is_absolute() else root_value.resolve()
        globs = raw.get("source_globs", ["memories/**/*.md"])
        if not isinstance(globs, list) or not globs or not all(isinstance(item, str) and item for item in globs):
            raise ValueError("source_globs must be a non-empty list of strings")
        for pattern in globs:
            normalized = pattern.replace("\\", "/")
            if Path(normalized).is_absolute() or ".." in Path(normalized).parts:
                raise ValueError("source_globs must stay within root")
        stages_raw = raw.get("stages")
        if not isinstance(stages_raw, list) or not stages_raw:
            raise ValueError("stages must be a non-empty list")
        stages: list[Stage] = []
        for item in stages_raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("each stage needs a string name")
            argv = item.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(token, str) and token for token in argv):
                raise ValueError(f"stage {item['name']!r} needs a non-empty argv list")
            stages.append(Stage(item["name"], tuple(argv)))
        state_value = raw.get("state_dir")
        if state_value:
            state_path = Path(str(state_value))
            state_dir = (path.parent / state_path).resolve() if not state_path.is_absolute() else state_path.resolve()
        else:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "state"))
            state_dir = (base / "AgentReady" / "memory-pipelines" / path.stem).resolve()
        return cls(
            config_path=path,
            root=root,
            state_dir=state_dir,
            source_globs=tuple(globs),
            stages=tuple(stages),
            settle_seconds=float(raw.get("settle_seconds", 20)),
            poll_seconds=float(raw.get("poll_seconds", 10)),
            retry_base_seconds=float(raw.get("retry_base_seconds", 30)),
            command_timeout=int(raw.get("command_timeout", 3600)),
        )


class PipelineBusy(RuntimeError):
    """Raised when another worker owns the process-wide pipeline lock."""


class ProcessLock(AbstractContextManager["ProcessLock"]):
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise PipelineBusy(str(self.path)) from error
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"pid={os.getpid()}\n".encode())
        self.handle.flush()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class EventStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                digest TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                detected_at REAL NOT NULL,
                ready_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                completed_at REAL,
                UNIQUE(source, digest, kind)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                source TEXT PRIMARY KEY,
                digest TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def snapshots(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT source, digest FROM snapshots")
        return {str(row["source"]): str(row["digest"]) for row in rows}

    def replace_snapshots(self, values: dict[str, str]) -> None:
        self.connection.execute("DELETE FROM snapshots")
        self.connection.executemany("INSERT INTO snapshots(source, digest) VALUES (?, ?)", values.items())
        self.connection.commit()

    def enqueue(self, source: str, digest: str, kind: str, settle_seconds: float) -> bool:
        now = time.time()
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO events(source, digest, kind, detected_at, ready_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source, digest, kind, now, now + settle_seconds),
        )
        self.connection.commit()
        return bool(cursor.rowcount)

    def ready(self, now: float | None = None) -> list[sqlite3.Row]:
        current = time.time() if now is None else now
        return list(
            self.connection.execute(
                """
                SELECT * FROM events
                WHERE status IN ('pending', 'retry') AND ready_at <= ?
                ORDER BY detected_at, id
                """,
                (current,),
            )
        )

    def recover_running(self) -> None:
        self.connection.execute("UPDATE events SET status='retry', ready_at=? WHERE status='running'", (time.time(),))
        self.connection.commit()

    def mark_running(self, ids: Iterable[int]) -> None:
        self.connection.executemany("UPDATE events SET status='running' WHERE id=?", ((item,) for item in ids))
        self.connection.commit()

    def complete(self, ids: Iterable[int]) -> None:
        now = time.time()
        self.connection.executemany(
            "UPDATE events SET status='done', completed_at=?, last_error=NULL WHERE id=?",
            ((now, item) for item in ids),
        )
        self.connection.commit()

    def retry(self, ids: Iterable[int], error: str, base_seconds: float) -> None:
        now = time.time()
        for item in ids:
            row = self.connection.execute("SELECT attempts FROM events WHERE id=?", (item,)).fetchone()
            attempts = int(row["attempts"] if row else 0) + 1
            delay = min(3600.0, base_seconds * (2 ** min(attempts - 1, 7)))
            self.connection.execute(
                "UPDATE events SET status='retry', attempts=?, ready_at=?, last_error=? WHERE id=?",
                (attempts, now + delay, error[:2000], item),
            )
        self.connection.commit()

    def counts(self) -> dict[str, int]:
        rows = self.connection.execute("SELECT status, COUNT(*) AS count FROM events GROUP BY status")
        return {str(row["status"]): int(row["count"]) for row in rows}


class MemoryPipeline:
    def __init__(self, config: PipelineConfig, runner=subprocess.run):
        self.config = config
        self.runner = runner
        self.store = EventStore(config.state_dir / "events.sqlite3")

    def close(self) -> None:
        self.store.close()

    def source_hashes(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for pattern in self.config.source_globs:
            for path in self.config.root.glob(pattern):
                if path.is_file():
                    relative = path.relative_to(self.config.root).as_posix()
                    values[relative] = file_sha256(path)
        return dict(sorted(values.items()))

    def scan(self) -> int:
        live = self.source_hashes()
        previous = self.store.snapshots()
        count = 0
        for source, digest in live.items():
            if previous.get(source) != digest:
                count += int(self.store.enqueue(source, digest, "upsert", self.config.settle_seconds))
        for source in previous.keys() - live.keys():
            count += int(self.store.enqueue(source, "deleted", "delete", self.config.settle_seconds))
        self.store.replace_snapshots(live)
        return count

    def _expanded_argv(self, stage: Stage) -> list[str]:
        replacements = {
            "{python}": sys.executable,
            "{root}": str(self.config.root),
            "{state_dir}": str(self.config.state_dir),
            "{config}": str(self.config.config_path),
        }
        return [replacements.get(token, token) for token in stage.argv]

    def _run_stage(self, stage: Stage) -> None:
        result = self.runner(
            self._expanded_argv(stage),
            cwd=str(self.config.root),
            text=True,
            capture_output=True,
            timeout=self.config.command_timeout,
            check=False,
        )
        if result.returncode:
            output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            raise RuntimeError(f"{stage.name} exited {result.returncode}: {output[-1800:]}")

    def _write_health(self, state: str, detail: str, metrics: dict[str, object] | None = None) -> None:
        atomic_json(
            self.config.health,
            {
                "schema_version": "agentready.memory_pipeline.v1",
                "generated_at_utc": utc_now(),
                "state": state,
                "detail": detail,
                "config": str(self.config.config_path),
                "queue": self.store.counts(),
                "metrics": metrics or {},
            },
        )

    def _annotate_converged(self, field: str, detail: str) -> bool:
        if not self.config.health.exists():
            return False
        try:
            health = json.loads(self.config.health.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if health.get("state") != "CONVERGED":
            return False
        health.update({field: utc_now(), "detail": detail, "queue": self.store.counts()})
        atomic_json(self.config.health, health)
        return True

    def run_once(self, reconcile: bool = False) -> int:
        try:
            with ProcessLock(self.config.state_dir / "pipeline.lock"):
                self.store.recover_running()
                self.scan()
                if reconcile and not self.store.ready():
                    self.store.enqueue("__reconcile__", utc_now(), "reconcile", 0)
                events = self.store.ready()
                if not events:
                    if not self._annotate_converged("last_idle_poll_utc", "No ready changes; convergence is current."):
                        self._write_health("IDLE", "No ready changes; no convergence run has completed yet.")
                    return 0
                ids = [int(event["id"]) for event in events]
                self.store.mark_running(ids)
                try:
                    for stage in self.config.stages:
                        self._run_stage(stage)
                    discovered = self.scan()
                except Exception as error:
                    self.store.retry(ids, f"{type(error).__name__}: {error}", self.config.retry_base_seconds)
                    self._write_health("DEGRADED", str(error))
                    return 1
                self.store.complete(ids)
                metrics: dict[str, object] = {
                    "source_count": len(self.source_hashes()),
                    "stages": [stage.name for stage in self.config.stages],
                }
                if discovered:
                    self._write_health(
                        "CATCHING_UP", "Sources changed during stage execution; another pass is queued.", metrics
                    )
                else:
                    self._write_health(
                        "CONVERGED", "All configured stages passed against the current source hashes.", metrics
                    )
                return 0
        except PipelineBusy:
            return 0

    def watch(self) -> int:
        if not self._annotate_converged("watcher_started_utc", "Watcher is running; convergence is current."):
            self._write_health("STARTING", "Watcher started; scanning declared sources.")
        while True:
            try:
                self.run_once()
            except Exception as error:  # daemon supervision must survive unexpected faults
                self._write_health("DEGRADED", f"watch loop: {type(error).__name__}: {error}")
            time.sleep(max(1.0, self.config.poll_seconds))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", choices=("validate", "enqueue", "once", "watch", "status"))
    parser.add_argument("--reconcile", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PipelineConfig.load(args.config)
    if args.command == "validate":
        print(
            json.dumps({"status": "VALID", "root": str(config.root), "stages": [item.name for item in config.stages]})
        )
        return 0
    pipeline = MemoryPipeline(config)
    try:
        if args.command == "enqueue":
            print(json.dumps({"enqueued": pipeline.scan(), "queue": pipeline.store.counts()}))
            return 0
        if args.command == "once":
            return pipeline.run_once(reconcile=args.reconcile)
        if args.command == "watch":
            return pipeline.watch()
        if config.health.exists():
            text = config.health.read_text(encoding="utf-8")
            print(text, end="")
            health = json.loads(text)
            return 0 if health.get("state") in {"CONVERGED", "IDLE", "CATCHING_UP"} else 1
        print(json.dumps({"state": "UNINITIALIZED", "queue": pipeline.store.counts()}))
        return 1
    finally:
        pipeline.close()


if __name__ == "__main__":
    raise SystemExit(main())
