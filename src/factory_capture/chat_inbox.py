"""Historical Chat Inbox v0.1 — a folder-drop bridge from factory_capture to the existing Agent Data
Foundry historical-chat importer.

The founder drops an OpenAI ChatGPT export (`.zip`) or a `conversations.json` into the inbox folder.
`scan` stages each new item, runs the EXISTING `import-historical-chats` action **as a subprocess
through factory_capture** (so the import is captured as a `command_run` receipt), writes an import
manifest, and moves the item to processed/ or failed/. Duplicates (by sha256) are skipped.

It does NOT reimplement the importer: zip extraction + conversations.json location + redaction +
internal-only rights grading are all done by the foundry importer (`agent_data_foundry_lib.historical_chat`).
Historical chats stay internal-only candidates — no promotion to gold, no schema/output drift, no network."""
from __future__ import annotations

import hashlib
import shutil
import sys
import time
from pathlib import Path

from factory_capture.common import gen_event_id, now_iso, read_json, write_json
from factory_capture.gitstate import find_repo_root
from factory_capture.redaction import redact_text
from factory_capture.runner import run_command
from factory_capture.store import Store

MANIFEST_SCHEMA = "sf.chat_inbox_manifest.v0.1"
CONFIG_SCHEMA = "sf.chat_inbox_config.v0.1"
ROOT_NAME = "chat_inbox"
SUBDIRS = ("inbox", "processing", "processed", "failed", "manifests", "logs")
# the importer's canonical output, relative to the import root (no drift):
HISTORICAL_OUTPUT_REL = Path("data") / "training-library" / "30_curated" / "internal" / "historical-chats"


def inbox_paths(store: Store) -> dict[str, Path]:
    base = store.root / ROOT_NAME
    paths = {"base": base, "config": base / "config.json"}
    paths.update({name: base / name for name in SUBDIRS})
    return paths


def _foundry_script() -> Path:
    """The historical-chat importer CLI — a sibling of this package in src/."""
    return Path(__file__).resolve().parent.parent / "agent_data_foundry.py"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_items(inbox_dir: Path) -> list[Path]:
    """Authoritative inputs only: an OpenAI export .zip or a conversations.json."""
    if not inbox_dir.exists():
        return []
    items = []
    for path in sorted(inbox_dir.iterdir()):
        if path.is_file() and (path.suffix.lower() == ".zip" or path.name == "conversations.json"):
            items.append(path)
    return items


def _processed_shas(manifests_dir: Path) -> dict[str, str]:
    seen: dict[str, str] = {}
    for manifest in manifests_dir.glob("*.manifest.json"):
        data = read_json(manifest, {})
        if data.get("status") == "processed" and data.get("sha256"):
            seen[data["sha256"]] = data.get("manifest_id", "")
    return seen


def init_inbox(store: Store) -> dict:
    """Create the chat_inbox folder tree + config. Ensures the parent store exists."""
    if not store.exists():
        store.init()
    paths = inbox_paths(store)
    for name in SUBDIRS:
        paths[name].mkdir(parents=True, exist_ok=True)
    created = not paths["config"].exists()
    if created:
        write_json(paths["config"], {
            "schema": CONFIG_SCHEMA, "version": "0.1", "created_utc": now_iso(),
            "poll_interval_s": 10, "internal_only": True, "promote_to_gold": False,
        })
    return {"root": str(paths["base"]), "created": created, "subdirs": list(SUBDIRS)}


def _write_manifest(paths: dict, *, sha: str, source_name: str, kind: str, status: str,
                    event: dict | None, output_root: str | None, final_path: Path,
                    duplicate_of: str | None = None) -> dict:
    manifest_id = gen_event_id()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "manifest_id": manifest_id,
        "created_utc": now_iso(),
        "source_filename": redact_text(source_name)[0],
        "source_kind": kind,
        "sha256": sha,
        "status": status,
        "duplicate_of": duplicate_of,
        "capture_event_id": event.get("event_id") if event else None,
        "import_exit_code": event.get("exit_code") if event else None,
        "import_output_root": output_root,
        "final_path": str(final_path),
        "internal_only": True,
        "promoted_to_gold": False,
    }
    write_json(paths["manifests"] / f"{manifest_id}.manifest.json", manifest)
    return manifest


def _unique_dest(directory: Path, name: str) -> Path:
    dest = directory / name
    counter = 1
    while dest.exists():
        dest = directory / f"{Path(name).stem}__{counter}{Path(name).suffix}"
        counter += 1
    return dest


