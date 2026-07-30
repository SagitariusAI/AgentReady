from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    append_jsonl_rows,
    jsonl_row_count,
    read_json,
    read_jsonl,
    write_json,
)


def test_jsonl_roundtrip_and_readback(tmp_path: Path) -> None:
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    p = tmp_path / "out.jsonl"
    append_jsonl(p, rows)
    assert jsonl_row_count(p) == 2
    assert read_jsonl(p) == rows  # readback == emitted


def test_jsonl_escapes_line_separators(tmp_path: Path) -> None:
    # U+2028/U+2029 must be escaped so they never split a row on read.
    # Built via chr() so the test never depends on invisible chars in source.
    sep28, sep29 = chr(0x2028), chr(0x2029)
    row = {"text": f"line1{sep28}line2{sep29}end"}
    p = tmp_path / "u.jsonl"
    append_jsonl(p, [row])
    raw = p.read_text(encoding="utf-8")
    assert sep28 not in raw and sep29 not in raw  # escaped to literal \uXXXX text, not the chars
    assert jsonl_row_count(p) == 1  # not split by the separators
    assert read_jsonl(p) == [row]  # lossless round-trip restores the chars


def test_append_jsonl_rows_appends_not_truncates(tmp_path: Path) -> None:
    p = tmp_path / "a.jsonl"
    append_jsonl_rows(p, [{"i": 1}])
    append_jsonl_rows(p, [{"i": 2}])
    assert jsonl_row_count(p) == 2


def test_append_jsonl_truncates_by_design(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    append_jsonl(p, [{"i": 1}, {"i": 2}])
    append_jsonl(p, [{"i": 3}])
    assert read_jsonl(p) == [{"i": 3}]  # append_jsonl opens "w" (truncate) -- preserved behavior


def test_read_write_json_roundtrip_and_missing(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    write_json(p, {"k": 1})
    assert read_json(p) == {"k": 1}
    assert read_json(tmp_path / "missing.json") is None


def test_jsonl_row_count_missing_file(tmp_path: Path) -> None:
    assert jsonl_row_count(tmp_path / "nope.jsonl") == 0
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_reexported_from_agent_data_foundry() -> None:
    # Phase A compat shim: the names still resolve from the top-level module,
    # and are the SAME objects as in the lib (no divergent copy).
    import agent_data_foundry as adf

    assert adf.read_jsonl is read_jsonl
    assert adf.write_json is write_json
    assert adf.jsonl_row_count is jsonl_row_count
    assert adf.append_jsonl is append_jsonl
