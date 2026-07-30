"""Historical ChatGPT import / pilot sampler for the Agent Data Foundry.

Phase E1 of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the internal-only historical chat import + pilot sampler subsystem moved verbatim out
of agent_data_foundry.py with **no behavior change**. This is a near-leaf: it imports
only the sibling library modules (io_jsonl for JSON/JSONL IO incl. the U+2028/U+2029
escaping + readback, safety_scan for redaction/quarantine, rights for the internal-only
default grade) and the stdlib — it never imports back from agent_data_foundry, so there
is no import cycle.

The lane is strictly internal: every record is graded A_INTERNAL_RESEARCH_ONLY
(export/eval/training/sale all false), session/segment IDs are hashed, segment text is
redacted in place and severe-secret segments have their text dropped + quarantined,
nothing is promoted to training gold, and no derived observations / labels are
fabricated. Primary source is the ChatGPT `conversations.json` only (no chat.html, no
media/audio/user.json/message_feedback/shared_conversations). Keyword matching is
word-boundary + case-insensitive so short terms never over-match substrings.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    as_dict,
    as_list,
    jsonl_row_count,
    now_utc,
    read_json_value,
    rel,
    write_json,
)
from agent_data_foundry_lib.paths import AGENTREADY_HOME
from agent_data_foundry_lib.rights import (
    default_data_need,
    default_data_rights,
    quarantine_data_rights_for_signal,
)
from agent_data_foundry_lib.safety_scan import _scan_source_signal_value


def historical_chats_root(root: Path) -> Path:
    return root / "data" / "training-library" / "30_curated" / "internal" / "historical-chats"


def _historical_internal_rights() -> dict[str, Any]:
    return default_data_rights(
        grade="A_INTERNAL_RESEARCH_ONLY",
        allowed_uses=["internal_research", "internal_eval"],
        forbidden_uses=["external_release", "external_training", "external_eval", "commercial_sale", "public_sample_pack"],
        export_allowed=False,
        external_eval_allowed=False,
        external_training_allowed=False,
        commercial_sale_allowed=False,
        requires_legal_review=True,
        requires_founder_release=True,
        reason="Historical chat: internal research only -- fossilized project cognition, never external.",
    )


def _historical_internal_need() -> dict[str, Any]:
    return default_data_need(
        primary_need="FACTORY_DOJO_INTERNAL",
        technical_value="MEDIUM",
        value_reason="Historical chat imported for internal long-horizon learning.",
    )


def _load_chatgpt_export(source: Path) -> Any:
    """Load a ChatGPT conversations.json from a file, a directory containing one,
    or an export .zip. Returns the parsed JSON or None."""
    source = Path(source)
    if source.is_dir():
        candidate = source / "conversations.json"
        return read_json_value(candidate) if candidate.exists() else None
    if source.suffix.lower() == ".zip" and source.exists():
        import zipfile

        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.endswith("conversations.json")]
            if not names:
                return None
            with archive.open(names[0]) as handle:
                return json.loads(handle.read().decode("utf-8"))
    if source.suffix.lower() == ".json" and source.exists():
        return read_json_value(source)
    return None


def _chatgpt_conversation_messages(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract ordered (role, text, create_time) messages from a ChatGPT
    conversation's node mapping. Empty/non-text nodes are skipped."""
    mapping = as_dict(conversation.get("mapping"))
    messages: list[dict[str, Any]] = []
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        role = str((message.get("author") or {}).get("role") or "unknown")
        content = as_dict(message.get("content"))
        parts = as_list(content.get("parts"))
        text = "\n".join(part for part in parts if isinstance(part, str)).strip()
        if not text:
            continue
        messages.append({"role": role, "text": text, "create_time": message.get("create_time")})
    messages.sort(key=lambda item: item.get("create_time") or 0)
    return messages


