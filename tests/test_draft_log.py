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


# --- Fix round 1: both routes must feed one candidate set, not a tie-break ---


def test_exact_subject_bucket_does_not_hide_a_fuzzy_ambiguity():
    """An exact-subject hit with a dissimilar body must not shadow a
    different-subject candidate whose body is a near-identical match."""
    sent = [
        _sent("Listings - what changes", "Totally unrelated text about lunch plans."),
        _sent("Something else entirely", DRAFT["body"]),
    ]
    status, hits = find_match(DRAFT, sent)
    assert status == "ambiguous"
    assert len(hits) == 2


def test_three_exact_subject_candidates_are_ambiguous():
    sent = [
        _sent("Listings - what changes", DRAFT["body"]),
        _sent("Listings - what changes", DRAFT["body"] + " one"),
        _sent("Listings - what changes", DRAFT["body"] + " two"),
    ]
    status, hits = find_match(DRAFT, sent)
    assert status == "ambiguous"
    assert len(hits) == 3


def test_two_fuzzy_candidates_are_ambiguous_even_when_one_is_more_similar():
    """No tie-break on similarity score: both clear MATCH_THRESHOLD, so both
    are candidates, even though they are not equally similar."""
    close = DRAFT["body"] + " One more line here."
    farther = DRAFT["body"] + " One more line here with several extra words tacked on at the end."
    assert similarity(DRAFT["body"], close) != similarity(DRAFT["body"], farther)
    assert similarity(DRAFT["body"], close) >= MATCH_THRESHOLD
    assert similarity(DRAFT["body"], farther) >= MATCH_THRESHOLD
    sent = [
        _sent("Different subject one", close),
        _sent("Different subject two", farther),
    ]
    status, hits = find_match(DRAFT, sent)
    assert status == "ambiguous"
    assert len(hits) == 2


def test_draft_with_unparseable_created_is_not_matched():
    draft = {**DRAFT, "created": "not-a-date"}
    sent = [_sent("Listings - what changes", DRAFT["body"])]
    assert find_match(draft, sent)[0] == "none"


def test_message_with_unparseable_date_is_excluded():
    sent = [_sent("Listings - what changes", DRAFT["body"], date="not-a-date")]
    assert find_match(DRAFT, sent)[0] == "none"


def test_message_sent_at_exactly_the_draft_created_timestamp_is_a_candidate():
    sent = [_sent("Listings - what changes", DRAFT["body"], date=DRAFT["created"])]
    status, hits = find_match(DRAFT, sent)
    assert status == "matched"


def test_none_and_empty_recipients_do_not_crash():
    draft = {**DRAFT, "recipients": [None, "", "caden@example.com"]}
    sent = [_sent("Listings - what changes", DRAFT["body"],
                  recipients=(None, "", "caden@example.com"))]
    status, hits = find_match(draft, sent)
    assert status == "matched"


def test_subject_matching_is_case_and_whitespace_insensitive():
    """The no-recipient path is the one the design calls safe, so it must not
    miss a match that differs only in case or surrounding whitespace."""
    draft = {**DRAFT, "recipients": []}
    sent = [_sent("  LISTINGS - WHAT CHANGES  ", DRAFT["body"], recipients=())]
    status, hits = find_match(draft, sent)
    assert status == "matched"


def test_message_qualifying_both_ways_counts_once():
    """A message with an exact subject match that is also highly similar in
    body must appear once in the candidate set, not twice."""
    sent = [_sent("Listings - what changes", DRAFT["body"])]
    status, hits = find_match(DRAFT, sent)
    assert status == "matched"
    assert len(hits) == 1


import subprocess


