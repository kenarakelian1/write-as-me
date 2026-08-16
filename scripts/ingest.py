# scripts/ingest.py
from __future__ import annotations

import argparse
import json
import mailbox
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
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

# Void elements never get a matching close tag (HTMLParser calls
# handle_starttag for them but handle_endtag never follows), so they must
# never be pushed onto the container-tracking stack below — if they were,
# the stack would drift out of sync with the real tag nesting on the very
# first <br> inside a paragraph.
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _QuoteStrippingParser(HTMLParser):
    """Extract visible text from an HTML email body, dropping <blockquote>
    elements and any element carrying class="gmail_quote" together with
    their full contents, at any nesting depth.

    A regex cannot match a balanced, arbitrarily nested container correctly:
    a non-greedy pattern stops at the *first* inner closing tag — which
    leaks a quote container's own sibling content (Gmail renders each
    quoted paragraph as its own <div> inside one class="gmail_quote"
    wrapper, so a non-greedy match closes after the first paragraph and
    leaks every paragraph after it). A greedy pattern runs to the *last*
    closing tag in the whole document — which swallows real user text
    sandwiched between two independent quote blocks (a reply in the middle
    of a forwarded thread). Walking the actual tag stream sidesteps both
    failures: text is only ever emitted while no quote-container tag is
    currently open, regardless of how many non-quote tags are nested inside
    or around it.

    An unclosed <blockquote> (malformed markup) is never popped off the
    stack, so everything after it is treated as still inside it and
    dropped through end of input — "fail toward stripping more," not
    toward leaking a truncated quote.

    Entity unescaping (&amp;, &#8212;, &nbsp;, ...) is handled by
    HTMLParser itself via convert_charrefs=True — decoded text arrives
    pre-unescaped in handle_data, so no separate html.unescape() step is
    needed or correct to add on top of this.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        # One (tag_name, is_quote_container) entry per currently-open,
        # non-void tag — a stack, so nested/sibling tags of the same name
        # resolve against the correct opener.
        self._stack: list[tuple[str, bool]] = []

    @staticmethod
    def _is_quote_container(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag == "blockquote":
            return True
        for name, value in attrs:
            if name == "class" and value and "gmail_quote" in value.split():
                return True
        return False

    def _skipping(self) -> bool:
        return any(is_quote for _, is_quote in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # A tag boundary always breaks word-fusion between the text before
        # and after it, whether or not its content is being skipped — e.g.
        # "<div>A</div><div>B</div>" must not read back as "AB".
        self._chunks.append(" ")
        if tag in VOID_ELEMENTS:
            return
        self._stack.append((tag, self._is_quote_container(tag, attrs)))

    def handle_endtag(self, tag: str) -> None:
        self._chunks.append(" ")
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return
        # Unmatched close tag (malformed markup) — nothing to pop; ignore.

    def handle_data(self, data: str) -> None:
        if not self._skipping():
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def strip_quote_containers(raw_html: str) -> str:
    parser = _QuoteStrippingParser()
    parser.feed(raw_html)
    parser.close()
    return parser.get_text()


def is_auto_reply(msg: EmailMessage) -> bool:
    for header in AUTO_HEADERS:
        value = msg.get(header)
        if value and value.lower() not in ("no",):
            return True
    subject = (msg.get("Subject") or "").lower()
    return subject.startswith(("out of office", "automatic reply"))


# Markers that identify a body generated by a tool rather than typed by the
# user. Calendar invites go out from the user's own account and look like sent
# mail, but nobody wrote them.
MACHINE_MARKERS = (
    "google meet joining info",
    "join with google meet",
    "video call link:",
    "zoom.us/j/",
    "microsoft teams meeting",
    "join the meeting now",
    "when\nwhere\nwho",
    "add to calendar",
    "rsvp to this invitation",
)
URL_TOKEN = re.compile(r"https?://\S+|\bwww\.\S+")
LINK_ONLY_WORD_FLOOR = 4


def is_self_addressed(msg: EmailMessage, user_email: str) -> bool:
    """True when the user is the only recipient.

    Automated reports, deadline alerts and saved links that a user mails to
    themselves are not correspondence, and on a real mailbox they can outnumber
    genuine sent mail. Left in, they teach the profile to imitate the user's
    reporting scripts. A message addressed to the user *and* someone else is
    ordinary mail and is kept.
    """
    recipients = {
        addr.lower()
        for _, addr in getaddresses([msg.get("To", ""), msg.get("Cc", "")])
        if addr
    }
    if not recipients:
        return False
    return recipients == {user_email.lower()}


def is_machine_generated(msg: EmailMessage) -> bool:
    """True when the body was produced by a tool rather than written."""
    body = extract_body(msg)
    lowered = body.lower()
    if any(marker in lowered for marker in MACHINE_MARKERS):
        return True

    # A body that is nothing but a link — a shared article, a notebook, a
    # dashboard URL. Stripping the URLs leaves too little prose to model.
    # Checked against the raw body so a signature cannot rescue it.
    without_urls = URL_TOKEN.sub(" ", body)
    return bool(URL_TOKEN.search(body)) and len(without_urls.split()) < LINK_ONLY_WORD_FLOOR


def extract_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        return part.get_content()
    part = msg.get_body(preferencelist=("html",))
    if part is not None:
        return strip_quote_containers(part.get_content())
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

    # Filter before normalizing so each drop reason can be counted and reported.
    dropped_self = dropped_machine = 0
    candidates = []
    for message in raw:
        if is_self_addressed(message, args.user):
            dropped_self += 1
            continue
        if is_machine_generated(message):
            dropped_machine += 1
            continue
        candidates.append(message)

    records = [r for r in (normalize(m, args.user) for m in candidates) if r]
    records = dedupe(records)

    main_corpus = [r for r in records if r["word_count"] >= TERSE_WORD_LIMIT]
    terse = [r for r in records if r["word_count"] < TERSE_WORD_LIMIT]

    payload = {
        "user": args.user,
        "messages": main_corpus,
        "terse_ack": terse,
        "stats": {
            "raw": len(raw),
            "self_addressed": dropped_self,
            "machine_generated": dropped_machine,
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
    # Never filter silently: a corpus that shrank by half should say why.
    if dropped_self or dropped_machine:
        print(
            f"  dropped {dropped_self} self-addressed "
            f"(automated reports, notes to self) and "
            f"{dropped_machine} machine-generated (calendar invites, link-only)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
