# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.historical_chat import (
    STRONG_KEYWORD_DEFAULTS,
    _keyword_pattern,
    historical_chats_root,
    import_historical_chats,
    sample_historical_chats,
)

# A realish GitHub token (matches the safety severe detector, no fake marker) so a
# segment carrying it is quarantined with its text dropped.
_REALISH_GH_TOKEN = "ghp_" + "ab" * 18


def _conv(title, *messages, conv_id="c1", create_time=1.0, update_time=2.0):
    mapping = {}
    for i, (role, text) in enumerate(messages):
        mapping[f"n{i}"] = {"message": {"author": {"role": role}, "content": {"parts": [text]}, "create_time": float(i)}}
    return {"id": conv_id, "conversation_id": conv_id, "title": title, "create_time": create_time,
            "update_time": update_time, "mapping": mapping}


def _write_export(path, conversations):
    path.write_text(json.dumps({"conversations": conversations}), encoding="utf-8")


def test_import_emits_all_files_restricted_use(tmp_path):
    src = tmp_path / "conversations.json"
    _write_export(src, [_conv("AgentReady planning", ("user", "let us design ClaimEvidence"), ("assistant", "ok"))])
    result = import_historical_chats(tmp_path, source_path=src)
    out = historical_chats_root(tmp_path)
    for name in (
        "historical_chat_sessions.jsonl", "historical_chat_segments.jsonl",
        "historical_chat_dataset_records.jsonl", "historical_chat_manifest.json",
        "historical_chat_rights_report.json", "historical_chat_signal_coverage_report.json",
    ):
        assert (out / name).exists(), name
    assert result["status"] == "CURATED_READY"
    assert result["session_count"] == 1 and result["segment_count"] == 2
    assert result["all_restricted_use"] is True
    assert result["external_release_allowed"] is False and result["commercial_sale_allowed"] is False
    # every session is graded restricted-use
    rights = json.loads((out / "historical_chat_rights_report.json").read_text(encoding="utf-8"))
    assert rights["all_restricted_use"] is True and rights["export_allowed_rows"] == 0


def test_segment_readback_matches_emitted_rows(tmp_path):
    src = tmp_path / "conversations.json"
    # include a Unicode line separator (U+2028) in a message to exercise JSONL escaping
    _write_export(src, [_conv("notes", ("user", "line1" + chr(0x2028) + "line2"), ("assistant", "a" + chr(0x2029) + "b"))])
    result = import_historical_chats(tmp_path, source_path=src)
    out = historical_chats_root(tmp_path)
    rows = (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8").split("\n")
    rows = [r for r in rows if r.strip()]
    assert len(rows) == result["segment_count"] == 2  # readback == emitted, no silent loss
    assert result["segment_readback_matches"] is True
    # the separators survive inside the JSON field, not as raw row breaks
    seg0 = json.loads(rows[0])
    assert chr(0x2028) in seg0["text"]


def test_severe_secret_segment_quarantined_text_dropped(tmp_path):
    src = tmp_path / "conversations.json"
    _write_export(src, [_conv("leak", ("user", f"token is {_REALISH_GH_TOKEN}"), ("assistant", "ok"))])
    result = import_historical_chats(tmp_path, source_path=src)
    out = historical_chats_root(tmp_path)
    segs = [json.loads(r) for r in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8").split("\n") if r.strip()]
    secret_seg = next(s for s in segs if s["quarantined"])
    assert secret_seg["text"] is None  # dropped, not stored
    assert secret_seg["data_rights"]["grade"] == "F_QUARANTINE"
    assert result["quarantined_segments"] == 1
    # the raw token never appears anywhere in the emitted segment rows
    assert _REALISH_GH_TOKEN not in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8")


def test_email_redacted_in_place_no_leak(tmp_path):
    src = tmp_path / "conversations.json"
    _write_export(src, [_conv("contact", ("user", "reach me at dev@example.org please"))])
    import_historical_chats(tmp_path, source_path=src)
    out = historical_chats_root(tmp_path)
    blob = (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8")
    assert "dev@example.org" not in blob
    assert "<REDACTED:EMAIL>" in blob


def test_keyword_pattern_is_word_boundary():
    # "RAG" must not match inside "storage" / "dragon"
    assert _keyword_pattern("RAG").search("retrieval RAG pipeline") is not None
    assert _keyword_pattern("RAG").search("storage and dragons") is None
    assert "agentready" in STRONG_KEYWORD_DEFAULTS


def test_sampler_strong_vs_weak_scoring(tmp_path):
    src = tmp_path / "conversations.json"
    out = tmp_path / "pilot"
    _write_export(src, [
        _conv("AgentReady design", ("user", "the agentready eval gate"), conv_id="strong1"),  # 1 strong hit -> selected
        _conv("random chat", ("user", "the weather is nice"), conv_id="none1"),  # no hit -> excluded
        _conv("two weak terms", ("user", "training and dataset talk"), conv_id="weak2"),  # 2 weak hits -> selected
        _conv("one weak term", ("user", "just training talk"), conv_id="weak1"),  # 1 weak hit -> excluded
    ])
    result = sample_historical_chats(src, out, keywords="agentready,training,dataset", limit=20)
    assert result["selected_count"] == 2
    manifest = json.loads((out / "pilot_manifest.json").read_text(encoding="utf-8"))
    # manifest carries hashed ids + redacted titles only, never raw message bodies
    assert all("conversation_id_hash" in e and "text" not in e for e in manifest["conversations"])
    pilot = json.loads((out / "pilot_conversations.json").read_text(encoding="utf-8"))
    assert len(pilot) == 2  # full structure kept for downstream import


def test_sampler_limit_and_no_keyword(tmp_path):
    src = tmp_path / "conversations.json"
    out = tmp_path / "pilot"
    _write_export(src, [_conv(f"chat {i}", ("user", "hi"), conv_id=f"c{i}", update_time=float(i)) for i in range(5)])
    # no keyword filter -> selected by limit
    result = sample_historical_chats(src, out, keywords="", limit=3)
    assert result["selected_count"] == 3


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    assert adf.import_historical_chats is import_historical_chats
    assert adf.sample_historical_chats is sample_historical_chats
    assert adf.historical_chats_root is historical_chats_root
