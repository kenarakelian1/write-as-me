"""Finding 5 (final whole-branch review): draft_log.load_drafts and
edit_log.load_edits were byte-equivalent apart from their docstrings, copied
rather than shared. During this build edit_log.py shipped with the exact
BOM and non-dict-record bugs draft_log.py had already fixed, because the
logic lived in two places. scripts/jsonl.py centralizes it; both modules
must delegate to it rather than keep their own copy."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import draft_log  # noqa: E402
import edit_log  # noqa: E402
import jsonl  # noqa: E402
from jsonl import load_jsonl  # noqa: E402


def test_draft_log_and_edit_log_share_the_same_jsonl_loader():
    """Not just 'behaves the same' -- the same function object, so a future
    fix to the loader lands in both modules at once instead of needing to be
    copied twice and risking exactly the drift this finding describes."""
    assert draft_log.load_jsonl is jsonl.load_jsonl
    assert edit_log.load_jsonl is jsonl.load_jsonl


def test_load_jsonl_skips_corrupt_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\nnot json at all\n{"a": 2}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_load_jsonl_skips_non_dict_values(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('42\n"string"\nnull\n[1, 2]\n{"a": 1}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"a": 1}]


def test_load_jsonl_handles_a_utf8_bom(tmp_path):
    path = tmp_path / "log.jsonl"
    with path.open("wb") as handle:
        handle.write(b"\xef\xbb\xbf")
        handle.write('{"a": 1}\n'.encode("utf-8"))
    assert load_jsonl(path) == [{"a": 1}]


def test_load_jsonl_missing_file_is_empty_not_an_error(tmp_path):
    assert load_jsonl(tmp_path / "nope.jsonl") == []