def import_historical_chats(root: Path | str = AGENTREADY_HOME, source_path: str | Path | None = None) -> dict[str, Any]:
    """Tiny ChatGPT export parser for the internal-only historical chat lane.
    Parses conversations.json, normalizes, hashes IDs, grades every record
    internal-only, redacts/quarantines segment text (severe secret -> the segment
    text is dropped), and emits the internal output files. No summarizer, no
    semantic segmentation -- segment_kind stays `unknown`, derived observations
    stay empty (never fabricated). Never writes raw frontier transcripts outside
    the internal lane and never under 40_release_ready."""
    root = Path(root)
    out_root = historical_chats_root(root)
    out_root.mkdir(parents=True, exist_ok=True)
    payload = _load_chatgpt_export(Path(source_path)) if source_path else None
    conversations = payload if isinstance(payload, list) else (payload or {}).get("conversations") if isinstance(payload, dict) else []
    conversations = conversations or []

    sessions: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    dojo_records: list[dict[str, Any]] = []
    quarantined_segments = 0
    redacted_segments = 0
    grade_counts: dict[str, int] = {}

    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conv_id = str(conversation.get("conversation_id") or conversation.get("id") or "")
        raw_title = str(conversation.get("title") or "")
        title_clean, _tf, _tr, _ts = _scan_source_signal_value(raw_title)
        session_id = hashlib.sha256((conv_id or raw_title or "untitled").encode("utf-8")).hexdigest()[:24]
        messages = _chatgpt_conversation_messages(conversation)
        role_counts: dict[str, int] = {}
        session_quarantined = False

        for index, message in enumerate(messages):
            role = str(message["role"])
            role_counts[role] = role_counts.get(role, 0) + 1
            cleaned, findings, redacted, severe = _scan_source_signal_value(str(message["text"]))
            segment_id = hashlib.sha256(f"{session_id}:{index}".encode("utf-8")).hexdigest()[:24]
            segment = {
                "schema_version": "sf.historical_chat_segment.v0.1",
                "session_id": session_id,
                "segment_id": segment_id,
                "source_type": "chatgpt_export",
                "role": role,
                "segment_index": index,
                "segment_kind": "unknown",
                "redacted": bool(redacted or severe),
                "quarantined": bool(severe),
                "findings": [{"detector": f.get("detector"), "severity": f.get("severity")} for f in findings],
            }
            if severe:
                # Severe secret material: drop the text, quarantine the segment.
                segment["text"] = None
                segment["data_rights"] = quarantine_data_rights_for_signal("historical_chat_segment_secret")
                quarantined_segments += 1
                session_quarantined = True
            else:
                segment["text"] = cleaned
                if redacted:
                    redacted_segments += 1
            segments.append(segment)

        need = _historical_internal_need()
        rights = _historical_internal_rights()
        grade_counts[rights["grade"]] = grade_counts.get(rights["grade"], 0) + 1
        sessions.append({
            "schema_version": "sf.historical_chat_session.v0.1",
            "session_id": session_id,
            "source_type": "chatgpt_export",
            "title": title_clean,
            "message_count": len(messages),
            "role_counts": role_counts,
            "create_time": conversation.get("create_time"),
            "update_time": conversation.get("update_time"),
            "model_hints": [],  # never the app/agent name as a model name
            "any_segment_quarantined": session_quarantined,
            "data_need": need,
            "data_rights": rights,
        })
        dojo_records.append({
            "schema_version": "sf.historical_chat_dojo_record.v0.1",
            "session_id": session_id,
            "source_type": "chatgpt_export",
            "message_count": len(messages),
            "role_counts": role_counts,
            "segment_kinds": {"unknown": len(messages)},
            "derived_observations": [],  # filled by a later slice; never fabricated here
            "any_segment_quarantined": session_quarantined,
            "data_need": need,
            "data_rights": rights,
        })

    segments_path = out_root / "historical_chat_segments.jsonl"
    append_jsonl(out_root / "historical_chat_sessions.jsonl", sessions)
    append_jsonl(segments_path, segments)
    append_jsonl(out_root / "historical_chat_dojo_records.jsonl", dojo_records)

    # Self-check: every emitted segment row must read back (no silent loss from a
    # Unicode line separator). A mismatch is a hard signal, not a rounding error.
    segment_readback_count = jsonl_row_count(segments_path)

    export_rows = sum(1 for s in sessions if s["data_rights"].get("export_allowed"))
    sale_rows = sum(1 for s in sessions if s["data_rights"].get("commercial_sale_allowed"))
    manifest = {
        "schema_version": "sf.historical_chat_manifest.v0.1",
        "dataset_id": "historical-chats-internal",
        "status": "INHOUSE_READY",
        "generated_at": now_utc(),
        "source_path": str(source_path) if source_path else None,
        "session_count": len(sessions),
        "segment_count": len(segments),
        "segment_readback_count": segment_readback_count,
        "segment_readback_matches": segment_readback_count == len(segments),
        "dojo_record_count": len(dojo_records),
        "quarantined_segments": quarantined_segments,
        "redacted_segments": redacted_segments,
        "external_release_allowed": False,
        "commercial_sale_allowed": False,
    }
    write_json(out_root / "historical_chat_manifest.json", manifest)

    rights_report = {
        "schema_version": "sf.historical_chat_rights.v0.1",
        "generated_at": now_utc(),
        "record_count": len(sessions),
        "data_rights_grade_counts": grade_counts,
        "export_allowed_rows": export_rows,
        "commercial_sale_rows": sale_rows,
        "all_internal_only": export_rows == 0 and sale_rows == 0,
    }
    write_json(out_root / "historical_chat_rights_report.json", rights_report)

    coverage_report = {
        "schema_version": "sf.historical_chat_signal_coverage_report.v0.1",
        "generated_at": now_utc(),
        "sessions": len(sessions),
        "segments": len(segments),
        "segment_kind_counts": {"unknown": len(segments) - quarantined_segments, "quarantined": quarantined_segments},
        "quarantined_segments": quarantined_segments,
        "redacted_segments": redacted_segments,
        "model_hints_present": 0,
    }
    write_json(out_root / "historical_chat_signal_coverage_report.json", coverage_report)

    return {
        "status": "INHOUSE_READY",
        "session_count": len(sessions),
        "segment_count": len(segments),
        "segment_readback_count": segment_readback_count,
        "segment_readback_matches": segment_readback_count == len(segments),
        "quarantined_segments": quarantined_segments,
        "redacted_segments": redacted_segments,
        "external_release_allowed": False,
        "commercial_sale_allowed": False,
        "all_internal_only": rights_report["all_internal_only"],
        "output_root": rel(root, out_root),
    }