def _process_item(store: Store, paths: dict, item: Path, sha: str, kind: str,
                  import_root: Path, python_exe: str) -> dict:
    staged = _unique_dest(paths["processing"], f"{sha[:12]}__{item.name}")
    shutil.move(str(item), str(staged))
    command = [
        str(python_exe), str(_foundry_script()),
        "-Action", "import-historical-chats",
        "-DatasetPath", str(staged), "-Root", str(import_root),
    ]
    event = run_command(store, command, cwd=import_root)
    ok = event.get("exit_code") == 0
    status = "processed" if ok else "failed"
    dest_dir = paths["processed"] if ok else paths["failed"]
    final = _unique_dest(dest_dir, staged.name)
    shutil.move(str(staged), str(final))
    output_root = str(Path(import_root) / HISTORICAL_OUTPUT_REL) if ok else None
    manifest = _write_manifest(paths, sha=sha, source_name=item.name, kind=kind, status=status,
                               event=event, output_root=output_root, final_path=final)
    return {"source": item.name, "sha256": sha, "status": status,
            "manifest_id": manifest["manifest_id"], "capture_event_id": event.get("event_id"),
            "exit_code": event.get("exit_code")}


def _record_duplicate(paths: dict, item: Path, sha: str, kind: str, original: str) -> dict:
    final = _unique_dest(paths["processed"], f"{sha[:12]}__dup__{item.name}")
    shutil.move(str(item), str(final))
    manifest = _write_manifest(paths, sha=sha, source_name=item.name, kind=kind,
                               status="duplicate_skipped", event=None, output_root=None,
                               final_path=final, duplicate_of=original)
    return {"source": item.name, "sha256": sha, "status": "duplicate_skipped",
            "manifest_id": manifest["manifest_id"], "capture_event_id": None, "exit_code": None}


def scan(store: Store, import_root: Path | None = None, python_exe: str | None = None) -> dict:
    """Process every new authoritative item in inbox/. Returns a per-item result list."""
    paths = inbox_paths(store)
    if not paths["config"].exists():
        return {"error": "chat-inbox not initialized — run `factory-capture chat-inbox init` first"}
    import_root = Path(import_root) if import_root else find_repo_root(store.root.parent)
    python_exe = python_exe or sys.executable
    already = _processed_shas(paths["manifests"])
    results = []
    for item in _detect_items(paths["inbox"]):
        sha = _sha256_file(item)
        kind = "zip" if item.suffix.lower() == ".zip" else "conversations_json"
        if sha in already:
            results.append(_record_duplicate(paths, item, sha, kind, already[sha]))
        else:
            result = _process_item(store, paths, item, sha, kind, import_root, python_exe)
            results.append(result)
            if result["status"] == "processed":
                already[sha] = result["manifest_id"]
    return {"scanned": len(results), "results": results}


def watch(store: Store, interval: int = 10, max_cycles: int | None = None,
          import_root: Path | None = None, python_exe: str | None = None,
          sleep=time.sleep) -> dict:
    """Poll inbox every `interval`s, running scan each cycle. `max_cycles` bounds it (test mode)."""
    summary = {"cycles": 0, "total_scanned": 0}
    while max_cycles is None or summary["cycles"] < max_cycles:
        result = scan(store, import_root=import_root, python_exe=python_exe)
        summary["cycles"] += 1
        summary["total_scanned"] += result.get("scanned", 0)
        if max_cycles is not None and summary["cycles"] >= max_cycles:
            break
        sleep(interval)
    return summary


def status(store: Store) -> dict:
    paths = inbox_paths(store)

    def count(directory: Path) -> int:
        return sum(1 for x in directory.iterdir() if x.is_file()) if directory.exists() else 0

    manifests = sorted(paths["manifests"].glob("*.manifest.json"), key=lambda m: m.stat().st_mtime) \
        if paths["manifests"].exists() else []
    latest = read_json(manifests[-1]) if manifests else None
    return {
        "initialized": paths["config"].exists(),
        "inbox_root": str(paths["base"]),
        "pending": count(paths["inbox"]),
        "processing": count(paths["processing"]),
        "processed": count(paths["processed"]),
        "failed": count(paths["failed"]),
        "manifests": len(manifests),
        "latest": None if not latest else {
            "source": latest.get("source_filename"), "status": latest.get("status"),
            "sha256": (latest.get("sha256") or "")[:12], "capture_event_id": latest.get("capture_event_id"),
        },
    }


def render_status(snap: dict) -> str:
    latest = snap["latest"]
    latest_line = "(none)" if not latest else f"{latest['source']} [{latest['status']}] {latest['sha256']}"
    return "\n".join([
        "# Factory Capture -- Historical Chat Inbox",
        f"- inbox root : {snap['inbox_root']}",
        f"- initialized: {snap['initialized']}",
        f"- pending    : {snap['pending']}",
        f"- processing : {snap['processing']}",
        f"- processed  : {snap['processed']}",
        f"- failed     : {snap['failed']}",
        f"- manifests  : {snap['manifests']}",
        f"- latest     : {latest_line}",
    ]) + "\n"
