# tests/test_ingest.py
from __future__ import annotations

import json
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from ingest import (  # noqa: E402
    dedupe,
    load_eml_dir,
    normalize,
    strip_quoted,
    strip_signature,
)


def test_strips_gmail_quote():
    body = (
        "Pushed the fix.\n\n"
        "On Tue, Apr 15, 2025 at 4:02 PM Marcus Webb <m@x.com> wrote:\n"
        "> Did the config get updated?\n"
    )
    assert strip_quoted(body).strip() == "Pushed the fix."


def test_strips_outlook_quote():
    body = "Sounds good.\n\n-----Original Message-----\nFrom: Bob\nOld text\n"
    assert strip_quoted(body).strip() == "Sounds good."


def test_strips_bare_angle_quotes():
    body = "No thanks.\n\n> please reconsider\n> it is important\n"
    assert strip_quoted(body).strip() == "No thanks."


def test_strips_outlook_divider():
    body = "Done.\n\n________________________________\nFrom: Someone\n"
    assert strip_quoted(body).strip() == "Done."


def test_keeps_body_without_quotes():
    body = "Just a plain note with > a greater than sign inline."
    assert strip_quoted(body).strip() == body


def test_strips_dash_dash_signature():
    body = "Thanks for the update.\n\n-- \nDana Reyes\nNorthwind Labs\n+1 555 018 2299"
    assert strip_signature(body).strip() == "Thanks for the update."


def test_strips_mobile_footer():
    body = "On my way.\n\nSent from my iPhone"
    assert strip_signature(body).strip() == "On my way."


def test_strips_trailing_contact_block():
    body = "Let's lock the date.\n\nDana Reyes\nNorthwind Labs\nnorthwind-labs.com"
    assert strip_signature(body).strip() == "Let's lock the date."


def test_keeps_signoff_line():
    """A signoff is style, not a signature block — it must survive."""
    body = "Pushed the fix.\n\n— Dana"
    assert "Dana" in strip_signature(body)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "synthetic"
USER = "dana@northwind-labs.com"


def load_eml(name: str):
    return BytesParser(policy=policy.default).parsebytes((FIXTURES / name).read_bytes())


def test_normalize_produces_schema():
    msg = load_eml("client_001.eml")
    rec = normalize(msg, USER)
    assert set(rec) == {
        "id", "date", "to_domains", "recipient_count",
        "subject", "body", "is_reply", "word_count",
    }
    assert rec["to_domains"] == ["harborline.com"]
    assert rec["is_reply"] is False
    assert rec["word_count"] > 0


def test_normalize_detects_reply():
    assert normalize(load_eml("internal_004.eml"), USER)["is_reply"] is True


def test_normalize_rejects_mail_from_others():
    msg = load_eml("client_001.eml")
    assert normalize(msg, "someone-else@example.com") is None


def test_dedupe_removes_near_duplicates():
    a = {"id": "a", "body": "We help teams ship faster with fewer meetings and less overhead."}
    b = {"id": "b", "body": "We help teams ship faster with fewer meetings and less overhead now."}
    c = {"id": "c", "body": "Completely unrelated message about lunch plans on Friday."}
    kept = dedupe([a, b, c])
    assert [m["id"] for m in kept] == ["a", "c"]


def test_cli_end_to_end(tmp_path):
    out = tmp_path / "corpus.json"
    root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(FIXTURES), "--user", USER, "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))

    # Ground truth: how many fixtures normalize successfully (2 auto-replies
    # are dropped by normalize()), independent of the CLI subprocess.
    normalized_count = len(
        [r for r in (normalize(m, USER) for m in load_eml_dir(FIXTURES)) if r]
    )

    assert data["stats"]["kept"] >= 12
    assert data["stats"]["terse"] == 4
    # dedupe() must actually fire: outreach_001/outreach_002 are a genuine
    # templated pair (Jaccard > 0.85), so exactly one of them is collapsed.
    assert data["stats"]["deduped"] == normalized_count - 1
    assert data["stats"]["kept"] + data["stats"]["terse"] == data["stats"]["deduped"]
    for msg in data["messages"]:
        assert "wrote:" not in msg["body"]
        assert "Sent from my" not in msg["body"]
