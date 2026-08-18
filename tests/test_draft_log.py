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
    assert len(a) == len("d-20260818-") + 8


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


def test_load_skips_non_dict_json_values(tmp_path):
    log = tmp_path / "drafts.jsonl"
    good = json.dumps({"id": "d-1", "created": CREATED, "register": "client",
                       "recipients": [], "subject": "s", "body": "b",
                       "status": "pending"})
    # Write a mix of valid dict, JSON scalar, and another valid dict
    log.write_text(good + "\n42\n" + good + "\n", encoding="utf-8")
    assert len(load_drafts(log)) == 2


def test_load_with_utf8_bom(tmp_path):
    log = tmp_path / "drafts.jsonl"
    good = json.dumps({"id": "d-1", "created": CREATED, "register": "client",
                       "recipients": [], "subject": "s", "body": "b",
                       "status": "pending"})
    # Write with UTF-8 BOM prefix
    with log.open("w", encoding="utf-8-sig") as f:
        f.write(good + "\n")
    drafts = load_drafts(log)
    assert len(drafts) == 1
    assert drafts[0]["id"] == "d-1"


def test_set_status_preserves_corrupt_lines(tmp_path):
    log = tmp_path / "drafts.jsonl"
    good = json.dumps({"id": "d-1", "created": CREATED, "register": "client",
                       "recipients": [], "subject": "s", "body": "b",
                       "status": "pending"})
    garbage = "not json at all"
    # Write a good record, then garbage, then another good record
    log.write_text(good + "\n" + garbage + "\n", encoding="utf-8")
    set_status("d-1", "matched", path=log)
    content = log.read_text(encoding="utf-8")
    # Garbage line should still be there
    assert garbage in content
    # First record should be updated
    drafts = load_drafts(log)
    assert len(drafts) == 1
    assert drafts[0]["status"] == "matched"


from draft_log import (  # noqa: E402
    MATCH_THRESHOLD,
    REWRITE_THRESHOLD,
    find_match,
    similarity,
)

DRAFT = {
    "id": "d-1",
    "created": "2026-08-18T09:00:00-04:00",
    "recipients": ["caden@example.com"],
    "subject": "Listings - what changes",
    "body": "Caden,\n\nI am narrowing what I do on directory listings. "
            "Monthly I check each property and send you what is wrong.",
}


def _sent(subject, body, recipients=("caden@example.com",),
          date="2026-08-18T10:00:00-04:00"):
    return {"subject": subject, "body": body,
            "recipients": list(recipients), "date": date}


def test_similarity_is_one_for_identical_text():
    assert similarity("a b c d e f", "a b c d e f") == 1.0


def test_similarity_is_zero_when_either_side_is_empty():
    assert similarity("", "a b c d e f") == 0.0


def test_exact_subject_and_recipient_matches():
    sent = [_sent("Listings - what changes", DRAFT["body"])]
    status, hits = find_match(DRAFT, sent)
    assert status == "matched"
    assert hits[0]["subject"] == "Listings - what changes"


def test_message_sent_before_the_draft_is_not_a_candidate():
    sent = [_sent("Listings - what changes", DRAFT["body"],
                  date="2026-08-17T10:00:00-04:00")]
    assert find_match(DRAFT, sent)[0] == "none"


def test_message_to_a_different_recipient_is_not_a_candidate():
    sent = [_sent("Listings - what changes", DRAFT["body"],
                  recipients=("someone-else@example.com",))]
    assert find_match(DRAFT, sent)[0] == "none"


def test_edited_subject_falls_back_to_body_similarity():
    sent = [_sent("Listings update", DRAFT["body"] + " One more line here.")]
    status, hits = find_match(DRAFT, sent)
    assert status == "matched"
    assert hits[0]["subject"] == "Listings update"


def test_unrelated_body_with_edited_subject_is_not_a_match():
    sent = [_sent("Something else", "Totally unrelated text about lunch plans.")]
    assert find_match(DRAFT, sent)[0] == "none"


def test_two_candidates_are_ambiguous_not_a_guess():
    sent = [
        _sent("Listings - what changes", DRAFT["body"]),
        _sent("Listings - what changes", DRAFT["body"] + " extra"),
    ]
    status, hits = find_match(DRAFT, sent)
    assert status == "ambiguous"
    assert len(hits) == 2


def test_draft_with_no_recipient_requires_an_exact_subject():
    """Without a recipient the shingle fallback loses its disambiguation, so
    only an exact subject is safe."""
    draft = {**DRAFT, "recipients": []}
    assert find_match(draft, [_sent("Listings update", DRAFT["body"],
                                    recipients=())])[0] == "none"
    assert find_match(draft, [_sent("Listings - what changes", DRAFT["body"],
                                    recipients=())])[0] == "matched"


def test_thresholds_are_the_spec_values():
    assert MATCH_THRESHOLD == 0.5
    assert REWRITE_THRESHOLD == 0.25
