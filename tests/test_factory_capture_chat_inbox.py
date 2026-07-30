# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
import zipfile

from factory_capture import chat_inbox
from factory_capture.common import read_jsonl
from factory_capture.store import Store


def _conversations(secret: str | None = None) -> list:
    user_text = "how do we build the data foundry?"
    if secret:
        user_text = f"contact me@example.com and token {secret}"
    return [{
        "title": "AgentReady planning", "conversation_id": "c1",
        "mapping": {
            "a": {"message": {"author": {"role": "user"}, "content": {"parts": [user_text]}, "create_time": 1.0}},
            "b": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["start with capture"]}, "create_time": 2.0}},
        },
    }]


def _inbox_store(tmp_path) -> Store:
    store = Store(tmp_path / ".factory_capture")
    chat_inbox.init_inbox(store)
    return store


def _drop_json(store, conversations) -> None:
    path = chat_inbox.inbox_paths(store)["inbox"] / "conversations.json"
    path.write_text(json.dumps(conversations), encoding="utf-8")


def _drop_zip(store, conversations, name="export.zip") -> None:
    path = chat_inbox.inbox_paths(store)["inbox"] / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(conversations))


def _scan(store, tmp_path) -> dict:
    return chat_inbox.scan(store, import_root=tmp_path, python_exe=sys.executable)


def _manifests(store) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in chat_inbox.inbox_paths(store)["manifests"].glob("*.manifest.json")]


def test_init_creates_layout(tmp_path):
    store = _inbox_store(tmp_path)
    paths = chat_inbox.inbox_paths(store)
    for name in chat_inbox.SUBDIRS:
        assert paths[name].is_dir()
    assert paths["config"].exists()
    assert json.loads(paths["config"].read_text(encoding="utf-8"))["schema"] == "sf.chat_inbox_config.v0.1"


def test_scan_processes_conversations_json_with_manifest_event_and_no_leak(tmp_path):
    store = _inbox_store(tmp_path)
    secret = "ghp_" + "ab" * 18
    _drop_json(store, _conversations(secret=secret))

    result = _scan(store, tmp_path)
    assert result["scanned"] == 1 and result["results"][0]["status"] == "processed"

    paths = chat_inbox.inbox_paths(store)
    # processed import goes to processed/, inbox emptied
    assert list(paths["processed"].glob("*conversations.json"))
    assert not list(paths["inbox"].glob("*"))

    # manifest written, restricted-use, not promoted
    manifests = _manifests(store)
    assert len(manifests) == 1
    man = manifests[0]
    assert man["schema"] == "sf.chat_inbox_manifest.v0.1" and man["status"] == "processed"
    assert man["restricted_use"] is True and man["promoted_to_gold"] is False
    assert man["import_exit_code"] == 0 and man["capture_event_id"]

    # a factory_capture command_run event for the importer was written
    events = read_jsonl(store.events_path)
    import_events = [e for e in events if e.get("event_type") == "command_run"
                     and any("import-historical-chats" in str(a) for a in (e.get("command") or []))]
    assert len(import_events) == 1 and import_events[0]["event_id"] == man["capture_event_id"]

    # the existing importer produced its canonical output under the (redirected) root
    assert (tmp_path / "data" / "training-library" / "30_curated" / "internal" / "historical-chats"
            / "historical_chat_manifest.json").exists()

    # no raw secret/email leaked into the inbox manifest
    blob = "".join(p.read_text(encoding="utf-8") for p in paths["manifests"].glob("*.manifest.json"))
    assert secret not in blob and "me@example.com" not in blob


def test_scan_processes_zip_fixture(tmp_path):
    store = _inbox_store(tmp_path)
    _drop_zip(store, _conversations())
    result = _scan(store, tmp_path)
    assert result["results"][0]["status"] == "processed"
    assert result["results"][0]["sha256"]
    assert list(chat_inbox.inbox_paths(store)["processed"].glob("*.zip"))
    assert (tmp_path / "data" / "training-library" / "30_curated" / "internal" / "historical-chats"
            / "historical_chat_manifest.json").exists()


def test_duplicate_file_skipped_by_sha256(tmp_path):
    store = _inbox_store(tmp_path)
    _drop_json(store, _conversations())
    first = _scan(store, tmp_path)
    assert first["results"][0]["status"] == "processed"

    # drop the SAME content again -> same sha -> skipped, importer NOT run a second time
    _drop_json(store, _conversations())
    second = _scan(store, tmp_path)
    assert second["results"][0]["status"] == "duplicate_skipped"
    assert second["results"][0]["capture_event_id"] is None

    events = read_jsonl(store.events_path)
    import_events = [e for e in events if e.get("event_type") == "command_run"
                     and any("import-historical-chats" in str(a) for a in (e.get("command") or []))]
    assert len(import_events) == 1  # only the first import ran


def test_failed_import_goes_to_failed(tmp_path):
    store = _inbox_store(tmp_path)
    # a corrupt .zip makes the importer raise BadZipFile -> non-zero exit -> failed/
    (chat_inbox.inbox_paths(store)["inbox"] / "broken.zip").write_bytes(b"this is not a valid zip archive")
    result = _scan(store, tmp_path)
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["exit_code"] not in (0, None)
    paths = chat_inbox.inbox_paths(store)
    assert list(paths["failed"].glob("*broken.zip"))
    assert not list(paths["processed"].glob("*"))
    man = _manifests(store)[0]
    assert man["status"] == "failed" and man["import_output_root"] is None


def test_cli_dispatch_init_status_and_guard(tmp_path, monkeypatch, capsys):
    import subprocess

    from factory_capture.cli import main
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    monkeypatch.chdir(tmp_path)

    assert main(["chat-inbox", "status"]) == 1  # guarded before init
    assert "not initialized" in capsys.readouterr().err
    assert main(["chat-inbox", "init"]) == 0
    assert "initialized" in capsys.readouterr().out
    assert main(["chat-inbox", "status"]) == 0
    assert "Historical Chat Inbox" in capsys.readouterr().out


def test_watch_runs_one_polling_cycle(tmp_path):
    store = _inbox_store(tmp_path)
    _drop_json(store, _conversations())
    calls = []
    summary = chat_inbox.watch(store, interval=0, max_cycles=1, import_root=tmp_path,
                               python_exe=sys.executable, sleep=lambda s: calls.append(s))
    assert summary["cycles"] == 1 and summary["total_scanned"] == 1
    assert calls == []  # one bounded cycle must not sleep
    assert list(chat_inbox.inbox_paths(store)["processed"].glob("*"))
