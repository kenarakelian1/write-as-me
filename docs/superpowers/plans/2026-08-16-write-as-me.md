# write-as-me Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that derives a personalized email writing-style guide from a user's sent mail and drafts new email in that voice.

**Architecture:** Deterministic Python (stdlib only) handles parsing, cleaning, metric computation, register clustering, and redaction, emitting a compact JSON fingerprint plus redacted exemplars. The model reads that small artifact — never the bulk corpus — and synthesizes a directive style guide written to `~/.claude/wam/`. Tasks 1–5 build and test the pipeline standalone; Tasks 6–8 wire it into the skill and plugin.

**Tech Stack:** Python 3.9+ (stdlib: `email`, `mailbox`, `json`, `re`, `statistics`, `argparse`), pytest for dev-time tests, Claude Code plugin manifests, Markdown skill definitions.

## Global Constraints

- **Runtime dependencies: none.** Python standard library only. pytest is dev-only, declared in `requirements-dev.txt`, never imported by `scripts/`.
- **Python floor: 3.9.** Every module starts with `from __future__ import annotations` so modern type syntax works on 3.9.
- **Explicit UTF-8 everywhere.** Every `open()`, `read_text()`, and `write_text()` passes `encoding="utf-8"`. Windows defaults to cp1252 and will corrupt real email without this.
- **No network calls** in any script under `scripts/`.
- **Generated profiles write to `~/.claude/wam/`**, never inside the repo.
- **Repo name / plugin name / skill name:** `write-as-me`. Storage directory and alias command: `wam`.
- **Every script is CLI-invokable** as `python scripts/<name>.py --help` and communicates via JSON files.
- Corpus minimum: **12** usable messages. Register minimum: **8** messages. Gmail window: **12 months**. Dedupe threshold: **0.85** Jaccard.
- Commit after every task. Never commit anything under `emails/`, `*.mbox`, `*.eml`.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `scripts/ingest.py` | Sources → cleaned, normalized `corpus.json` |
| `scripts/fingerprint.py` | `corpus.json` → `fingerprint.json` + `exemplars.json` |
| `scripts/redact.py` | PII scrub, importable and CLI |
| `scripts/eval_holdout.py` | Holdout harness comparing draft vs. original fingerprints |
| `scripts/build_baseline.py` | One-time generator for `fixtures/baseline_ngrams.json` |
| `skills/write-as-me/SKILL.md` | Both modes; the only file Claude reads at invocation |
| `commands/wam.md` | Alias delegating to the skill |
| `.claude-plugin/plugin.json`, `marketplace.json` | Plugin metadata |
| `fixtures/synthetic/` | Fake persona corpus, ~40 `.eml` files |
| `fixtures/baseline_ngrams.json` | Common-English frequency baseline |
| `tests/` | pytest suites, one per script |

---

## Task 1: Repo scaffolding, fixtures, and baseline

**Files:**
- Create: `.gitignore`, `requirements-dev.txt`, `pytest.ini`, `README.md`
- Create: `scripts/build_baseline.py`
- Create: `fixtures/baseline_ngrams.json`
- Create: `fixtures/synthetic/*.eml` (40 files)
- Create: `fixtures/synthetic/README.md`
- Test: `tests/test_fixtures.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `fixtures/synthetic/` (40 `.eml` files from persona "Dana Reyes" `<dana@northwind-labs.com>`), and `fixtures/baseline_ngrams.json` with shape `{"unigrams": {"the": 0.0512, ...}, "bigrams": {"of the": 0.0021, ...}}` where values are relative frequencies summing to ~1.0 per section.

- [ ] **Step 1: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.venv/

# Never commit real mail
emails/
*.mbox
*.eml
!fixtures/synthetic/*.eml
.wam/
corpus.json
raw.json
```

- [ ] **Step 2: Create `requirements-dev.txt` and `pytest.ini`**

```
# requirements-dev.txt
pytest>=7.0
```

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 3: Write the synthetic persona corpus**

Create 40 `.eml` files in `fixtures/synthetic/`. Persona: **Dana Reyes**, `dana@northwind-labs.com`, a consultant with a deliberately distinctive voice so metrics have signal to find.

Dana's designed traits (the tests assert these, so they must be real in the data):
- Short: most emails 40–80 words
- Opens `Hi <name>` to clients, no greeting on internal replies
- Signs off `— Dana` internally, `Best, Dana Reyes` to clients
- Heavy em dash, zero exclamation marks to clients
- Leads with the ask
- Pet phrase: "worth a look" appears in ~8 emails

Distribution: 14 client (`@*.com` external), 12 internal (`@northwind-labs.com`), 6 cold outreach, 5 personal (`@gmail.com`), 3 terse acks (under 15 words).

At least 6 must contain quoted reply blocks (mix of Gmail `On ... wrote:`, Outlook `-----Original Message-----`, and `>` prefixes), 8 must carry signatures, 2 must be auto-replies, and 2 must be near-duplicate templated outreach so dedupe has something to catch.

Example file, `fixtures/synthetic/client_001.eml`:

```
From: Dana Reyes <dana@northwind-labs.com>
To: Priya Raman <priya@harborline.com>
Subject: Timeline for the Q3 rollout
Date: Mon, 14 Apr 2025 09:12:04 -0400
Message-ID: <client-001@northwind-labs.com>
Content-Type: text/plain; charset="utf-8"

Hi Priya,

Can you confirm the Q3 date by Thursday? We need it locked before the vendor
contract goes out — otherwise we're rebuilding the schedule twice.

One thing worth a look: the staging environment is still on the old config.

Best,
Dana Reyes

--
Dana Reyes | Northwind Labs
+1 555 018 2299 | northwind-labs.com
```

Example with a quoted block, `fixtures/synthetic/internal_004.eml`:

```
From: Dana Reyes <dana@northwind-labs.com>
To: Marcus Webb <marcus@northwind-labs.com>
Subject: Re: staging config
Date: Tue, 15 Apr 2025 16:40:11 -0400
Message-ID: <internal-004@northwind-labs.com>
Content-Type: text/plain; charset="utf-8"

Pushed the fix — should be live in ten minutes.

— Dana

On Tue, Apr 15, 2025 at 4:02 PM Marcus Webb <marcus@northwind-labs.com> wrote:
> Did the staging config ever get updated? I'm still seeing the old
> values in the dashboard.
>
> Marcus
```

- [ ] **Step 4: Write `fixtures/synthetic/README.md`**

State that the corpus is entirely fictional, that no real person's mail is in the repo, and list the designed traits above so contributors know what the tests depend on.

- [ ] **Step 5: Write `scripts/build_baseline.py`**

The baseline must reflect **modern English**, not literary prose. Measuring email
against 19th-century novels would rank ordinary business vocabulary — "meeting",
"deadline", "invoice" — as highly distinctive, and every user's "pet phrases" would
come back as generic office words. The input is therefore a precomputed frequency
table, not raw text.

