# scripts/ingest.py
from __future__ import annotations

import argparse
import html
import json
import mailbox
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

QUOTE_MARKERS = [
    re.compile(r"^On .{0,200}\bwrote:\s*$", re.MULTILINE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
    re.compile(r"^From:\s.+\nSent:\s.+$", re.MULTILINE),
    re.compile(r"^\s*>", re.MULTILINE),
]


def strip_quoted(body: str) -> str:
    """Truncate at the earliest quoted-reply marker."""
    cut = len(body)
    for pattern in QUOTE_MARKERS:
        match = pattern.search(body)
        if match:
            cut = min(cut, match.start())
    return body[:cut].rstrip()


SIG_DELIMITER = re.compile(r"^--\s?$", re.MULTILINE)
MOBILE_FOOTER = re.compile(
    r"^\s*(Sent from my \w+|Get Outlook for \w+|Sent via \w+).*$",
    re.MULTILINE | re.IGNORECASE,
)
CONTACT_LINE = re.compile(
    r"(\+?\d[\d\s().-]{7,}\d"          # phone
    r"|\b[\w.+-]+@[\w-]+\.\w+\b"       # email
    r"|\b[\w-]+\.(com|net|org|io|co)\b"  # bare domain
    r"|\|)",                            # pipe-separated title bars
    re.IGNORECASE,
)


def strip_signature(body: str) -> str:
    """Remove signature blocks while preserving a bare signoff line."""
    match = SIG_DELIMITER.search(body)
    if match:
        body = body[: match.start()]

    match = MOBILE_FOOTER.search(body)
    if match:
        body = body[: match.start()]

    # Trailing contact block: walk up from the end while lines look like contact
    # details. Stop at the first line that reads like prose or a signoff.
    #
    # A bare name/org line (e.g. "Northwind Labs") carries no phone, email, or
    # domain of its own, so CONTACT_LINE alone won't catch it. Once we've
    # already popped a genuine contact line, also pop short label-like lines
    # sitting above it (no leading dash, no sentence punctuation, <=6 words) —
    # that's the rest of the signature block. A signoff such as "— Dana" is
    # never preceded by a popped contact line (it's the last line, nothing
    # below it), so this never reaches it.
    lines = body.rstrip().split("\n")
    popped_contact = False
    while len(lines) > 1 and lines[-1].strip():
        last = lines[-1].strip()
        is_contact = bool(CONTACT_LINE.search(last)) and len(last.split()) <= 8
        if is_contact:
            popped_contact = True
            lines.pop()
            continue
        if popped_contact and _looks_like_label(last):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


def _looks_like_label(line: str) -> bool:
    """True for a short name/title/org line with no sentence punctuation or
    leading dash — the shape of a signature-block line, not a signoff."""
    if not line or line[0] in "-–—*":
        return False
    words = line.split()
    if not words or len(words) > 6:
        return False
    return not line.rstrip().endswith((".", "!", "?"))


AUTO_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond")
TAG_RE = re.compile(r"<[^>]+>")

# Quoted-reply containers must be dropped *before* TAG_RE strips the markup,
# otherwise the correspondent's quoted text has no HTML tags left to signal
# "this is a quote" and survives as if it were the user's own prose (the tag
# strip leaves no literal ">" for strip_quoted's markers to find).
#
# <blockquote> is matched greedily (`.*` not `.*?`) on purpose: real reply
# chains nest <blockquote> inside <blockquote> (replying to a reply), and a
# lazy match would stop at the *first* closing tag — the innermost one —
# leaking the outer, older quoted text back into the body. Greedy matching to
# the *last* </blockquote> in the message correctly swallows the whole nested
# chain. The trade-off is two independent, non-nested blockquotes with real
# authored text between them would also get collapsed together; for a corpus
# whose purpose is "never let a correspondent's words pass as the user's
# voice," over-stripping a rare structure is the safer failure than under-
# stripping the common one.
BLOCKQUOTE_RE = re.compile(r"<blockquote\b[^>]*>.*</blockquote>", re.IGNORECASE | re.DOTALL)
# Some clients (and forwarded mail) mark the quote container with
# class="gmail_quote" on a tag other than <blockquote> (typically a <div>).
# Matched non-greedily against its own tag name via backreference, since
# these wrappers are not known to nest the way reply-chain blockquotes do.
GMAIL_QUOTE_RE = re.compile(
    r"<(\w+)\b[^>]*\bclass=[\"'][^\"']*gmail_quote[^\"']*[\"'][^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def is_auto_reply(msg: EmailMessage) -> bool:
    for header in AUTO_HEADERS:
        value = msg.get(header)
        if value and value.lower() not in ("no",):
            return True
    subject = (msg.get("Subject") or "").lower()
    return subject.startswith(("out of office", "automatic reply"))


def extract_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        return part.get_content()
    part = msg.get_body(preferencelist=("html",))
    if part is not None:
        content = part.get_content()
        content = BLOCKQUOTE_RE.sub(" ", content)
        content = GMAIL_QUOTE_RE.sub(" ", content)
        content = TAG_RE.sub(" ", content)
        return html.unescape(content)
    return ""


def _domains(msg: EmailMessage) -> list[str]:
    pairs = getaddresses(
        [msg.get("To", ""), msg.get("Cc", "")]
    )
    seen = []
    for _, addr in pairs:
        if "@" in addr:
            domain = addr.split("@", 1)[1].lower()
            if domain not in seen:
                seen.append(domain)
    return seen


def normalize(msg: EmailMessage, user_email: str) -> dict | None:
    sender = (msg.get("From") or "").lower()
    if user_email.lower() not in sender:
        return None
    if is_auto_reply(msg):
        return None
    if (msg.get_content_type() or "").startswith("text/calendar"):
        return None

    body = strip_signature(strip_quoted(extract_body(msg))).strip()
    if not body:
        return None

    try:
        date = parsedate_to_datetime(msg.get("Date", "")).isoformat()
    except (TypeError, ValueError):
        date = ""

    subject = msg.get("Subject", "") or ""
    recipients = getaddresses([msg.get("To", ""), msg.get("Cc", "")])
    return {
        "id": msg.get("Message-ID", "") or subject[:40],
        "date": date,
        "to_domains": _domains(msg),
        "recipient_count": len(recipients),
        "subject": subject,
        "body": body,
        "is_reply": subject.lower().startswith("re:"),
        "word_count": len(body.split()),
    }


def _shingles(text: str, size: int = 5) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) < size:
        return {" ".join(words)}
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


# 0.70, not 0.85: measured template pairs (same boilerplate, only name/company
# swapped) score 0.77 at 5-word shingles; 0.85 never fires on them, which
# defeats the reason dedupe exists (collapsing a template into one occurrence
# so it can't be learned as "the voice"). The nearest genuinely-distinct pair
# in this corpus scores 0.051, so 0.70 leaves a wide safe basin between real
# duplicates and real variety — do not retune this without re-measuring both
# ends of that basin.
def dedupe(messages: list[dict], threshold: float = 0.70) -> list[dict]:
    kept: list[tuple[dict, set[str]]] = []
    for msg in messages:
        shingles = _shingles(msg["body"])
        duplicate = False
        for _, existing in kept:
            union = shingles | existing
            if union and len(shingles & existing) / len(union) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append((msg, shingles))
    return [msg for msg, _ in kept]


# 15 is a domain judgment about what counts as a terse acknowledgement, not a
# value fit to any particular fixture set. Do not retune it to match a
# specific corpus's stats — genuine 12-14 word acks in real mail belong here.
TERSE_WORD_LIMIT = 15


def load_eml_dir(path: Path) -> list[EmailMessage]:
    parser = BytesParser(policy=policy.default)
    return [parser.parsebytes(p.read_bytes()) for p in sorted(path.glob("*.eml"))]


def load_mbox(path: Path) -> list[EmailMessage]:
    box = mailbox.mbox(str(path), factory=None)
    out = []
    for key in box.iterkeys():
        try:
            raw = box.get_bytes(key)
        except Exception:
            continue
        try:
            out.append(BytesParser(policy=policy.default).parsebytes(raw))
        except Exception:
            continue
    return out


def load_json(path: Path) -> list[EmailMessage]:
    """Load a Gmail-connector dump: [{from, to, cc, subject, date, body}, ...]."""
    records = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for rec in records:
        msg = EmailMessage()
        msg["From"] = rec.get("from", "")
        msg["To"] = rec.get("to", "")
        if rec.get("cc"):
            msg["Cc"] = rec["cc"]
        msg["Subject"] = rec.get("subject", "")
        msg["Date"] = rec.get("date", "")
        msg["Message-ID"] = rec.get("id", "")
        msg.set_content(rec.get("body", ""))
        out.append(msg)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize sent mail into corpus.json")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--eml-dir")
    src.add_argument("--mbox")
    src.add_argument("--json")
    ap.add_argument("--user", required=True, help="The user's own email address")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.eml_dir:
        raw = load_eml_dir(Path(args.eml_dir))
    elif args.mbox:
        raw = load_mbox(Path(args.mbox))
    else:
        raw = load_json(Path(args.json))

    records = [r for r in (normalize(m, args.user) for m in raw) if r]
    records = dedupe(records)

    main_corpus = [r for r in records if r["word_count"] >= TERSE_WORD_LIMIT]
    terse = [r for r in records if r["word_count"] < TERSE_WORD_LIMIT]

    payload = {
        "user": args.user,
        "messages": main_corpus,
        "terse_ack": terse,
        "stats": {
            "raw": len(raw),
            "deduped": len(records),
            "kept": len(main_corpus),
            "terse": len(terse),
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"{len(raw)} parsed -> {len(main_corpus)} usable, "
        f"{len(terse)} terse acks -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
