# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agent_memory_pipeline import MemoryPipeline, PipelineConfig


class MemoryPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.memory = self.root / "memories" / "example.md"
        self.memory.parent.mkdir(parents=True)
        self.memory.write_text("# Synthetic memory\n", encoding="utf-8")
        self.config_path = self.base / "pipeline.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "state_dir": str(self.base / "state"),
                    "settle_seconds": 0,
                    "retry_base_seconds": 0,
                    "stages": [{"name": "synthetic verifier", "argv": ["{python}", "-c", "print('ok')"]}],
                }
            ),
            encoding="utf-8",
        )
        self.config = PipelineConfig.load(self.config_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def success_runner(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "ok", "")

    def test_direct_writer_is_detected_and_pipeline_converges(self) -> None:
        runner = Mock(side_effect=self.success_runner)
        worker = MemoryPipeline(self.config, runner=runner)
        try:
            self.assertEqual(0, worker.run_once())
            health = json.loads(self.config.health.read_text(encoding="utf-8"))
            self.assertEqual("CONVERGED", health["state"])
            self.assertEqual(1, health["metrics"]["source_count"])
            self.assertEqual(["synthetic verifier"], health["metrics"]["stages"])
            self.assertEqual(1, runner.call_count)
        finally:
            worker.close()

    def test_scan_is_idempotent_and_detects_deletion(self) -> None:
        worker = MemoryPipeline(self.config, runner=self.success_runner)
        try:
            self.assertEqual(1, worker.scan())
            self.assertEqual(0, worker.scan())
            self.memory.unlink()
            self.assertEqual(1, worker.scan())
        finally:
            worker.close()

    def test_failure_is_retried_and_not_abandoned(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 7, "", "synthetic failure"))
        worker = MemoryPipeline(self.config, runner=runner)
        try:
            self.assertEqual(1, worker.run_once())
            self.assertEqual({"retry": 1}, worker.store.counts())
            health = json.loads(self.config.health.read_text(encoding="utf-8"))
            self.assertEqual("DEGRADED", health["state"])
        finally:
            worker.close()

    def test_running_lease_recovers_after_restart(self) -> None:
        worker = MemoryPipeline(self.config, runner=self.success_runner)
        worker.scan()
        event = worker.store.ready()[0]
        worker.store.mark_running([int(event["id"])])
        worker.close()
        reopened = MemoryPipeline(self.config, runner=self.success_runner)
        try:
            reopened.store.recover_running()
            self.assertEqual({"retry": 1}, reopened.store.counts())
        finally:
            reopened.close()

    def test_idle_and_startup_preserve_convergence_evidence(self) -> None:
        worker = MemoryPipeline(self.config, runner=self.success_runner)
        try:
            self.assertEqual(0, worker.run_once())
            worker._annotate_converged("watcher_started_utc", "running")
            self.assertEqual(0, worker.run_once())
            health = json.loads(self.config.health.read_text(encoding="utf-8"))
            self.assertEqual("CONVERGED", health["state"])
            self.assertIn("watcher_started_utc", health)
            self.assertIn("last_idle_poll_utc", health)
        finally:
            worker.close()

    def test_configuration_rejects_escape_glob(self) -> None:
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw["source_globs"] = ["../private/**/*.md"]
        self.config_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stay within root"):
            PipelineConfig.load(self.config_path)

    def test_public_assets_do_not_embed_private_topology(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        paths = [
            repository / "src" / "agent_memory_pipeline.py",
            repository / "scripts" / "register-memory-pipeline.ps1",
            repository / "integrations" / "claude-memory-pipeline-hook.py",
            repository / "docs" / "autonomous-memory-pipeline.md",
            repository / "examples" / "memory-pipeline.config.json",
        ]
        forbidden = (
            "Serena" + "Data",
            "192" + ".168.",
            "qw" + "en",
            "al" + "exb",
            "Sovereign" + "Forge",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for marker in forbidden:
            self.assertNotIn(marker, combined)