```python
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TOKEN = re.compile(r"^[a-z']+$")


def read_counts(path: Path, top_n: int, ngram_size: int) -> dict[str, float]:
    """Read a TSV frequency table: <ngram>\\t<count> per line, already sorted
    descending by count. Returns relative frequencies."""
    entries: list[tuple[str, int]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip("\\n").split("\\t")
            if len(parts) != 2:
                continue
            phrase, raw = parts[0].strip().lower(), parts[1].strip()
            if not raw.isdigit():
                continue
            words = phrase.split()
            if len(words) != ngram_size or not all(TOKEN.match(w) for w in words):
                continue
            entries.append((phrase, int(raw)))
            if len(entries) >= top_n:
                break

    total = sum(count for _, count in entries) or 1
    return {phrase: count / total for phrase, count in entries}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build an n-gram frequency baseline from TSV count tables."
    )
    ap.add_argument("--unigrams", required=True, help="TSV: word<TAB>count")
    ap.add_argument("--bigrams", required=True, help="TSV: 'w1 w2'<TAB>count")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-n", type=int, default=20000)
    args = ap.parse_args()

    baseline = {
        "unigrams": read_counts(Path(args.unigrams), args.top_n, 1),
        "bigrams": read_counts(Path(args.bigrams), args.top_n, 2),
    }
    Path(args.out).write_text(json.dumps(baseline), encoding="utf-8")
    print(
        f"wrote {args.out}: {len(baseline['unigrams'])} unigrams, "
        f"{len(baseline['bigrams'])} bigrams"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Generate the baseline**

Source: Peter Norvig's frequency tables derived from the Google Web Trillion Word
Corpus — modern web English, correctly licensed (the underlying Google data is
CC BY 3.0), and already in the TSV shape the script expects.

Download to the scratch directory, not into the repo:

```bash
curl -sL https://norvig.com/ngrams/count_1w.txt -o <scratch>/count_1w.txt
curl -sL https://norvig.com/ngrams/count_2w.txt -o <scratch>/count_2w.txt
python scripts/build_baseline.py --unigrams <scratch>/count_1w.txt \
  --bigrams <scratch>/count_2w.txt --out fixtures/baseline_ngrams.json
```

Verify the committed file is under 3 MB. If larger, lower `--top-n` to 10000 and
regenerate. Record the source and its CC BY 3.0 attribution in
`fixtures/README.md`, which you must also create.

If both URLs are unreachable, report BLOCKED rather than substituting a literary
corpus — the modern-English property is the point of this step.

- [ ] **Step 7: Write the fixture integrity test**

```python
# tests/test_fixtures.py
from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"


def load_all():
    parser = BytesParser(policy=policy.default)
    return [parser.parsebytes(p.read_bytes()) for p in sorted(SYNTHETIC.glob("*.eml"))]


def test_corpus_size():
    assert len(list(SYNTHETIC.glob("*.eml"))) == 40


def test_every_message_is_from_dana():
    for msg in load_all():
        assert "dana@northwind-labs.com" in msg["From"]


def test_every_message_parses_with_a_body():
    for msg in load_all():
        assert msg.get_body(preferencelist=("plain",)) is not None


def test_baseline_shape():
    data = json.loads((FIXTURES / "baseline_ngrams.json").read_text(encoding="utf-8"))
    assert set(data) == {"unigrams", "bigrams"}
    assert len(data["unigrams"]) >= 5000
    assert len(data["bigrams"]) >= 5000
    assert data["unigrams"]["the"] > data["unigrams"].get("nevertheless", 0)


def test_baseline_is_modern_english():
    """A literary-prose baseline would rank ordinary business words as
    distinctive. Common workplace vocabulary must be present and non-trivial."""
    data = json.loads((FIXTURES / "baseline_ngrams.json").read_text(encoding="utf-8"))
    for word in ("email", "online", "website", "meeting"):
        assert data["unigrams"].get(word, 0) > 0, f"{word} missing from baseline"
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest tests/test_fixtures.py -v`
Expected: 5 passed. If `test_corpus_size` fails, you wrote the wrong number of `.eml` files.

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements-dev.txt pytest.ini scripts/build_baseline.py fixtures tests/test_fixtures.py
git commit -m "feat: repo scaffolding, synthetic fixture corpus, ngram baseline"
```

---

## Task 2: `ingest.py` — parsing and cleaning

