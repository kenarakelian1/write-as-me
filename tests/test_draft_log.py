from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from draft_log import (  # noqa: E402
    expire_old,
    load_drafts,
    make_id,
    pending,
    record_draft,
    set_status,
)

CREATED = "2026-08-18T14:02:11-04:00"


def test_make_id_is_deterministic_and_dated():
    a = make_id(CREATED, "Listings - what changes")
    b = make_id(CREATED, "Listings - what changes")
    assert a == b
    assert a.startswith("d-20260818-")
    assert len(a) == len("d-20260818-") + 4


def test_make_id_differs_by_subject():
    assert make_id(CREATED, "one") != make_id(CREATED, "two")


def test_record_and_load_round_trip(tmp_path):
    log = tmp_path / "drafts.jsonl"
    draft_id = record_draft(
        "client", ["caden@example.com"], "Listings", "Caden,\n\nBody.",
        created=CREATED, path=log,
    )
    drafts = load_drafts(log)
    assert len(drafts) == 1
    assert drafts[0]["id"] == draft_id
    assert drafts[0]["status"] == "pending"
    assert drafts[0]["recipients"] == ["caden@example.com"]
    assert drafts[0]["body"] == "Caden,\n\nBody."


def test_load_missing_file_is_empty_not_an_error(tmp_path):
    assert load_drafts(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path):
    log = tmp_path / "drafts.jsonl"
    good = json.dumps({"id": "d-1", "created": CREATED, "register": "client",
                       "recipients": [], "subject": "s", "body": "b",
                       "status": "pending"})
    log.write_text(good + "\nnot json at all\n" + good + "\n", encoding="utf-8")
    assert len(load_drafts(log)) == 2


def test_set_status_rewrites_one_entry(tmp_path):
    log = tmp_path / "drafts.jsonl"
    first = record_draft("client", [], "one", "b", created=CREATED, path=log)
    second = record_draft("client", [], "two", "b", created=CREATED, path=log)
    set_status(second, "matched", path=log)
    by_id = {d["id"]: d for d in load_drafts(log)}
    assert by_id[second]["status"] == "matched"
    assert by_id[first]["status"] == "pending"


def test_expire_old_drops_entries_past_retention():
    drafts = [
        {"id": "old", "created": "2026-07-01T00:00:00-04:00", "status": "pending"},
        {"id": "new", "created": "2026-08-17T00:00:00-04:00", "status": "pending"},
    ]
    kept = expire_old(drafts, "2026-08-18T00:00:00-04:00")
    assert [d["id"] for d in kept] == ["new"]


def test_expire_old_ignores_unparseable_dates():
    drafts = [{"id": "weird", "created": "", "status": "pending"}]
    assert expire_old(drafts, "2026-08-18T00:00:00-04:00") == []


def test_pending_filters_by_status():
    drafts = [{"id": "a", "status": "pending"}, {"id": "b", "status": "matched"}]
    assert [d["id"] for d in pending(drafts)] == ["a"]
