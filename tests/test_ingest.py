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
    strip_quote_containers,
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
    # templated pair (Jaccard ~0.857 at 5-word shingles, well above the 0.70
    # threshold), so exactly one of them is collapsed. The nearest genuinely
    # distinct pair in this corpus scores ~0.051, far below threshold.
    assert data["stats"]["deduped"] == normalized_count - 1
    assert data["stats"]["kept"] + data["stats"]["terse"] == data["stats"]["deduped"]
    for msg in data["messages"]:
        assert "wrote:" not in msg["body"]
        assert "Sent from my" not in msg["body"]


# --- Finding 1: first run must not crash with FileNotFoundError -----------


def test_cli_creates_missing_output_directory(tmp_path):
    """A user with no prior ~/.claude/wam/cache/ must not hit an uncaught
    FileNotFoundError from Path.write_text on the very first run."""
    out = tmp_path / "does" / "not" / "exist" / "corpus.json"
    root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(FIXTURES), "--user", USER, "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()


# --- Finding 5: dedupe threshold lowered to 0.70, 5-word shingles kept ----


def test_dedupe_default_threshold_catches_070_pair_085_would_miss():
    """A template pair differing in exactly one of ten words scores 5/7 ~=
    0.714 Jaccard at 5-word shingles: below the old 0.85 default (the two
    messages would have survived as separate entries) and above the new 0.70
    default (they must collapse to one). This is the exact class of genuine
    templated outreach dedupe exists to catch."""
    a = {"id": "a", "body": "alpha beta gamma delta epsilon zeta eta theta iota kappa"}
    b = {"id": "b", "body": "alpha beta gamma delta epsilon zeta eta theta iota lambda"}

    assert [m["id"] for m in dedupe([a, b])] == ["a"]
    # Confirm the old default really would have missed this pair, so the
    # test is actually exercising the threshold change and not something else.
    assert len(dedupe([a, b], threshold=0.85)) == 2


def test_dedupe_still_spares_genuinely_distinct_messages():
    """The 0.70 default must not start catching real variety. The highest-
    scoring genuinely-distinct pair measured in the synthetic corpus is
    ~0.051 Jaccard, far below threshold."""
    a = {"id": "a", "body": "Completely unrelated message about lunch plans on Friday."}
    b = {"id": "b", "body": "Quarterly budget review moved to next Thursday afternoon."}
    assert len(dedupe([a, b])) == 2


# --- Finding 3: HTML blockquote / gmail_quote replies must be stripped ----


def _html_msg(html_body: str, subject: str = "Re: Thursday", msg_id: str = "html-1") -> bytes:
    return (
        b"From: dana@northwind-labs.com\r\n"
        b"To: priya@harborline.com\r\n"
        b"Subject: " + subject.encode() + b"\r\n"
        b"Date: Mon, 21 Apr 2025 09:00:11 -0400\r\n"
        b"Message-ID: <" + msg_id.encode() + b"@northwind-labs.com>\r\n"
        b'Content-Type: text/html; charset="utf-8"\r\n'
        b"\r\n" + html_body.encode("utf-8")
    )


def test_html_blockquote_reply_is_stripped_and_entities_unescaped():
    raw = _html_msg(
        "<div>Sounds good &mdash; let's proceed with Thursday.</div>\n"
        '<blockquote class="gmail_quote">\n'
        "<div>On Mon, Apr 21, 2025 at 8:00 AM Priya Shah "
        "&lt;priya@harborline.com&gt; wrote:</div>\n"
        "<div>Can we push the call to Thursday? Let me know soon.</div>\n"
        "</blockquote>\n"
        "<div>Dana Reyes</div>\n"
        "<div>northwind-labs.com</div>\n"
    )
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    rec = normalize(msg, USER)
    assert rec is not None
    body = rec["body"]
    # The correspondent's quoted message and identity must not survive.
    assert "Priya" not in body
    assert "push the call" not in body
    # The entity must be unescaped, not left as literal markup.
    assert "&mdash;" not in body
    assert "—" in body  # em dash
    # The trailing signature block is removed by the existing pipeline.
    assert "Dana Reyes" not in body
    assert body == "Sounds good — let's proceed with Thursday."


