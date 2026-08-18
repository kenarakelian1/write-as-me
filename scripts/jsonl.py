"""Shared JSONL reader for every append-only log this plugin keeps
(drafts.jsonl, edits.jsonl, and any future one). One implementation so a fix
to how corrupt lines or a BOM are handled lands everywhere at once, instead
of being copied into each log module and drifting."""
from __future__ import annotations

import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    """Corrupt lines and non-dict JSON values are skipped, never raised —
    a damaged log must not take the caller down with it. Reads with
    utf-8-sig so a UTF-8 BOM (e.g. from a Windows-authored file) does not
    land inside the first key of the first record."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                out.append(item)
        except json.JSONDecodeError:
            continue
    return out