# Specific, high-signal project/tooling terms. A single strong hit selects a
# conversation; weak/generic terms need two hits. Keep these lowercased.
STRONG_KEYWORD_DEFAULTS = frozenset({
    "software factory", "agentready", "dataset quality", "data foundry", "release engineering",
    "local model", "agent workflow", "coding agent", "model runtime",
    "fine-tune", "lora", "qlora",
})


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Case-insensitive, word-boundary matcher. Short keywords like `RAG` match
    only as whole words -- never `storage` / `dragon`. Multiword terms match as
    phrases (`(?<!\\w)` / `(?!\\w)` anchor the alnum edges)."""
    return re.compile(r"(?<!\w)" + re.escape(keyword.strip()) + r"(?!\w)", re.IGNORECASE)


def sample_historical_chats(
    source_path: str | Path | None,
    output_dir: str | Path | None,
    keywords: Any = None,
    limit: int = 20,
    strong_keywords: Any = None,
) -> dict[str, Any]:
    """Pilot sampler: read a ChatGPT conversations.json and emit a small
    (<= limit) pilot_conversations.json selected by keyword/title match, plus a
    pilot_manifest.json of metadata only (hashed conversation IDs, titles,
    timestamps, message counts, keyword hits, reason). Matching is
    word-boundary + case-insensitive, so short keywords do not over-match
    substrings; a conversation is selected on 1 strong-keyword hit or 2 weak hits.
    Does NOT import the full export, copy media, parse chat.html, or use user.json.
    The pilot conversations keep full structure so import-historical-chats can run
    against them; the manifest carries no raw message bodies."""
    out_dir = Path(output_dir) if output_dir else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _load_chatgpt_export(Path(source_path)) if source_path else None
    conversations = payload if isinstance(payload, list) else (payload or {}).get("conversations") if isinstance(payload, dict) else []
    conversations = conversations or []

    if isinstance(keywords, (list, tuple)):
        keyword_list = [str(k).strip() for k in keywords if str(k).strip()]
    else:
        keyword_list = [k.strip() for k in str(keywords or "").split(",") if k.strip()]
    if isinstance(strong_keywords, (list, tuple)):
        explicit_strong = {str(k).strip().lower() for k in strong_keywords if str(k).strip()}
    else:
        explicit_strong = {k.strip().lower() for k in str(strong_keywords or "").split(",") if k.strip()}
    strong_set = explicit_strong | set(STRONG_KEYWORD_DEFAULTS)
    patterns = [(k, _keyword_pattern(k), k.lower() in strong_set) for k in keyword_list]

    scored: list[dict[str, Any]] = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        title = str(conversation.get("title") or "")
        messages = _chatgpt_conversation_messages(conversation)
        blob = title + "\n" + "\n".join(str(m["text"]) for m in messages)  # regex is IGNORECASE
        strong_hits = [keyword for keyword, pattern, is_strong in patterns if is_strong and pattern.search(blob)]
        weak_hits = [keyword for keyword, pattern, is_strong in patterns if not is_strong and pattern.search(blob)]
        if keyword_list and not (len(strong_hits) >= 1 or len(weak_hits) >= 2):
            continue  # 1 strong hit OR 2 weak hits required
        scored.append({
            "conversation": conversation,
            "title": title,
            "message_count": len(messages),
            "keyword_hits": strong_hits + weak_hits,
            "strong_hits": strong_hits,
            "weak_hits": weak_hits,
            "hit_score": len(strong_hits) * 3 + len(weak_hits),
            "create_time": conversation.get("create_time"),
            "update_time": conversation.get("update_time"),
        })

    scored.sort(key=lambda item: (item["hit_score"], item.get("update_time") or 0), reverse=True)
    selected = scored[: max(0, int(limit))]

    pilot_conversations = [item["conversation"] for item in selected]
    pilot_path = out_dir / "pilot_conversations.json"
    write_json(pilot_path, pilot_conversations)

    entries: list[dict[str, Any]] = []
    for item in selected:
        title_clean, _f, _r, _s = _scan_source_signal_value(item["title"])
        conversation = item["conversation"]
        conv_id = str(conversation.get("conversation_id") or conversation.get("id") or item["title"] or "untitled")
        entries.append({
            "conversation_id_hash": hashlib.sha256(conv_id.encode("utf-8")).hexdigest()[:24],
            "title": title_clean,  # redacted; no raw bodies in the manifest
            "create_time": item["create_time"],
            "update_time": item["update_time"],
            "message_count": item["message_count"],
            "keyword_hits": item["keyword_hits"],
            "strong_hits": item["strong_hits"],
            "weak_hits": item["weak_hits"],
            "hit_score": item["hit_score"],
            "reason_selected": (
                f"{len(item['strong_hits'])} strong [{', '.join(item['strong_hits'])}]"
                f" + {len(item['weak_hits'])} weak [{', '.join(item['weak_hits'])}]"
                if item["keyword_hits"] else "selected by limit (no keyword filter)"
            ),
        })

    manifest = {
        "schema_version": "sf.historical_chat_pilot_manifest.v0.1",
        "generated_at": now_utc(),
        "source_path": str(source_path) if source_path else None,
        "source_conversation_count": len(conversations),
        "keywords": keyword_list,
        "limit": int(limit),
        "selected_count": len(selected),
        "pilot_conversations_path": str(pilot_path),
        "conversations": entries,
    }
    manifest_path = out_dir / "pilot_manifest.json"
    write_json(manifest_path, manifest)

    return {
        "source_conversation_count": len(conversations),
        "selected_count": len(selected),
        "keywords": keyword_list,
        "pilot_conversations_path": str(pilot_path),
        "pilot_manifest_path": str(manifest_path),
    }