def test_record_cli_writes_an_entry(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    body = tmp_path / "body.txt"
    body.write_text("Caden,\n\nBody with \"quotes\" and\nnewlines.", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--record",
         "--register", "client", "--recipients", "caden@example.com",
         "--subject", "Listings", "--body-file", str(body),
         "--created", CREATED, "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    drafts = load_drafts(log)
    assert len(drafts) == 1
    assert drafts[0]["body"].endswith("newlines.")
    assert result.stdout.strip() == drafts[0]["id"]


def test_list_pending_cli_applies_retention(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    record_draft("client", [], "old", "b", created="2026-07-01T00:00:00-04:00",
                 path=log)
    record_draft("client", [], "new", "b", created="2026-08-17T00:00:00-04:00",
                 path=log)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--list-pending",
         "--now", "2026-08-18T00:00:00-04:00", "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "new" in result.stdout
    assert "old" not in result.stdout
    assert len(load_drafts(log)) == 1


def test_match_cli_reports_status_and_candidates(tmp_path):
    root = Path(__file__).parent.parent
    draft_file = tmp_path / "draft.json"
    cand_file = tmp_path / "candidates.json"
    draft_file.write_text(json.dumps(DRAFT), encoding="utf-8")
    cand_file.write_text(
        json.dumps([_sent("Listings - what changes", DRAFT["body"])]),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--match",
         "--draft-file", str(draft_file), "--candidates-file", str(cand_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "matched"
    assert len(payload["candidates"]) == 1


def test_record_cli_requires_created(tmp_path):
    """Without --created, find_match can never parse the draft's creation
    time (Task 2's fix), so the draft would sit in the log permanently
    unmatchable and silently teach nothing. Refuse to write it at all."""
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    body = tmp_path / "body.txt"
    body.write_text("Body.", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--record",
         "--register", "client", "--recipients", "caden@example.com",
         "--subject", "Listings", "--body-file", str(body),
         "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not log.exists()


def test_set_status_cli_updates_status(tmp_path):
    """Finding 2 (final whole-branch review): set_status() existed but no CLI
    flag exposed it, so nothing outside the tests could ever call it and a
    reviewed draft stayed 'pending' forever. --set-status must actually
    rewrite the record on disk."""
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    draft_id = record_draft("client", [], "one", "b", created=CREATED, path=log)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--set-status",
         "--draft-id", draft_id, "--status", "matched", "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    by_id = {d["id"]: d for d in load_drafts(log)}
    assert by_id[draft_id]["status"] == "matched"


def test_set_status_cli_rejects_an_unknown_status(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    draft_id = record_draft("client", [], "one", "b", created=CREATED, path=log)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--set-status",
         "--draft-id", draft_id, "--status", "expired", "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--status must be one of" in result.stderr
    by_id = {d["id"]: d for d in load_drafts(log)}
    assert by_id[draft_id]["status"] == "pending"


def test_set_status_cli_requires_draft_id(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--set-status",
         "--status", "matched", "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--set-status requires --draft-id" in result.stderr


def test_get_cli_prints_the_full_record_including_body(tmp_path):
    """Finding 3: --list-pending is compact by design (id/created/register/
    recipients/subject, no body), and that was the only documented way to
    fetch a draft. Without a body, find_match()'s fuzzy fallback silently
    never fires (similarity("", body) == 0.0) and diff_draft.py dies with
    KeyError: 'body'. --get must return the complete record."""
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    draft_id = record_draft(
        "client", ["caden@example.com"], "Listings", "Caden,\n\nBody text here.",
        created=CREATED, path=log,
    )
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--get",
         "--draft-id", draft_id, "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["id"] == draft_id
    assert record["body"] == "Caden,\n\nBody text here."
    assert record["subject"] == "Listings"


def test_get_cli_errors_cleanly_for_an_unknown_draft_id(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    record_draft("client", [], "one", "b", created=CREATED, path=log)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--get",
         "--draft-id", "d-nonexistent", "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "no draft with id" in result.stderr


def test_statuses_does_not_include_expired():
    """Finding 6: expire_old() deletes past-retention rows outright rather
    than marking them, so 'expired' can never actually occur as a status.
    The vocabulary must match reality."""
    from draft_log import STATUSES
    assert "expired" not in STATUSES
    assert set(STATUSES) == {"pending", "matched", "ambiguous"}


def test_record_cli_requires_body_file(tmp_path):
    """Without --body-file, the draft is recorded with an empty body, which
    carries no content to diff against the sent version later. Refuse it."""
    root = Path(__file__).parent.parent
    log = tmp_path / "drafts.jsonl"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "draft_log.py"), "--record",
         "--register", "client", "--recipients", "caden@example.com",
         "--subject", "Listings", "--created", CREATED,
         "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not log.exists()


# --- Redirect-to-self (found by using the loop on real mail) ---

SELF = "me@example.com"


def test_draft_redirected_to_self_matches_on_exact_subject():
    """Sending a draft to yourself instead of its intended recipient is the
    natural way to test, and it cost a real edit signal when the matcher
    declined. Self-addressed sent mail is definitionally the user's own
    composition, so matching it cannot teach a stranger's voice — the reason
    the recipient guard exists does not apply."""
    sent = [_sent("Listings - what changes", DRAFT["body"], recipients=(SELF,))]
    status, hits = find_match(DRAFT, sent, user_email=SELF)
    assert status == "matched"
    assert hits[0]["recipients"] == [SELF]


def test_redirect_to_self_still_requires_an_exact_subject():
    """With the recipient signal gone, the fuzzy body route has nothing left
    to disambiguate with, exactly as in the no-recipient case."""
    sent = [_sent("Listings update", DRAFT["body"], recipients=(SELF,))]
    assert find_match(DRAFT, sent, user_email=SELF)[0] == "none"


def test_self_carve_out_needs_the_user_to_be_the_only_recipient():
    """A message to the user AND someone else is ordinary correspondence and
    must go through the normal recipient check."""
    sent = [_sent("Listings - what changes", DRAFT["body"],
                  recipients=(SELF, "stranger@example.com"))]
    assert find_match(DRAFT, sent, user_email=SELF)[0] == "none"


def test_self_carve_out_is_inert_without_a_user_email():
    """Behaviour is unchanged for every existing caller that passes no user."""
    sent = [_sent("Listings - what changes", DRAFT["body"], recipients=(SELF,))]
    assert find_match(DRAFT, sent)[0] == "none"


def test_self_carve_out_does_not_bypass_the_time_window():
    sent = [_sent("Listings - what changes", DRAFT["body"], recipients=(SELF,),
                  date="2026-08-17T10:00:00-04:00")]
    assert find_match(DRAFT, sent, user_email=SELF)[0] == "none"


def test_self_redirect_and_a_normal_hit_are_ambiguous_not_a_pick():
    sent = [
        _sent("Listings - what changes", DRAFT["body"]),
        _sent("Listings - what changes", DRAFT["body"], recipients=(SELF,)),
    ]
    assert find_match(DRAFT, sent, user_email=SELF)[0] == "ambiguous"


def test_normal_recipient_matching_is_unaffected_by_the_carve_out():
    sent = [_sent("Listings - what changes", DRAFT["body"])]
    assert find_match(DRAFT, sent, user_email=SELF)[0] == "matched"