**Files:**
- Create: `scripts/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `fixtures/synthetic/*.eml` from Task 1.
- Produces, importable by later tasks:
  - `strip_quoted(body: str) -> str`
  - `strip_signature(body: str) -> str`
  - `is_auto_reply(msg: EmailMessage) -> bool`
  - `extract_body(msg: EmailMessage) -> str`
  - `normalize(msg: EmailMessage, user_email: str) -> dict | None`
  - `dedupe(messages: list[dict], threshold: float = 0.85) -> list[dict]`
  - Message dict schema: `{"id": str, "date": str, "to_domains": list[str], "recipient_count": int, "subject": str, "body": str, "is_reply": bool, "word_count": int}`
  - CLI: `python scripts/ingest.py --eml-dir DIR --user EMAIL --out corpus.json`, also accepting `--mbox FILE` or `--json FILE`.

- [ ] **Step 1: Write failing tests for quote stripping**

```python
# tests/test_ingest.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from ingest import (  # noqa: E402
    dedupe,
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest'`

- [ ] **Step 3: Implement quote stripping**

```python
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
```

- [ ] **Step 4: Run to verify quote tests pass**

Run: `python -m pytest tests/test_ingest.py -v -k "quote or divider or plain"`
Expected: 5 passed. (Quote the `-k` expression — PowerShell splits it otherwise.)

- [ ] **Step 5: Write failing tests for signature stripping**

```python
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
```

- [ ] **Step 6: Run to verify failure**

Run: `python -m pytest tests/test_ingest.py -v -k "signature or footer or contact or signoff"`
Expected: FAIL — `ImportError: cannot import name 'strip_signature'`

- [ ] **Step 7: Implement signature stripping**

```python
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
    lines = body.rstrip().split("\n")
    while len(lines) > 1 and lines[-1].strip():
        last = lines[-1].strip()
        is_contact = bool(CONTACT_LINE.search(last)) and len(last.split()) <= 8
        if not is_contact:
            break
        lines.pop()
    return "\n".join(lines).rstrip()
```

- [ ] **Step 8: Run to verify signature tests pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: 9 passed.

- [ ] **Step 9: Write failing tests for normalization and dedupe**

```python
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
```

Add the `BytesParser`/`policy` imports to the test file's import block.

- [ ] **Step 10: Run to verify failure**

Run: `python -m pytest tests/test_ingest.py -v -k "normalize or dedupe"`
Expected: FAIL — `ImportError: cannot import name 'normalize'`

- [ ] **Step 11: Implement body extraction, normalization, and dedupe**

```python
AUTO_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond")
TAG_RE = re.compile(r"<[^>]+>")


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
        return TAG_RE.sub(" ", part.get_content())
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


def dedupe(messages: list[dict], threshold: float = 0.85) -> list[dict]:
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
```

- [ ] **Step 12: Run to verify all ingest tests pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: 13 passed.

- [ ] **Step 13: Add loaders and the CLI**

```python
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
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"{len(raw)} parsed -> {len(main_corpus)} usable, "
        f"{len(terse)} terse acks -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 14: Write the end-to-end CLI test**

```python
import subprocess


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
    assert data["stats"]["kept"] >= 12
    assert data["stats"]["terse"] == 3
    # Auto-replies dropped, near-duplicates collapsed
    assert data["stats"]["kept"] + data["stats"]["terse"] < 40
    for msg in data["messages"]:
        assert "wrote:" not in msg["body"]
        assert "Sent from my" not in msg["body"]
```

Add `import json` and `import subprocess` to the test imports.

- [ ] **Step 15: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all pass. If `test_cli_end_to_end` reports `kept < 12`, the cleaning is too aggressive — inspect `corpus.json` and check which messages emptied out.

- [ ] **Step 16: Commit**

```bash
git add scripts/ingest.py tests/test_ingest.py
git commit -m "feat: email ingestion with quote, signature, and duplicate removal"
```

---

## Task 3: `fingerprint.py` — core metrics

**Files:**
- Create: `scripts/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: `corpus.json` from Task 2.
- Produces:
  - `sentences(text: str) -> list[str]`
  - `paragraphs(text: str) -> list[str]`
  - `shape_metrics(messages: list[dict]) -> dict` → `{"words_per_email": {"median": float, "iqr": [float, float]}, "words_per_sentence": {...}, "sentences_per_paragraph": {...}, "paragraphs_per_email": {...}}`
  - `opener_pattern(body: str) -> str` → one of `"hi_name"`, `"hey_name"`, `"name_dash"`, `"bare_name"`, `"none"`
  - `closer_pattern(body: str) -> dict` → `{"signoff": str, "name_form": str}`
  - `contraction_rate(text: str) -> float`
  - `punct_rates(text: str) -> dict` → per-100-word rates keyed `em_dash`, `ellipsis`, `exclamation`, `semicolon`, `parenthesis`, `emoji`
  - `stance(text: str) -> dict` → `{"hedges_per_100w": float, "imperative_rate": float, "question_rate": float, "bullet_rate": float}`
  - `ask_placement(text: str) -> float | None` → position of the ask as a fraction of email length, `None` when no ask found
  - `lexicon(messages: list[dict], baseline: dict, top_n: int = 15) -> list[dict]`

- [ ] **Step 1: Write failing tests for text splitting and shape**

```python
# tests/test_fingerprint.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fingerprint import (  # noqa: E402
    ask_placement,
    closer_pattern,
    contraction_rate,
    opener_pattern,
    paragraphs,
    punct_rates,
    sentences,
    shape_metrics,
    stance,
)


def test_sentences_splits_on_terminators():
    assert sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_sentences_ignores_common_abbreviations():
    assert len(sentences("Meet Dr. Webb at 5 p.m. tomorrow.")) == 1


def test_paragraphs_split_on_blank_lines():
    assert paragraphs("A\nB\n\nC") == ["A\nB", "C"]


def test_shape_metrics_median():
    msgs = [{"body": "one two three"}, {"body": "one two"}, {"body": "one"}]
    assert shape_metrics(msgs)["words_per_email"]["median"] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fingerprint'`

- [ ] **Step 3: Implement splitting and shape metrics**

```python
# scripts/fingerprint.py
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

# Each lookbehind must include the trailing period: the split point sits AFTER
# the ".", so "(?<!\bDr)" would inspect "r." and never fire.
ABBREV = (
    r"(?<!\bDr\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bSt\.)"
    r"(?<!\bp\.m\.)(?<!\ba\.m\.)(?<!\be\.g\.)(?<!\bi\.e\.)"
)
SENTENCE_END = re.compile(ABBREV + r"(?<=[.!?])\s+(?=[A-Z0-9])")
WORD = re.compile(r"[A-Za-z']+")


def sentences(text: str) -> list[str]:
    parts = [s.strip() for s in SENTENCE_END.split(text.strip()) if s.strip()]
    return parts


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def _summary(values: list[float]) -> dict:
    if not values:
        return {"median": 0.0, "iqr": [0.0, 0.0]}
    ordered = sorted(values)
    if len(ordered) >= 4:
        quartiles = statistics.quantiles(ordered, n=4)
        iqr = [quartiles[0], quartiles[2]]
    else:
        iqr = [ordered[0], ordered[-1]]
    return {"median": statistics.median(ordered), "iqr": iqr}


def shape_metrics(messages: list[dict]) -> dict:
    words_per_email, words_per_sentence = [], []
    sents_per_para, paras_per_email = [], []
    for msg in messages:
        body = msg["body"]
        words_per_email.append(len(WORD.findall(body)))
        paras = paragraphs(body)
        paras_per_email.append(len(paras))
        for para in paras:
            sents = sentences(para)
            sents_per_para.append(len(sents))
            for sent in sents:
                words_per_sentence.append(len(WORD.findall(sent)))
    return {
        "words_per_email": _summary(words_per_email),
        "words_per_sentence": _summary(words_per_sentence),
        "sentences_per_paragraph": _summary(sents_per_para),
        "paragraphs_per_email": _summary(paras_per_email),
    }
```

- [ ] **Step 4: Run to verify shape tests pass**

Run: `python -m pytest tests/test_fingerprint.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write failing tests for openers, closers, and mechanics**

```python
def test_opener_patterns():
    assert opener_pattern("Hi Priya,\n\nBody here.") == "hi_name"
    assert opener_pattern("Hey Marcus -\n\nBody.") == "hey_name"
    assert opener_pattern("Priya —\n\nBody.") == "name_dash"
    assert opener_pattern("Priya,\n\nBody.") == "bare_name"
    assert opener_pattern("Pushed the fix.") == "none"


def test_closer_pattern():
    result = closer_pattern("Body text.\n\nBest,\nDana Reyes")
    assert result["signoff"] == "best"
    assert result["name_form"] == "full_name"

    result = closer_pattern("Body text.\n\n— Dana")
    assert result["signoff"] == "none"
    assert result["name_form"] == "first_name"


def test_contraction_rate():
    assert contraction_rate("I don't think we can't win") == 1.0
    assert contraction_rate("I do not think it") == 0.0


def test_punct_rates_per_100_words():
    text = " ".join(["word"] * 100) + " — !"
    rates = punct_rates(text)
    assert rates["em_dash"] == 1.0
    assert rates["exclamation"] == 1.0


def test_stance_detects_hedges_and_questions():
    result = stance("I just think maybe we should wait. Can you confirm?")
    assert result["hedges_per_100w"] > 0
    assert result["question_rate"] == 0.5


def test_ask_placement_front_vs_back():
    front = "Can you confirm by Thursday? The rest is context. More context here."
    back = "Here is context. More context follows. Can you confirm by Thursday?"
    assert ask_placement(front) < 0.5
    assert ask_placement(back) > 0.5
    assert ask_placement("No request in this text at all.") is None
```

- [ ] **Step 6: Run to verify failure**

Run: `python -m pytest tests/test_fingerprint.py -v -k "opener or closer or contraction or punct or stance or ask"`
Expected: FAIL — `ImportError: cannot import name 'opener_pattern'`

- [ ] **Step 7: Implement openers, closers, mechanics, stance, and ask placement**

```python
CONTRACTIBLE = re.compile(
    r"\b(do not|does not|did not|is not|are not|was not|were not|cannot|can not|"
    r"will not|would not|should not|could not|have not|has not|had not|it is|"
    r"that is|there is|I am|you are|we are|they are|I will|we will)\b",
    re.IGNORECASE,
)
CONTRACTION = re.compile(r"\b\w+'(t|s|re|ll|ve|d|m)\b", re.IGNORECASE)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
HEDGES = re.compile(
    r"\b(just|i think|maybe|perhaps|sorry to|a bit|kind of|sort of|possibly|"
    r"if that works|no rush|whenever you get a chance)\b",
    re.IGNORECASE,
)
ASK = re.compile(
    r"(\?|\b(can you|could you|would you|please|let me know|need you to|"
    r"send me|confirm|by (monday|tuesday|wednesday|thursday|friday|eod|end of))\b)",
    re.IGNORECASE,
)
IMPERATIVE_START = re.compile(
    r"^(send|check|confirm|review|let|call|ping|see|take|hold|drop|add|move|use)\b",
    re.IGNORECASE,
)
SIGNOFFS = [
    "best", "thanks", "thank you", "cheers", "regards", "best regards",
    "talk soon", "sincerely", "all the best", "appreciate it",
]


def opener_pattern(body: str) -> str:
    first = body.strip().split("\n", 1)[0].strip()
    if re.match(r"^hi\s+[A-Z][\w'-]*\b", first, re.IGNORECASE):
        return "hi_name"
    if re.match(r"^(hey|hello)\s+[A-Z][\w'-]*\b", first, re.IGNORECASE):
        return "hey_name"
    if re.match(r"^[A-Z][\w'-]*\s*[—–-]\s*$", first) or re.match(
        r"^[A-Z][\w'-]*\s*[—–-]\s+\S", first
    ):
        return "name_dash"
    if re.match(r"^[A-Z][\w'-]*,\s*$", first):
        return "bare_name"
    return "none"


def closer_pattern(body: str) -> dict:
    tail = [ln.strip() for ln in body.strip().split("\n") if ln.strip()][-2:]
    signoff = "none"
    name_form = "none"
    for line in tail:
        cleaned = line.rstrip(",").strip().lower()
        if cleaned in SIGNOFFS:
            signoff = cleaned
    last = tail[-1] if tail else ""
    stripped = last.lstrip("—–-").strip().rstrip(",")
    words = stripped.split()
    if 1 <= len(words) <= 3 and all(w[:1].isupper() for w in words if w):
        if len(words) == 1:
            name_form = "initial" if len(words[0]) <= 2 else "first_name"
        else:
            name_form = "full_name"
    return {"signoff": signoff, "name_form": name_form}


def contraction_rate(text: str) -> float:
    contracted = len(CONTRACTION.findall(text))
    expanded = len(CONTRACTIBLE.findall(text))
    total = contracted + expanded
    return contracted / total if total else 0.0


def _per_100(count: int, words: int) -> float:
    return round(count * 100 / words, 3) if words else 0.0


def punct_rates(text: str) -> dict:
    words = len(WORD.findall(text))
    return {
        "em_dash": _per_100(len(re.findall(r"[—–]|--", text)), words),
        "ellipsis": _per_100(len(re.findall(r"\.\.\.|…", text)), words),
        "exclamation": _per_100(text.count("!"), words),
        "semicolon": _per_100(text.count(";"), words),
        "parenthesis": _per_100(text.count("("), words),
        "emoji": _per_100(len(EMOJI.findall(text)), words),
    }


def stance(text: str) -> dict:
    words = len(WORD.findall(text))
    sents = sentences(text)
    questions = sum(1 for s in sents if s.rstrip().endswith("?"))
    imperatives = sum(1 for s in sents if IMPERATIVE_START.match(s))
    bullets = sum(1 for ln in text.split("\n") if re.match(r"^\s*[-*•]\s+", ln))
    return {
        "hedges_per_100w": _per_100(len(HEDGES.findall(text)), words),
        "imperative_rate": round(imperatives / len(sents), 3) if sents else 0.0,
        "question_rate": round(questions / len(sents), 3) if sents else 0.0,
        "bullet_rate": round(bullets / len(sents), 3) if sents else 0.0,
    }


def ask_placement(text: str) -> float | None:
    sents = sentences(text)
    for index, sent in enumerate(sents):
        if ASK.search(sent):
            return round(index / len(sents), 3)
    return None
```

- [ ] **Step 8: Run to verify all metric tests pass**

Run: `python -m pytest tests/test_fingerprint.py -v`
Expected: 10 passed.

- [ ] **Step 9: Write the failing lexicon test**

```python
from fingerprint import lexicon  # add to the import block


def test_lexicon_surfaces_distinctive_phrases():
    """Every word in the sample must appear in the baseline except the
    distinctive ones. An absent word scores near-infinite log-odds against the
    smoothing floor, which would drown out the phrase under test."""
    baseline = {
        "unigrams": {
            "the": 0.05, "a": 0.03, "at": 0.02, "numbers": 0.001,
            "worth": 0.0000001, "look": 0.0000002,
        },
        "bigrams": {
            "at the": 0.002, "the numbers": 0.001, "a look": 0.0009,
            "look at": 0.002, "numbers worth": 0.0005,
            "worth a": 0.0000001,
        },
    }
    msgs = [{"body": "worth a look at the numbers"} for _ in range(10)]
    phrases = [item["phrase"] for item in lexicon(msgs, baseline, top_n=4)]
    assert "worth" in phrases
    assert "the" not in phrases
```

- [ ] **Step 10: Run to verify failure**

Run: `python -m pytest tests/test_fingerprint.py -v -k lexicon`
Expected: FAIL — `ImportError: cannot import name 'lexicon'`

- [ ] **Step 11: Implement the lexicon metric**

```python
SMOOTHING = 1e-7


def lexicon(messages: list[dict], baseline: dict, top_n: int = 15) -> list[dict]:
    """Rank the user's n-grams by log-odds against a common-English baseline."""
    words: list[str] = []
    for msg in messages:
        words.extend(w.lower() for w in WORD.findall(msg["body"]))

    uni = Counter(words)
    bi = Counter(f"{a} {b}" for a, b in zip(words, words[1:]))
    uni_total = sum(uni.values()) or 1
    bi_total = sum(bi.values()) or 1

    scored = []
    for counts, total, base_key in (
        (uni, uni_total, "unigrams"),
        (bi, bi_total, "bigrams"),
    ):
        base = baseline.get(base_key, {})
        for phrase, count in counts.items():
            if count < 3:
                continue
            observed = count / total
            expected = base.get(phrase, SMOOTHING)
            scored.append(
                {
                    "phrase": phrase,
                    "count": count,
                    "log_odds": round(math.log(observed / expected), 3),
                }
            )
    scored.sort(key=lambda item: item["log_odds"], reverse=True)
    return scored[:top_n]
```

- [ ] **Step 12: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add scripts/fingerprint.py tests/test_fingerprint.py
git commit -m "feat: core style metrics — shape, openers, mechanics, stance, lexicon"
```

---

## Task 4: Register clustering, exemplar selection, and the fingerprint CLI

**Files:**
- Modify: `scripts/fingerprint.py`
- Modify: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: everything from Task 3.
- Produces:
  - `classify_register(msg: dict, user_domain: str) -> str` → one of `"internal"`, `"client"`, `"cold_outreach"`, `"vendor"`, `"personal"`
  - `aggregate(messages: list[dict], baseline: dict) -> dict` → full metric block for a message set
  - `select_exemplars(messages: list[dict], count: int = 4) -> list[dict]`
  - CLI: `python scripts/fingerprint.py --corpus corpus.json --baseline fixtures/baseline_ngrams.json --out fingerprint.json --exemplars exemplars.json`
  - `fingerprint.json` schema: `{"user": str, "corpus_size": int, "date_range": [str, str], "baseline": <metric block>, "registers": {"<name>": {"count": int, "metrics": <metric block>}}, "suppressed_registers": {"<name>": int}, "english_metrics_valid": bool}`
  - `exemplars.json` schema: `{"<register>": [{"subject": str, "body": str, "word_count": int}]}`

- [ ] **Step 1: Write failing tests for register classification**

```python
from fingerprint import aggregate, classify_register, select_exemplars  # add to imports

USER_DOMAIN = "northwind-labs.com"


def test_classify_internal():
    msg = {"to_domains": ["northwind-labs.com"], "is_reply": True, "body": "x"}
    assert classify_register(msg, USER_DOMAIN) == "internal"


def test_classify_personal_consumer_domain():
    msg = {"to_domains": ["gmail.com"], "is_reply": False, "body": "x"}
    assert classify_register(msg, USER_DOMAIN) == "personal"


def test_classify_cold_outreach_is_non_reply_external():
    msg = {"to_domains": ["harborline.com"], "is_reply": False, "body": "x"}
    assert classify_register(msg, USER_DOMAIN) == "cold_outreach"


def test_classify_client_is_external_reply():
    msg = {"to_domains": ["harborline.com"], "is_reply": True, "body": "x"}
    assert classify_register(msg, USER_DOMAIN) == "client"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_fingerprint.py -v -k classify`
Expected: FAIL — `ImportError: cannot import name 'classify_register'`

- [ ] **Step 3: Implement register classification and aggregation**

```python
CONSUMER_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "me.com", "aol.com", "proton.me",
}
VENDOR_HINTS = ("billing", "support", "invoices", "noreply", "accounts")
MIN_REGISTER_SIZE = 8
MIN_CORPUS_SIZE = 12


def classify_register(msg: dict, user_domain: str) -> str:
    domains = msg.get("to_domains") or []
    if any(d == user_domain for d in domains):
        return "internal"
    if any(d in CONSUMER_DOMAINS for d in domains):
        return "personal"
    subject = (msg.get("subject") or "").lower()
    if any(hint in subject for hint in VENDOR_HINTS):
        return "vendor"
    return "client" if msg.get("is_reply") else "cold_outreach"


def aggregate(messages: list[dict], baseline: dict) -> dict:
    joined = "\n\n".join(m["body"] for m in messages)
    openers = Counter(opener_pattern(m["body"]) for m in messages)
    closer_data = [closer_pattern(m["body"]) for m in messages]
    closers = Counter(c["signoff"] for c in closer_data)
    name_forms = Counter(c["name_form"] for c in closer_data)
    placements = [
        p for p in (ask_placement(m["body"]) for m in messages) if p is not None
    ]
    subjects = [m["subject"] for m in messages if m["subject"]]
    return {
        "shape": shape_metrics(messages),
        "openers": {k: round(v / len(messages), 3) for k, v in openers.items()},
        "closers": {k: round(v / len(messages), 3) for k, v in closers.items()},
        "name_forms": {k: round(v / len(messages), 3) for k, v in name_forms.items()},
        "contraction_rate": round(contraction_rate(joined), 3),
        "punctuation": punct_rates(joined),
        "stance": stance(joined),
        "ask_placement_median": (
            round(statistics.median(placements), 3) if placements else None
        ),
        "subject": {
            "median_words": (
                statistics.median([len(s.split()) for s in subjects])
                if subjects else 0
            ),
            "lowercase_rate": round(
                sum(1 for s in subjects if s == s.lower()) / len(subjects), 3
            ) if subjects else 0.0,
            "question_rate": round(
                sum(1 for s in subjects if s.rstrip().endswith("?")) / len(subjects), 3
            ) if subjects else 0.0,
        },
        "lexicon": lexicon(messages, baseline),
    }
```

- [ ] **Step 4: Run to verify classification tests pass**

Run: `python -m pytest tests/test_fingerprint.py -v -k classify`
Expected: 4 passed.

- [ ] **Step 5: Write the failing exemplar-selection test**

```python
def test_select_exemplars_prefers_median_length_with_an_ask():
    msgs = [
        {"subject": "a", "body": "tiny", "word_count": 1},
        {"subject": "b", "body": "Can you confirm the date? " + "word " * 40,
         "word_count": 45},
        {"subject": "c", "body": "word " * 400, "word_count": 400},
    ]
    picked = select_exemplars(msgs, count=1)
    assert picked[0]["subject"] == "b"


def test_select_exemplars_respects_count():
    msgs = [
        {"subject": str(i), "body": "Can you confirm? " + "word " * 30,
         "word_count": 33}
        for i in range(10)
    ]
    assert len(select_exemplars(msgs, count=4)) == 4
```

- [ ] **Step 6: Run to verify failure**

Run: `python -m pytest tests/test_fingerprint.py -v -k exemplar`
Expected: FAIL — `ImportError: cannot import name 'select_exemplars'`

- [ ] **Step 7: Implement exemplar selection**

```python
def select_exemplars(messages: list[dict], count: int = 4) -> list[dict]:
    """Pick messages that best demonstrate the voice: near-median length, with an ask."""
    if not messages:
        return []
    median_words = statistics.median(m["word_count"] for m in messages)

    def score(msg: dict) -> float:
        spread = abs(msg["word_count"] - median_words) / (median_words or 1)
        has_ask = 1.0 if ASK.search(msg["body"]) else 0.0
        multi_para = 0.3 if len(paragraphs(msg["body"])) > 1 else 0.0
        return has_ask + multi_para - spread

    ranked = sorted(messages, key=score, reverse=True)
    return [
        {"subject": m["subject"], "body": m["body"], "word_count": m["word_count"]}
        for m in ranked[:count]
    ]
```

- [ ] **Step 8: Run to verify exemplar tests pass**

Run: `python -m pytest tests/test_fingerprint.py -v -k exemplar`
Expected: 2 passed.

- [ ] **Step 9: Add the CLI**

```python
NON_ASCII_THRESHOLD = 0.15


def _english_likely(messages: list[dict]) -> bool:
    joined = "".join(m["body"] for m in messages)
    if not joined:
        return True
    non_ascii = sum(1 for ch in joined if ord(ch) > 127)
    return non_ascii / len(joined) < NON_ASCII_THRESHOLD


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute a style fingerprint.")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exemplars", required=True)
    args = ap.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    messages = corpus["messages"]

    if len(messages) < MIN_CORPUS_SIZE:
        print(
            f"ERROR: {len(messages)} usable messages, need {MIN_CORPUS_SIZE}. "
            f"Parsed {corpus['stats']['raw']}, "
            f"dropped {corpus['stats']['raw'] - len(messages)} as quoted-only, "
            f"auto-replies, duplicates, or too short."
        )
        return 1

    user_domain = corpus["user"].split("@", 1)[1].lower()
    buckets: dict[str, list[dict]] = {}
    for msg in messages:
        buckets.setdefault(classify_register(msg, user_domain), []).append(msg)

    registers, suppressed = {}, {}
    for name, group in buckets.items():
        if len(group) >= MIN_REGISTER_SIZE:
            registers[name] = {"count": len(group), "metrics": aggregate(group, baseline)}
        else:
            suppressed[name] = len(group)

    dates = sorted(m["date"] for m in messages if m["date"])
    fingerprint = {
        "user": corpus["user"],
        "corpus_size": len(messages),
        "date_range": [dates[0], dates[-1]] if dates else ["", ""],
        "baseline": aggregate(messages, baseline),
        "registers": registers,
        "suppressed_registers": suppressed,
        "english_metrics_valid": _english_likely(messages),
    }
    Path(args.out).write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")

    exemplars = {name: select_exemplars(group) for name, group in buckets.items()}
    if corpus.get("terse_ack"):
        exemplars["terse_ack"] = select_exemplars(corpus["terse_ack"], count=3)
    Path(args.exemplars).write_text(json.dumps(exemplars, indent=2), encoding="utf-8")

    print(
        f"{len(messages)} messages, {len(registers)} registers "
        f"-> {args.out}, {args.exemplars}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 10: Write the CLI test against the fixture corpus**

```python
import json
import subprocess


def test_fingerprint_cli_on_synthetic_corpus(tmp_path):
    root = Path(__file__).parent.parent
    corpus = tmp_path / "corpus.json"
    subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(root / "fixtures" / "synthetic"),
         "--user", "dana@northwind-labs.com", "--out", str(corpus)],
        check=True, capture_output=True,
    )
    fp = tmp_path / "fingerprint.json"
    ex = tmp_path / "exemplars.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "fingerprint.py"),
         "--corpus", str(corpus),
         "--baseline", str(root / "fixtures" / "baseline_ngrams.json"),
         "--out", str(fp), "--exemplars", str(ex)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(fp.read_text(encoding="utf-8"))

    # Dana's designed traits must be recovered from the data
    assert data["baseline"]["shape"]["words_per_email"]["median"] < 120
    assert "internal" in data["registers"]
    assert data["baseline"]["punctuation"]["em_dash"] > 0
    phrases = [item["phrase"] for item in data["baseline"]["lexicon"]]
    assert any("worth" in p for p in phrases)

    exemplars = json.loads(ex.read_text(encoding="utf-8"))
    assert exemplars["internal"]
```

- [ ] **Step 11: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all pass. If the `worth` assertion fails, the fixture corpus does not repeat the pet phrase often enough — add it to more messages rather than weakening the test.

- [ ] **Step 12: Commit**

```bash
git add scripts/fingerprint.py tests/test_fingerprint.py
git commit -m "feat: register clustering, exemplar selection, fingerprint CLI"
```

---

## Task 5: `redact.py` — PII scrubbing

**Files:**
- Create: `scripts/redact.py`
- Test: `tests/test_redact.py`

**Interfaces:**
- Consumes: `exemplars.json` from Task 4.
- Produces:
  - `redact(text: str, keep_names: set[str] | None = None) -> str`
  - `redact_exemplars(data: dict, keep_names: set[str]) -> dict`
  - CLI: `python scripts/redact.py --in exemplars.json --out exemplars.redacted.json --keep-name Dana`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_redact.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from redact import redact  # noqa: E402


def test_redacts_email_addresses():
    assert "priya@harborline.com" not in redact("Ping priya@harborline.com today")
    assert "[EMAIL]" in redact("Ping priya@harborline.com today")


def test_redacts_phone_numbers():
    assert "[PHONE]" in redact("Call +1 555 018 2299 tomorrow")


def test_redacts_urls():
    assert "[URL]" in redact("See https://harborline.com/deck for details")


def test_redacts_currency():
    assert "[$AMOUNT]" in redact("The contract is $47,500 for the year")


def test_preserves_the_users_own_first_name():
    assert "Dana" in redact("Thanks,\nDana", keep_names={"Dana"})


def test_preserves_dates_and_weekdays():
    out = redact("Can you confirm by Thursday, April 17?")
    assert "Thursday" in out and "April" in out


def test_preserves_length_within_tolerance():
    """Rhythm is what we're modeling — redaction must replace, not delete."""
    original = "Hi Priya, the invoice for $4,200 goes to priya@harborline.com today."
    ratio = len(redact(original)) / len(original)
    assert 0.7 < ratio < 1.4
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_redact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'redact'`

- [ ] **Step 3: Implement redaction**

```python
# scripts/redact.py
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"https?://\S+|\bwww\.\S+"), "[URL]"),
    (re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?\b"), "[$AMOUNT]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)"), "[PHONE]"),
    (re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Blvd)\b"),
     "[ADDRESS]"),
]

WEEKDAYS_MONTHS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}

# Capitalized words in salutation or signoff position are almost always people.
SALUTATION = re.compile(
    r"^(Hi|Hey|Hello|Dear)\s+([A-Z][\w'-]+)", re.MULTILINE
)
SIGNOFF_NAME = re.compile(
    r"^(Best|Thanks|Cheers|Regards|Sincerely|Best regards),?\s*\n\s*([A-Z][\w'-]+"
    r"(?:\s+[A-Z][\w'-]+)?)\s*$",
    re.MULTILINE,
)


def redact(text: str, keep_names: set[str] | None = None) -> str:
    keep = {n.lower() for n in (keep_names or set())}

    for pattern, placeholder in PATTERNS:
        text = pattern.sub(placeholder, text)

    def _salutation(match: re.Match) -> str:
        greeting, name = match.group(1), match.group(2)
        if name.lower() in keep or name.lower() in WEEKDAYS_MONTHS:
            return match.group(0)
        return f"{greeting} [FIRST]"

    text = SALUTATION.sub(_salutation, text)

    def _signoff(match: re.Match) -> str:
        closer, name = match.group(1), match.group(2)
        if name.split()[0].lower() in keep:
            return match.group(0)
        return f"{closer},\n[FIRST]"

    return SIGNOFF_NAME.sub(_signoff, text)


def redact_exemplars(data: dict, keep_names: set[str]) -> dict:
    return {
        register: [
            {**ex, "body": redact(ex["body"], keep_names),
             "subject": redact(ex["subject"], keep_names)}
            for ex in items
        ]
        for register, items in data.items()
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrub PII from exemplars.")
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-name", action="append", default=[],
                    help="Name to preserve, repeatable. Use the profile owner's name.")
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    result = redact_exemplars(data, set(args.keep_name))
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"redacted -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify tests pass**

Run: `python -m pytest tests/test_redact.py -v`
Expected: 7 passed.

- [ ] **Step 5: Add the residual-PII sweep test**

```python
import json
import re
import subprocess


def test_no_raw_emails_survive_full_pipeline(tmp_path):
    """Belt and braces: run the real fixture corpus through and grep the output."""
    root = Path(__file__).parent.parent
    corpus, fp = tmp_path / "corpus.json", tmp_path / "fp.json"
    ex, red = tmp_path / "ex.json", tmp_path / "red.json"

    subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(root / "fixtures" / "synthetic"),
         "--user", "dana@northwind-labs.com", "--out", str(corpus)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(root / "scripts" / "fingerprint.py"),
         "--corpus", str(corpus),
         "--baseline", str(root / "fixtures" / "baseline_ngrams.json"),
         "--out", str(fp), "--exemplars", str(ex)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(root / "scripts" / "redact.py"),
         "--in", str(ex), "--out", str(red), "--keep-name", "Dana"],
        check=True, capture_output=True,
    )
    text = red.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), "raw email address survived"
    assert not re.search(r"\+?\d[\d\s().-]{8,}\d", text), "raw phone number survived"
    assert "Dana" in text, "profile owner's name should be preserved"
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/redact.py tests/test_redact.py
git commit -m "feat: PII redaction preserving rhythm and the profile owner's name"
```

---

## Task 6: Plugin manifests and the analyze mode

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`
- Create: `skills/write-as-me/SKILL.md`
- Create: `commands/wam.md`

**Interfaces:**
- Consumes: all four scripts via their CLIs.
- Produces: `/write-as-me` and `/wam` commands; a profile at `~/.claude/wam/<name>.md`.

- [ ] **Step 1: Write `.claude-plugin/plugin.json`**

```json
{
  "name": "write-as-me",
  "version": "0.1.0",
  "description": "Learns your email writing style from your sent mail and drafts new email in your voice.",
  "author": {
    "name": "Ken Arakelian",
    "url": "https://github.com/kenarakelian1"
  },
  "homepage": "https://github.com/kenarakelian1/write-as-me",
  "license": "MIT",
  "keywords": ["email", "writing", "style", "voice", "gmail"]
}
```

- [ ] **Step 2: Write `.claude-plugin/marketplace.json`**

```json
{
  "name": "write-as-me",
  "owner": {
    "name": "Ken Arakelian",
    "url": "https://github.com/kenarakelian1"
  },
  "plugins": [
    {
      "name": "write-as-me",
      "source": "./",
      "description": "Learns your email writing style from your sent mail and drafts new email in your voice."
    }
  ]
}
```

- [ ] **Step 3: Write `skills/write-as-me/SKILL.md` — frontmatter and mode routing**

```markdown
---
name: write-as-me
description: Use when the user wants email written in their own voice, wants to analyze their writing style, or asks to build or refresh a personal style profile. Triggers on "write as me", "in my voice", "sounds like me", "draft this email", "/wam".
---

# write-as-me

Two modes. Pick by whether the user supplied an intent.

| Invocation | Mode |
| --- | --- |
| `/write-as-me` or `/wam`, no arguments | **Analyze** — build the style profile |
| `/write-as-me <what to say>` | **Write** — draft using the existing profile |
| `--refresh` present | **Analyze**, overwriting the existing profile |

Profiles live in `~/.claude/wam/`. Never write a profile into a repository.
Scripts referenced below live in this plugin's `scripts/` directory.
```

- [ ] **Step 4: Add the analyze-mode body to `SKILL.md`**

````markdown
## Analyze mode

If `~/.claude/wam/default.md` already exists and `--refresh` was not passed, tell the
user it exists, show its metadata line, and ask whether to refresh or switch to write
mode. Do not silently overwrite.

### Step 1 — Find the mail

Try in order and announce which tier you used.

**Tier 1, Gmail connector.** If Gmail tools are available, search `in:sent -in:chats`
over the last 12 months. Fetch up to 150 messages. Write them to
`~/.claude/wam/cache/raw.json` as a JSON array of
`{id, from, to, cc, subject, date, body}`.

**Tier 2, local export.** Look for `.mbox` or `.eml` files in `./emails/`. If nothing
is there, ask the user for a path. Google Takeout, Outlook, and Apple Mail exports all
work.

**Tier 3, paste.** Ask the user to paste 15–30 sent emails. Write them into the same
`raw.json` shape.

Ask for the user's own email address if you cannot infer it from the data.

### Step 2 — Run the pipeline

```bash
python scripts/ingest.py --json ~/.claude/wam/cache/raw.json \
  --user <EMAIL> --out ~/.claude/wam/cache/corpus.json

python scripts/fingerprint.py --corpus ~/.claude/wam/cache/corpus.json \
  --baseline fixtures/baseline_ngrams.json \
  --out ~/.claude/wam/cache/fingerprint.json \
  --exemplars ~/.claude/wam/cache/exemplars.json

python scripts/redact.py --in ~/.claude/wam/cache/exemplars.json \
  --out ~/.claude/wam/cache/exemplars.redacted.json --keep-name <FIRST NAME>
```

Use `--eml-dir` or `--mbox` instead of `--json` for Tier 2.

If `fingerprint.py` exits non-zero with a corpus-size error, relay its message
verbatim and stop. Do not generate a profile from fewer than 12 messages.

### Step 3 — Read the small artifacts

Read `fingerprint.json` and `exemplars.redacted.json`. **Never read `corpus.json` or
`raw.json`** — they hold the full unredacted corpus and will flood context.

### Step 4 — Verify the redaction

Scan the redacted exemplars for anything the regexes missed: person names in the body,
company names, project code names, account numbers. Replace with `[FIRST]`,
`[COMPANY]`, `[PROJECT]`. Keep the owner's own first name in signoffs.

Never present an exemplar you have not personally checked.

### Step 5 — Write the profile

Write `~/.claude/wam/default.md` in this exact structure.

Rules for the prose:
- **Directives, not description.** "Median 68 words; over 120 is off-voice" — not
  "concise and direct."
- Every claim carries its number.
- The **Never do this** section is the most valuable part. Derive it from what is
  *absent*: signoffs at 0%, zero exclamation marks to clients, hedges below baseline.
  Include the standard AI tells the corpus never uses — "I hope this finds you well",
  "circle back", "touch base", "reach out", "delve", "leverage" as a verb.
- Register sections state *deltas* from baseline, never repeat the full metric block.
- If `english_metrics_valid` is false, omit contraction rate and hedge markers, and
  note the omission.
- Name suppressed registers with their counts so the user knows what was too thin.

```markdown
# How to write as <Name>

## Core directives
- Median length <N> words. Over <N*1.8> is off-voice.
- Open with "<pattern>" (<X>%) ... 
- Put the ask <early/late>: median position <X> of the way in.
- <contraction guidance>, <punctuation tics with rates>

## Never do this
- Never opens with "I hope this finds you well."
- <absence-derived rules with counts>

## By audience
| Register | Messages | Delta from baseline |
| --- | --- | --- |

## Examples
### <Register> — <what it does>
<redacted exemplar>

## Metadata
Corpus: <N> messages, <start> to <end>. Registers: <list>.
Too thin to profile: <suppressed with counts>. Generated <date>.
```

### Step 6 — Clean up and report

Delete `~/.claude/wam/cache/` unless the user passed `--keep-cache`. Report: tier used,
messages analyzed, registers found, profile path. Show the **Never do this** list, since
it is the most immediately useful part, and offer to draft something as a test.
````

- [ ] **Step 5: Write `commands/wam.md`**

```markdown
---
description: Write email in your own voice (alias for /write-as-me)
---

Invoke the `write-as-me` skill with these arguments: $ARGUMENTS

If no arguments were supplied, run analyze mode. Otherwise run write mode.
```

- [ ] **Step 6: Verify the plugin loads**

Run: `/plugin marketplace add C:\Users\Ken\Documents\GitHub\write-as-me` then
`/plugin install write-as-me`, then check `/help` lists both `/write-as-me` and `/wam`.

Expected: both commands appear. If not, validate both JSON manifests parse:
`python -c "import json,pathlib; [json.loads(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['.claude-plugin/plugin.json','.claude-plugin/marketplace.json']]; print('ok')"`

- [ ] **Step 7: Run analyze mode against the fixtures end to end**

Run `/write-as-me` and, when it asks for a source, give it
`fixtures/synthetic` as an eml directory with user `dana@northwind-labs.com`.

Expected: a profile at `~/.claude/wam/default.md` describing Dana — short emails, em
dashes, "worth a look" in the lexicon, an internal register distinct from client.

If the profile reads generically ("professional and friendly"), the Step 5 rules are
not being followed; tighten the directive language in `SKILL.md` rather than accepting
the output.

- [ ] **Step 8: Commit**

```bash
git add .claude-plugin skills commands
git commit -m "feat: plugin manifests, skill definition, analyze mode"
```

---

## Task 7: Write mode

**Files:**
- Modify: `skills/write-as-me/SKILL.md`

**Interfaces:**
- Consumes: `~/.claude/wam/default.md` from Task 6.
- Produces: drafts in chat; optional Gmail draft creation.

- [ ] **Step 1: Append the write-mode section to `SKILL.md`**

````markdown
## Write mode

Triggered when the user supplies an intent: `/wam ask Priya to confirm the Q3 date`.

### Step 1 — Load the profile

Read `~/.claude/wam/default.md`. If it is missing, say so and offer to run analyze
mode. Do not draft from a guess about the user's voice.

### Step 2 — Pick the register

Infer from the recipient if the user named one: own domain → `internal`, consumer
domain → `personal`, otherwise `client`. Ask only when genuinely ambiguous and the
registers differ materially. One question maximum — do not interrogate.

If the chosen register was suppressed for thinness, use the baseline and say so.

### Step 3 — Draft

Imitate the exemplars for that register first and the metrics second. The exemplars
carry the voice; the metrics are guardrails.

Match: length band, opener, ask placement, signoff and name form, punctuation habits,
paragraph count.

### Step 4 — Self-check before showing anything

Check the draft against the profile:

1. Word count inside the band? If over, cut — do not compress by deleting articles.
2. Any phrase from **Never do this**? Rewrite it out.
3. Opener and signoff match the register's dominant pattern?
4. Ask in the right position?
5. Punctuation rates roughly in line — especially exclamation marks?

Revise silently and show only the final draft. Do not narrate the checklist.

### Step 5 — Present

Show subject and body as plain text, ready to copy. Add one line naming the register
used. If Gmail tools are available, offer to save it as a draft.

**Never send email.** Creating a draft is the furthest this skill goes, and only when
the user asks.
````

- [ ] **Step 2: Test write mode against the Dana profile**

With the fixture-derived profile in place, run:
`/wam ask Priya to confirm the Q3 rollout date by Thursday`

Expected: under ~80 words, opens `Hi Priya`, ask in the first two sentences, em dash
present, no exclamation mark, signs off `Best,` / `Dana Reyes`.

- [ ] **Step 3: Test the missing-profile path**

Temporarily rename `~/.claude/wam/default.md`, run `/wam draft a note to Marcus`.

Expected: the skill offers to run analysis rather than inventing a voice. Rename back.

- [ ] **Step 4: Commit**

```bash
git add skills/write-as-me/SKILL.md
git commit -m "feat: write mode with anti-pattern self-check"
```

---

## Task 8: Holdout eval and README

**Files:**
- Create: `scripts/eval_holdout.py`
- Create: `README.md`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `fingerprint.py` functions, a corpus, and generated drafts.
- Produces:
  - `compare(a: dict, b: dict) -> dict` → `{"<metric>": float}` absolute deltas over flattened scalar metrics
  - `verdict(profile_deltas: dict, control_deltas: dict) -> dict` → `{"metrics_compared": int, "profile_closer": int, "share": float, "pass": bool}`
  - CLI: `python scripts/eval_holdout.py --holdout holdout.json --profile-drafts drafts.json --control-drafts control.json --baseline fixtures/baseline_ngrams.json`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from eval_holdout import compare, flatten, verdict  # noqa: E402


def test_flatten_produces_scalar_paths():
    nested = {"shape": {"words_per_email": {"median": 68.0, "iqr": [40, 90]}},
              "contraction_rate": 0.4}
    flat = flatten(nested)
    assert flat["shape.words_per_email.median"] == 68.0
    assert flat["contraction_rate"] == 0.4
    assert "shape.words_per_email.iqr" not in flat  # lists are skipped


def test_compare_returns_absolute_deltas():
    a = {"contraction_rate": 0.4}
    b = {"contraction_rate": 0.1}
    assert compare(a, b)["contraction_rate"] == pytest.approx(0.3)


def test_verdict_fails_just_below_threshold():
    """2 of 3 is a 0.667 share — under the 0.7 bar, so this must not pass."""
    profile = {"m1": 0.1, "m2": 0.1, "m3": 0.5}
    control = {"m1": 0.9, "m2": 0.9, "m3": 0.1}
    result = verdict(profile, control)
    assert result["metrics_compared"] == 3
    assert result["profile_closer"] == 2
    assert result["pass"] is False


def test_verdict_passes_when_profile_wins_enough():
    profile = {"m1": 0.1, "m2": 0.1, "m3": 0.1, "m4": 0.9}
    control = {"m1": 0.9, "m2": 0.9, "m3": 0.9, "m4": 0.1}
    result = verdict(profile, control)
    assert result["share"] == 0.75
    assert result["pass"] is True


def test_verdict_fails_when_control_wins():
    result = verdict({"m1": 0.9}, {"m1": 0.1})
    assert result["pass"] is False
```

Add `import pytest` to the test file.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval_holdout'`

- [ ] **Step 3: Implement the eval harness**

```python
# scripts/eval_holdout.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fingerprint import aggregate  # noqa: E402

PASS_THRESHOLD = 0.7


def flatten(node: dict, prefix: str = "") -> dict:
    """Flatten a metric block to scalar leaves. Lists are skipped as unorderable."""
    out: dict[str, float] = {}
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{path}."))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[path] = float(value)
    return out


def compare(a: dict, b: dict) -> dict:
    flat_a, flat_b = flatten(a), flatten(b)
    return {
        key: abs(flat_a[key] - flat_b[key])
        for key in flat_a.keys() & flat_b.keys()
    }


def verdict(profile_deltas: dict, control_deltas: dict) -> dict:
    shared = profile_deltas.keys() & control_deltas.keys()
    closer = sum(1 for k in shared if profile_deltas[k] < control_deltas[k])
    share = closer / len(shared) if shared else 0.0
    return {
        "metrics_compared": len(shared),
        "profile_closer": closer,
        "share": round(share, 3),
        "pass": share >= PASS_THRESHOLD,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare profile-guided drafts against held-out originals."
    )
    ap.add_argument("--holdout", required=True, help="JSON list of held-out messages")
    ap.add_argument("--profile-drafts", required=True)
    ap.add_argument("--control-drafts", required=True)
    ap.add_argument("--baseline", required=True)
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731

    truth = aggregate(load(args.holdout), baseline)
    profile_deltas = compare(truth, aggregate(load(args.profile_drafts), baseline))
    control_deltas = compare(truth, aggregate(load(args.control_drafts), baseline))
    result = verdict(profile_deltas, control_deltas)

    print(json.dumps(result, indent=2))
    worst = sorted(profile_deltas.items(), key=lambda kv: -kv[1])[:5]
    print("\nLargest remaining gaps:")
    for metric, delta in worst:
        print(f"  {metric}: {delta:.3f}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify tests pass**

Run: `python -m pytest tests/test_eval.py -v`
Expected: 5 passed.

- [ ] **Step 5: Document the eval procedure in `README.md`**

The README must cover, in this order: what the plugin does, install commands, the
three ingestion tiers, a privacy section, the eval procedure, and development setup.

Privacy section, stated plainly:

> Your generated profile contains excerpts of your real email, redacted but not
> anonymized. It lives in `~/.claude/wam/`, outside any repository. Do not commit or
> share it. The raw corpus cache is deleted after each analysis run unless you pass
> `--keep-cache`.

Eval procedure:

> 1. Run analyze mode with `--keep-cache`.
> 2. Move 5 messages out of `corpus.json` into `holdout.json`; re-run
>    `fingerprint.py` on the remainder and regenerate the profile.
> 3. For each held-out message, ask `/wam` to draft from its subject plus a one-line
>    intent, without showing it the original. Collect drafts into `drafts.json`
>    using the corpus message shape.
> 4. Repeat with a fresh session and no profile loaded to build `control.json`.
> 5. Run `eval_holdout.py`. It exits 0 when the profile-guided drafts are closer to
>    the originals than the control on at least 70% of metrics.

- [ ] **Step 6: Run the whole suite one final time**

Run: `python -m pytest tests/ -v`
Expected: all pass, no skips.

- [ ] **Step 7: Commit**

```bash
git add scripts/eval_holdout.py tests/test_eval.py README.md
git commit -m "feat: holdout eval harness and README"
```

---

## Self-Review Notes

**Spec coverage.** Every spec section maps to a task: acquisition tiers → Task 6 Step 1;
cleaning → Task 2; the full metric list → Tasks 3–4; register clustering and the
8-message floor → Task 4; exemplar selection → Task 4; redaction → Task 5; profile
format → Task 6 Step 5; write mode → Task 7; synthetic fixtures → Task 1; unit tests →
Tasks 2, 3, 5; holdout eval → Task 8; error-handling table → Task 4 Step 9 (corpus
floor), Task 4 Step 9 (`english_metrics_valid`, single register via
`suppressed_registers`), Task 2 Step 13 (corrupt mbox skipping), Task 6 Step 1 (tier
fallthrough), Task 7 Step 2 (missing profile); privacy → Task 1 `.gitignore`, Task 6
Step 6 cache deletion, Task 8 README.

**Known deviation from the spec.** The spec described a model pass for name redaction
"catching what the regexes miss." That is not a script — it became Task 6 Step 4, a
mandatory verification step in the skill. Calling it out because a reader comparing
spec to plan would otherwise look for a missing function.

**Type consistency.** `aggregate()` is defined in Task 4 and reused by Task 8's eval,
same signature. The message dict schema from Task 2 flows unchanged through Tasks 3–5.
`ASK` and `paragraphs()` are defined in Task 3 and used by `select_exemplars()` in
Task 4 — same module, so no import needed.