def test_html_nested_blockquote_chain_is_fully_stripped():
    """A reply-to-a-reply nests <blockquote> inside <blockquote>. A lazy
    (non-greedy) match would stop at the innermost closing tag and leak the
    outer, older quoted text back into the body."""
    raw = _html_msg(
        "<div>Works for me.</div>\n"
        '<blockquote class="gmail_quote">\n'
        "<div>Marcus wrote: can you also loop in Priya on this?</div>\n"
        '<blockquote class="gmail_quote">\n'
        "<div>Priya wrote: original ask about the fulfillment numbers.</div>\n"
        "</blockquote>\n"
        "</blockquote>\n"
    )
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    rec = normalize(msg, USER)
    assert rec is not None
    body = rec["body"]
    assert "Marcus" not in body
    assert "Priya" not in body
    assert "fulfillment numbers" not in body
    assert body == "Works for me."


# --- Finding 3 follow-up (reviewer audit): regex could not handle balanced
# nested/sibling containers correctly. Replaced with a depth-aware
# html.parser scan. Each case below is one the reviewer specifically
# exercised against the regex version and found broken.


def test_gmail_quote_div_with_sibling_paragraphs_is_fully_stripped():
    """(a) Gmail's real markup: one class="gmail_quote" <div> containing
    several sibling <div> paragraphs, not one flat blob. A non-greedy regex
    backreference-matched to the container's own closing tag stops at the
    *first* inner </div> and leaks every paragraph after the first."""
    html_body = (
        "<div>New content here.</div>"
        '<div class="gmail_quote">'
        "<div>Quoted paragraph one from Priya.</div>"
        "<div>Quoted paragraph two from Priya, with more detail.</div>"
        "<div>Quoted paragraph three, the sign-off.</div>"
        "</div>"
    )
    text = strip_quote_containers(html_body)
    assert "Quoted paragraph one" not in text
    assert "Quoted paragraph two" not in text
    assert "Quoted paragraph three" not in text
    assert "New content here." in text


def test_user_text_sandwiched_between_two_blockquotes_survives():
    """(b) A reply in the middle of a forwarded thread: quote, then genuine
    user prose, then another quote. A greedy regex matching to the *last*
    closing tag in the document swallows the real prose along with both
    quotes; this must survive intact while both quotes disappear."""
    html_body = (
        '<blockquote class="gmail_quote">'
        "<div>Old quoted paragraph from last week.</div>"
        "</blockquote>"
        "<div>Actually, following up on my note above: let's do Thursday.</div>"
        '<blockquote class="gmail_quote">'
        "<div>Another quoted paragraph from Priya.</div>"
        "</blockquote>"
    )
    text = strip_quote_containers(html_body)
    assert "Old quoted paragraph" not in text
    assert "Another quoted paragraph" not in text
    assert "Actually, following up on my note above: let's do Thursday." in text


def test_gmail_quote_div_attribute_order_does_not_matter():
    """class= can appear anywhere among a tag's attributes; the container
    must be recognized regardless of position."""
    variants = [
        '<div class="gmail_quote" id="q1" style="margin:0">QUOTE</div>',
        '<div id="q1" style="margin:0" class="gmail_quote">QUOTE</div>',
        '<div style="margin:0" id="q1" class="gmail_quote">QUOTE</div>',
    ]
    for html_body in variants:
        text = strip_quote_containers("Kept text. " + html_body)
        assert "QUOTE" not in text, html_body
        assert "Kept text." in text, html_body


def test_unclosed_blockquote_strips_to_end_of_input_instead_of_leaking():
    """Malformed markup with no closing </blockquote> must fail toward
    stripping too much (treat it as running to end of input), never toward
    leaking the quoted text back into the corpus."""
    html_body = (
        "<div>Real reply text.</div>"
        '<blockquote class="gmail_quote"><div>Quoted text with no closing tag'
    )
    text = strip_quote_containers(html_body)
    assert "Real reply text." in text
    assert "Quoted text with no closing tag" not in text


def test_entities_are_unescaped_in_surviving_text():
    html_body = (
        "<div>Ben &amp; Co. said &quot;yes&quot;&nbsp;&#8212; also &mdash; great.</div>"
    )
    text = strip_quote_containers(html_body)
    assert "&amp;" not in text and "Ben & Co." in text
    assert "&quot;" not in text and '"yes"' in text
    assert "&nbsp;" not in text and "\xa0" in text
    assert "&#8212;" not in text and "—" in text
    assert "&mdash;" not in text
