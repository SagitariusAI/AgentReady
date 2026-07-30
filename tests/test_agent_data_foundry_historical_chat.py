# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry import (
    append_jsonl,
    import_historical_chats,
    jsonl_row_count,
    read_jsonl,
    sample_historical_chats,
)

_HIST_DIR = Path("data") / "training-library" / "30_curated" / "internal" / "historical-chats"


def _chatgpt_conversation(conv_id: str, title: str, msgs: list[tuple[str, str, float]]) -> dict:
    mapping = {}
    for i, (role, text, t) in enumerate(msgs):
        nid = f"n{i}"
        mapping[nid] = {
            "id": nid, "parent": None, "children": [],
            "message": {"id": f"m{i}", "author": {"role": role}, "create_time": float(t),
                        "content": {"content_type": "text", "parts": [text]}},
        }
    return {"title": title, "conversation_id": conv_id, "create_time": 1.0, "update_time": 2.0, "mapping": mapping}


def _write_chatgpt_export(tmp_path: Path, conversations: list[dict]) -> Path:
    src = tmp_path / "conversations.json"
    src.write_text(json.dumps(conversations), encoding="utf-8")
    return src


def test_import_historical_chats_restricted_use(tmp_path: Path) -> None:
    export = [_chatgpt_conversation("conv-1", "Architecture chat",
              [("user", "How should we structure the harvest?", 1), ("assistant", "Use a layered envelope.", 2)])]
    src = _write_chatgpt_export(tmp_path, export)
    result = import_historical_chats(tmp_path, source_path=src)
    assert result["status"] == "CURATED_READY"
    assert result["session_count"] == 1 and result["segment_count"] == 2
    assert result["all_restricted_use"] is True

    out = tmp_path / _HIST_DIR
    sessions = [json.loads(line) for line in (out / "historical_chat_sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    s = sessions[0]
    assert s["data_rights"]["grade"] == "A_INTERNAL_RESEARCH_ONLY"
    assert s["data_rights"]["export_allowed"] is False and s["data_rights"]["commercial_sale_allowed"] is False
    assert s["data_rights"]["external_training_allowed"] is False
    assert s["session_id"] != "conv-1"  # hashed, not the raw id
    assert "text" not in s  # sessions carry no raw message bodies
    assert s["model_hints"] == []  # never the app name as a model

    segs = [json.loads(line) for line in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any("layered envelope" in (seg.get("text") or "") for seg in segs)
    assert all(seg["segment_kind"] == "unknown" for seg in segs)  # no semantic segmentation yet

    recs = [json.loads(line) for line in (out / "historical_chat_dataset_records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs[0]["derived_observations"] == []  # never fabricated
    assert "text" not in recs[0]  # derived record carries no raw text

    rights = json.loads((out / "historical_chat_rights_report.json").read_text(encoding="utf-8"))
    assert rights["all_restricted_use"] is True
    assert json.loads((out / "historical_chat_manifest.json").read_text(encoding="utf-8"))["commercial_sale_allowed"] is False
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_import_historical_chats_quarantines_secret(tmp_path: Path) -> None:
    token = "ghp_" + "ab" * 18  # real-looking token built at runtime
    export = [_chatgpt_conversation("c2", "Debug",
              [("user", f"my key is {token}", 1), ("assistant", "never paste secrets", 2)])]
    src = _write_chatgpt_export(tmp_path, export)
    result = import_historical_chats(tmp_path, source_path=src)
    assert result["quarantined_segments"] >= 1

    out = tmp_path / _HIST_DIR
    segs = [json.loads(line) for line in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8").splitlines()]
    secret_seg = next(seg for seg in segs if seg["quarantined"])
    assert secret_seg["text"] is None  # text dropped at the segment
    assert token not in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8")  # never stored
    sessions = [json.loads(line) for line in (out / "historical_chat_sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sessions[0]["any_segment_quarantined"] is True


def test_import_historical_chats_redacts_email(tmp_path: Path) -> None:
    export = [_chatgpt_conversation("c3", "Contact", [("user", "reach me at me@example.com please", 1)])]
    src = _write_chatgpt_export(tmp_path, export)
    import_historical_chats(tmp_path, source_path=src)
    out = tmp_path / _HIST_DIR
    seg = [json.loads(line) for line in (out / "historical_chat_segments.jsonl").read_text(encoding="utf-8").splitlines()][0]
    assert seg["redacted"] is True
    assert "me@example.com" not in (seg["text"] or "")
    assert "<REDACTED:EMAIL>" in seg["text"]


def test_import_historical_chats_empty_source(tmp_path: Path) -> None:
    result = import_historical_chats(tmp_path, source_path=None)
    assert result["session_count"] == 0 and result["segment_count"] == 0
    assert result["all_restricted_use"] is True  # nothing imported -> trivially restricted-use


def test_sample_historical_chats_selects_by_keyword(tmp_path: Path) -> None:
    export = [
        _chatgpt_conversation("c1", "AgentReady harvest design", [("user", "how does the ClaimEvidence data foundry grade rights?", 1)]),
        _chatgpt_conversation("c2", "Grocery list", [("user", "buy milk and eggs", 1)]),
        _chatgpt_conversation("c3", "DGX setup", [("user", "configure the local model on the DGX", 1)]),
    ]
    src = _write_chatgpt_export(tmp_path, export)
    out = tmp_path / "pilot"
    result = sample_historical_chats(src, out, keywords="AgentReady,ClaimEvidence,DGX,local model", limit=20)
    assert result["selected_count"] == 2  # c1 and c3 match; grocery list does not

    pilot = json.loads((out / "pilot_conversations.json").read_text(encoding="utf-8"))
    titles = {c["title"] for c in pilot}
    assert "Grocery list" not in titles  # unmatched conversation excluded

    manifest = json.loads((out / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert manifest["selected_count"] == 2
    assert all(entry["conversation_id_hash"] not in ("c1", "c3") for entry in manifest["conversations"])  # hashed
    assert all(len(entry["conversation_id_hash"]) == 24 for entry in manifest["conversations"])
    assert manifest["conversations"][0]["keyword_hits"]  # keyword hits recorded
    assert "strong" in manifest["conversations"][0]["reason_selected"]
    # No raw message bodies in the manifest.
    assert "buy milk" not in json.dumps(manifest)
    assert "grade rights" not in json.dumps(manifest)


def test_sample_historical_chats_respects_limit(tmp_path: Path) -> None:
    export = [_chatgpt_conversation(f"c{i}", f"AgentReady topic {i}", [("user", "AgentReady factory work", 1)]) for i in range(10)]
    src = _write_chatgpt_export(tmp_path, export)
    out = tmp_path / "pilot"
    result = sample_historical_chats(src, out, keywords="AgentReady", limit=3)
    assert result["selected_count"] == 3
    assert len(json.loads((out / "pilot_conversations.json").read_text(encoding="utf-8"))) == 3


def test_sample_pilot_is_importable(tmp_path: Path) -> None:
    export = [_chatgpt_conversation("c1", "AgentReady", [("user", "ClaimEvidence design", 1), ("assistant", "layered envelope", 2)])]
    src = _write_chatgpt_export(tmp_path, export)
    out = tmp_path / "pilot"
    sample_historical_chats(src, out, keywords="AgentReady", limit=20)
    # The pilot output runs cleanly through the importer.
    result = import_historical_chats(tmp_path, source_path=out / "pilot_conversations.json")
    assert result["session_count"] == 1
    assert result["all_restricted_use"] is True


def test_sample_keyword_word_boundary_no_substring_false_positive(tmp_path: Path) -> None:
    export = [
        # 'rag' lives inside storage/dragon -- must NOT match the keyword RAG.
        _chatgpt_conversation("c1", "Storage and dragons", [("user", "storage capacity and a dragon appeared", 1)]),
        # Real RAG word + a strong keyword -> selected.
        _chatgpt_conversation("c2", "RAG pipeline", [("user", "building a RAG retrieval system for AgentReady", 1)]),
    ]
    src = _write_chatgpt_export(tmp_path, export)
    out = tmp_path / "pilot"
    sample_historical_chats(src, out, keywords="RAG,AgentReady", limit=20)
    pilot = json.loads((out / "pilot_conversations.json").read_text(encoding="utf-8"))
    titles = {c["title"] for c in pilot}
    assert "Storage and dragons" not in titles  # RAG did not match storage/dragon
    assert "RAG pipeline" in titles


def test_sample_two_weak_hits_required(tmp_path: Path) -> None:
    # A single WEAK keyword hit is not enough; two weak hits select.
    export = [
        _chatgpt_conversation("c1", "one weak", [("user", "we used some training here", 1)]),  # only 'training' (weak)
        _chatgpt_conversation("c2", "two weak", [("user", "training a local model dataset", 1)]),  # training + dataset (2 weak)
    ]
    src = _write_chatgpt_export(tmp_path, export)
    out = tmp_path / "pilot"
    sample_historical_chats(src, out, keywords="training,dataset,forge", limit=20)
    titles = {c["title"] for c in json.loads((out / "pilot_conversations.json").read_text(encoding="utf-8"))}
    assert "one weak" not in titles  # single weak hit excluded
    assert "two weak" in titles  # two weak hits selected


def test_jsonl_preserves_unicode_line_separators(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [
        {"text": "line one" + chr(0x2028) + "line two"},
        {"text": "para" + chr(0x2029) + "graph"},
        {"text": "clean row"},
    ]
    append_jsonl(path, rows)
    # No literal line separators in the written file.
    raw = path.read_text(encoding="utf-8")
    assert chr(0x2028) not in raw and chr(0x2029) not in raw
    # Exactly 3 rows readable -- none silently dropped.
    assert jsonl_row_count(path) == 3
    back = read_jsonl(path)
    assert len(back) == 3
    assert back[0]["text"] == "line one" + chr(0x2028) + "line two"  # lossless round-trip


def test_import_historical_chats_segment_readback_matches(tmp_path: Path) -> None:
    export = [_chatgpt_conversation("c1", "AgentReady", [
        ("user", "a" + chr(0x2028) + "b with a U+2028 inside the message", 1),
        ("assistant", "c" + chr(0x2029) + "d too", 2),
    ])]
    src = _write_chatgpt_export(tmp_path, export)
    result = import_historical_chats(tmp_path, source_path=src)
    assert result["segment_readback_count"] == result["segment_count"]
    assert result["segment_readback_matches"] is True
