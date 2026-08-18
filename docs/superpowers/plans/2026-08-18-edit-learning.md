# Edit-Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let write-as-me learn from the edits a user makes before sending a draft, and propose profile changes once a pattern repeats.

**Architecture:** Write mode appends every draft it presents to `~/.claude/wam/drafts.jsonl`. Review mode finds the sent version in Gmail, measures the difference deterministically in Python, and hands a compact delta to the model, which separates voice edits from factual corrections and records observations to `~/.claude/wam/edits.jsonl`. A profile change is proposed only when two observations share a dimension and a direction.

**Tech Stack:** Python 3.9+ (stdlib: `json`, `difflib`, `hashlib`, `datetime`, `argparse`), pytest for dev-time tests, Markdown skill definitions.

**Spec:** `docs/superpowers/specs/2026-08-18-edit-learning-design.md`

## Global Constraints

- **Runtime dependencies: none.** Python standard library only. pytest is dev-only.
- **Python floor: 3.9.** Every module starts with `from __future__ import annotations`.
- **Explicit UTF-8 everywhere.** Every `open()`, `read_text()`, `write_text()` passes `encoding="utf-8"`. Windows defaults to cp1252.
- **No network calls** in any script under `scripts/`. Gmail access happens in the skill layer, never in Python.
- **State lives in `~/.claude/wam/`**, never in a repository.
- **Retention: 30 days.** Draft records older than that are dropped on the next review run.
- **Match threshold: 0.5** shingle Jaccard. **Rewrite threshold: 0.25.** **Promotion threshold: 2** observations sharing a dimension and direction.
- **`dimension` is a closed vocabulary** — exactly `length`, `hedging`, `opener`, `signoff`, `ask_placement`, `structure`, `punctuation`, `contractions`, `formality`, `closing_offer`. Never extended at runtime.
- **`direction`** is `reduce`, `increase`, or `replace:<value>`.
- **The fetched sent body never touches disk.** Only derived observations persist.
- Commit after every task. Never commit anything under `emails/`, `*.mbox`, `*.eml`.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `scripts/draft_log.py` | `drafts.jsonl` lifecycle: append, load, expire, status — and matching a draft to candidate sent messages |
| `scripts/diff_draft.py` | Measure draft vs. sent: structural deltas, metric deltas, sentence diff |
| `scripts/edit_log.py` | `edits.jsonl`: validated observations and the promotion rule |
| `skills/write-as-me/SKILL.md` | Write mode logs drafts; new review mode; profile updates with provenance |
| `fixtures/edit_pairs/` | Synthetic draft/sent pair with known deltas |
| `tests/test_draft_log.py`, `tests/test_diff_draft.py`, `tests/test_edit_log.py` | pytest suites |

---

## Task 1: `draft_log.py` — record, load, expire

**Files:**
- Create: `scripts/draft_log.py`
- Test: `tests/test_draft_log.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_LOG: Path` — `Path.home() / ".claude" / "wam" / "drafts.jsonl"`
  - `RETENTION_DAYS: int = 30`
  - `make_id(created: str, subject: str) -> str` → `"d-YYYYMMDD-xxxx"`
  - `record_draft(register: str, recipients: list[str], subject: str, body: str, *, created: str, path: Path) -> str` (returns the id)
  - `load_drafts(path: Path) -> list[dict]` (skips corrupt lines)
  - `set_status(draft_id: str, status: str, *, path: Path) -> None`
  - `expire_old(drafts: list[dict], now: str, retention_days: int = RETENTION_DAYS) -> list[dict]`
  - `pending(drafts: list[dict]) -> list[dict]`
  - Draft record schema: `{"id": str, "created": str, "register": str, "recipients": list[str], "subject": str, "body": str, "status": str}` where status is one of `pending`, `matched`, `expired`, `ambiguous`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_draft_log.py
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_draft_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'draft_log'`

- [ ] **Step 3: Implement**

```python
# scripts/draft_log.py
"""Record of the drafts write-as-me produced, so review mode can find them later."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_LOG = Path.home() / ".claude" / "wam" / "drafts.jsonl"
RETENTION_DAYS = 30
STATUSES = ("pending", "matched", "expired", "ambiguous")


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def make_id(created: str, subject: str) -> str:
    """Stable id from the draft's own content, so the same draft never
    produces two records and tests do not need a clock or a random source."""
    digest = hashlib.sha1(f"{created}|{subject}".encode("utf-8")).hexdigest()[:4]
    parsed = _parse(created)
    day = parsed.strftime("%Y%m%d") if parsed else "00000000"
    return f"d-{day}-{digest}"


def record_draft(
    register: str,
    recipients: list[str],
    subject: str,
    body: str,
    *,
    created: str,
    path: Path = DEFAULT_LOG,
) -> str:
    draft_id = make_id(created, subject)
    record = {
        "id": draft_id,
        "created": created,
        "register": register,
        "recipients": list(recipients),
        "subject": subject,
        "body": body,
        "status": "pending",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return draft_id


def load_drafts(path: Path = DEFAULT_LOG) -> list[dict]:
    """Corrupt lines are skipped, never raised — a damaged log must not take
    write mode down with it."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _rewrite(drafts: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(d) + "\n" for d in drafts), encoding="utf-8"
    )


def set_status(draft_id: str, status: str, *, path: Path = DEFAULT_LOG) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
    drafts = load_drafts(path)
    for draft in drafts:
        if draft.get("id") == draft_id:
            draft["status"] = status
    _rewrite(drafts, path)


def expire_old(
    drafts: list[dict], now: str, retention_days: int = RETENTION_DAYS
) -> list[dict]:
    """Drop records past retention. A draft with an unparseable date is dropped
    too: it can never be matched on a time window, so keeping it only leaves
    real draft bodies on disk indefinitely."""
    current = _parse(now)
    if current is None:
        return list(drafts)
    cutoff = current - timedelta(days=retention_days)
    kept = []
    for draft in drafts:
        created = _parse(draft.get("created", ""))
        if created is not None and created >= cutoff:
            kept.append(draft)
    return kept


def pending(drafts: list[dict]) -> list[dict]:
    return [d for d in drafts if d.get("status") == "pending"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_draft_log.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add scripts/draft_log.py tests/test_draft_log.py
git commit -m "feat: draft log with retention and corrupt-line tolerance"
```

---

## Task 2: `draft_log.py` — matching a draft to its sent message

**Files:**
- Modify: `scripts/draft_log.py`
- Modify: `scripts/ingest.py` (make `_shingles` public as `shingles`, keep the old name as an alias)
- Modify: `tests/test_draft_log.py`

**Interfaces:**
- Consumes: `load_drafts`, draft record schema from Task 1.
- Produces:
  - `ingest.shingles(text: str, size: int = 5) -> set[str]` (public; `_shingles` remains as an alias so nothing that imported it breaks)
  - `similarity(a: str, b: str) -> float` — shingle Jaccard, 0.0 when either side is empty
  - `MATCH_THRESHOLD = 0.5`, `REWRITE_THRESHOLD = 0.25`
  - `find_match(draft: dict, sent: list[dict]) -> tuple[str, list[dict]]` returning `("matched", [one])`, `("ambiguous", [two or more])`, or `("none", [])`
  - Sent-message dicts passed in are shaped `{"subject": str, "body": str, "recipients": list[str], "date": str}` — the skill layer builds these from Gmail results.

- [ ] **Step 1: Make `shingles` public in `ingest.py`**

Change the definition and add a backward-compatible alias:

```python
def shingles(text: str, size: int = 5) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) < size:
        return {" ".join(words)}
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


# Historical name, kept so existing imports keep working.
_shingles = shingles
```

Replace the body of the old `_shingles` with this. Every existing call site keeps working through the alias.

- [ ] **Step 2: Run the existing suite to confirm nothing broke**

Run: `python -m pytest tests/ -q`
Expected: all pass. If `test_ingest.py` fails on dedupe, the rename dropped behaviour — the two functions must be identical.

- [ ] **Step 3: Write the failing matching tests**

Append to `tests/test_draft_log.py`:

```python
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
```

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_draft_log.py -v -k "match or similarity or threshold"`
Expected: FAIL — `ImportError: cannot import name 'find_match'`

- [ ] **Step 5: Implement matching**

Add to `scripts/draft_log.py`:

```python
import sys

sys.path.insert(0, str(Path(__file__).parent))

from ingest import shingles  # noqa: E402

MATCH_THRESHOLD = 0.5
REWRITE_THRESHOLD = 0.25


def similarity(a: str, b: str) -> float:
    """Shingle Jaccard, the same measure dedupe() uses."""
    if not a.strip() or not b.strip():
        return 0.0
    left, right = shingles(a), shingles(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def find_match(draft: dict, sent: list[dict]) -> tuple[str, list[dict]]:
    """Find the sent message a draft became.

    Fails closed: two plausible candidates return "ambiguous" rather than a
    guess, because learning from the wrong message teaches the profile from
    someone else's writing.
    """
    created = _parse(draft.get("created", ""))
    recipients = {r.lower() for r in draft.get("recipients") or []}
    subject = (draft.get("subject") or "").strip()

    window = []
    for message in sent:
        when = _parse(message.get("date", ""))
        if created is not None and when is not None and when < created:
            continue
        if recipients:
            theirs = {r.lower() for r in message.get("recipients") or []}
            if not (recipients & theirs):
                continue
        window.append(message)

    exact = [m for m in window if (m.get("subject") or "").strip() == subject]
    if exact:
        return ("ambiguous", exact) if len(exact) > 1 else ("matched", exact)

    # No recipient means the time window is the only other filter, so the
    # fuzzy path has nothing left to disambiguate with. Require exact only.
    if not recipients:
        return ("none", [])

    near = [
        m for m in window
        if similarity(draft.get("body", ""), m.get("body", "")) >= MATCH_THRESHOLD
    ]
    if not near:
        return ("none", [])
    return ("ambiguous", near) if len(near) > 1 else ("matched", near)
```

- [ ] **Step 6: Run to verify they pass**

Run: `python -m pytest tests/test_draft_log.py -v`
Expected: 19 passed.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/draft_log.py scripts/ingest.py tests/test_draft_log.py
git commit -m "feat: match a logged draft to its sent message, failing closed on ambiguity"
```

---

## Task 3: `diff_draft.py` — measure what changed

**Files:**
- Create: `scripts/diff_draft.py`
- Create: `fixtures/edit_pairs/draft.json`, `fixtures/edit_pairs/sent.json`, `fixtures/edit_pairs/README.md`
- Test: `tests/test_diff_draft.py`

**Interfaces:**
- Consumes: `aggregate(messages, baseline)` from `fingerprint.py`; `flatten(node, prefix="")` from `eval_holdout.py`; `sentences(text)`, `opener_pattern(body)`, `closer_pattern(body)`, `paragraphs(text)` from `fingerprint.py`; `similarity` from `draft_log.py`.
- Produces:
  - `sentence_diff(draft_body: str, sent_body: str) -> dict` → `{"removed": [str], "added": [str], "changed": [[str, str]]}`
  - `structural_deltas(draft: dict, sent: dict) -> dict`
  - `metric_deltas(draft: dict, sent: dict, baseline: dict) -> dict` → flat `{metric_path: float}` of sent minus draft
  - `diff(draft: dict, sent: dict, baseline: dict) -> dict` → `{"classification": str, "similarity": float, "structural": {...}, "metrics": {...}, "sentences": {...}}` where classification is `"edited"` or `"rewritten"`
  - CLI: `python scripts/diff_draft.py --draft FILE --sent FILE --baseline FILE --out FILE`

- [ ] **Step 1: Create the fixture pair**

`fixtures/edit_pairs/draft.json` — what wam produced:

```json
{
  "subject": "Q3 rollout - confirming the date",
  "body": "Hi Priya,\n\nCan you confirm the Q3 rollout date by Thursday? We are locking the deployment window this week and the vendor contract goes out on the 15th.\n\nI just wanted to flag that staging is still on the old config.\n\nHappy to jump on a call if that is easier.\n\nBest,\nDana Reyes",
  "word_count": 58,
  "date": "2026-08-18T09:00:00-04:00",
  "to_domains": ["harborline.com"],
  "recipient_count": 1,
  "is_reply": false,
  "id": "draft-1"
}
```

`fixtures/edit_pairs/sent.json` — what the user actually sent. One hedge removed (`I just wanted to flag that` → direct), the closing offer sentence cut, and one figure corrected (15th → 18th):

```json
{
  "subject": "Q3 rollout - confirming the date",
  "body": "Hi Priya,\n\nCan you confirm the Q3 rollout date by Thursday? We are locking the deployment window this week and the vendor contract goes out on the 18th.\n\nStaging is still on the old config.\n\nBest,\nDana Reyes",
  "word_count": 42,
  "date": "2026-08-18T11:00:00-04:00",
  "to_domains": ["harborline.com"],
  "recipient_count": 1,
  "is_reply": false,
  "id": "sent-1"
}
```

`fixtures/edit_pairs/README.md` must state that both files are fictional, that they belong to the Dana Reyes persona, and list the three designed changes above, because the tests assert on them.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_diff_draft.py
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from diff_draft import (  # noqa: E402
    diff,
    metric_deltas,
    sentence_diff,
    structural_deltas,
)

ROOT = Path(__file__).parent.parent
PAIR = ROOT / "fixtures" / "edit_pairs"


def load(name):
    return json.loads((PAIR / name).read_text(encoding="utf-8"))


def baseline():
    return json.loads(
        (ROOT / "fixtures" / "baseline_ngrams.json").read_text(encoding="utf-8")
    )


def test_sentence_diff_reports_a_removed_sentence():
    result = sentence_diff("One. Two. Three.", "One. Three.")
    assert result["removed"] == ["Two."]
    assert result["added"] == []


def test_sentence_diff_reports_an_added_sentence():
    result = sentence_diff("One. Three.", "One. Two. Three.")
    assert result["added"] == ["Two."]
    assert result["removed"] == []


def test_sentence_diff_reports_a_changed_sentence_as_a_pair():
    result = sentence_diff("Ship on the 15th.", "Ship on the 18th.")
    assert result["changed"] == [["Ship on the 15th.", "Ship on the 18th."]]


def test_sentence_diff_on_the_fixture_pair_finds_the_cut_offer():
    result = sentence_diff(load("draft.json")["body"], load("sent.json")["body"])
    joined = " ".join(result["removed"])
    assert "Happy to jump on a call" in joined


def test_structural_deltas_report_the_length_cut():
    result = structural_deltas(load("draft.json"), load("sent.json"))
    assert result["word_count_delta"] < 0
    assert result["word_count_pct"] < 0
    assert result["subject_changed"] is False


def test_structural_deltas_carry_opener_and_signoff_both_sides():
    result = structural_deltas(load("draft.json"), load("sent.json"))
    assert result["opener"]["draft"] == "hi_name"
    assert result["opener"]["sent"] == "hi_name"
    assert result["signoff"]["draft"]["signoff"] == "best"
    assert result["signoff"]["sent"]["signoff"] == "best"


def test_metric_deltas_show_hedging_fell():
    result = metric_deltas(load("draft.json"), load("sent.json"), baseline())
    assert result["stance.hedges_per_100w"] < 0


def test_metric_deltas_are_sent_minus_draft():
    same = load("draft.json")
    result = metric_deltas(same, same, baseline())
    assert all(abs(v) < 1e-9 for v in result.values())


def test_diff_classifies_the_fixture_pair_as_edited():
    result = diff(load("draft.json"), load("sent.json"), baseline())
    assert result["classification"] == "edited"
    assert result["similarity"] >= 0.25


def test_diff_classifies_a_replacement_as_rewritten():
    draft = load("draft.json")
    replacement = {
        **draft,
        "body": "Priya - moving the whole conversation to a call tomorrow "
                "instead. Nothing else to report from my side this week.",
    }
    result = diff(draft, replacement, baseline())
    assert result["classification"] == "rewritten"
    assert result["similarity"] < 0.25


def test_cli_writes_a_diff_file(tmp_path):
    out = tmp_path / "diff.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diff_draft.py"),
         "--draft", str(PAIR / "draft.json"),
         "--sent", str(PAIR / "sent.json"),
         "--baseline", str(ROOT / "fixtures" / "baseline_ngrams.json"),
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"classification", "similarity", "structural",
                         "metrics", "sentences"}
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_diff_draft.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diff_draft'`

- [ ] **Step 4: Implement**

```python
# scripts/diff_draft.py
"""Measure the difference between a draft write-as-me produced and what the
user actually sent."""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from draft_log import REWRITE_THRESHOLD, similarity  # noqa: E402
from eval_holdout import flatten  # noqa: E402
from fingerprint import (  # noqa: E402
    aggregate,
    closer_pattern,
    opener_pattern,
    paragraphs,
    sentences,
)


def sentence_diff(draft_body: str, sent_body: str) -> dict:
    """Sentence-level diff.

    A removed sentence is the single most interpretable output this module
    produces — "cut 'Happy to jump on a call'" is actionable in a way that
    "bullet rate fell 0.04" is not.
    """
    before, after = sentences(draft_body), sentences(sent_body)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    removed: list[str] = []
    added: list[str] = []
    changed: list[list[str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            removed.extend(before[i1:i2])
        elif tag == "insert":
            added.extend(after[j1:j2])
        elif tag == "replace":
            old, new = before[i1:i2], after[j1:j2]
            for index in range(min(len(old), len(new))):
                changed.append([old[index], new[index]])
            removed.extend(old[len(new):])
            added.extend(new[len(old):])
    return {"removed": removed, "added": added, "changed": changed}


def structural_deltas(draft: dict, sent: dict) -> dict:
    draft_body, sent_body = draft.get("body", ""), sent.get("body", "")
    draft_words = len(draft_body.split())
    sent_words = len(sent_body.split())
    pct = ((sent_words - draft_words) / draft_words * 100) if draft_words else 0.0
    return {
        "word_count_delta": sent_words - draft_words,
        "word_count_pct": round(pct, 1),
        "sentence_count": {"draft": len(sentences(draft_body)),
                           "sent": len(sentences(sent_body))},
        "paragraph_count": {"draft": len(paragraphs(draft_body)),
                            "sent": len(paragraphs(sent_body))},
        "opener": {"draft": opener_pattern(draft_body),
                   "sent": opener_pattern(sent_body)},
        "signoff": {"draft": closer_pattern(draft_body),
                    "sent": closer_pattern(sent_body)},
        "subject_changed": (draft.get("subject") or "") != (sent.get("subject") or ""),
        "subject": {"draft": draft.get("subject", ""), "sent": sent.get("subject", "")},
    }


def metric_deltas(draft: dict, sent: dict, baseline: dict) -> dict:
    """Sent minus draft, over every scalar metric aggregate() produces."""
    before = flatten(aggregate([draft], baseline))
    after = flatten(aggregate([sent], baseline))
    return {
        key: round(after[key] - before[key], 4)
        for key in before.keys() & after.keys()
    }


def diff(draft: dict, sent: dict, baseline: dict) -> dict:
    score = similarity(draft.get("body", ""), sent.get("body", ""))
    return {
        "classification": "rewritten" if score < REWRITE_THRESHOLD else "edited",
        "similarity": round(score, 4),
        "structural": structural_deltas(draft, sent),
        "metrics": metric_deltas(draft, sent, baseline),
        "sentences": sentence_diff(draft.get("body", ""), sent.get("body", "")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff a draft against what was sent.")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--sent", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    def read(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    result = diff(read(args.draft), read(args.sent), read(args.baseline))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"{result['classification']} (similarity {result['similarity']}), "
        f"{len(result['sentences']['removed'])} sentences removed -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_diff_draft.py -v`
Expected: 11 passed. If `test_metric_deltas_show_hedging_fell` fails, check that the draft fixture's "I just wanted to flag that" is actually matching the `HEDGES` pattern in `fingerprint.py` — `just` and `wanted to` are the relevant tokens.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/diff_draft.py fixtures/edit_pairs tests/test_diff_draft.py
git commit -m "feat: measure draft-vs-sent deltas with a sentence-level diff"
```

---

## Task 4: `edit_log.py` — observations and the promotion rule

**Files:**
- Create: `scripts/edit_log.py`
- Test: `tests/test_edit_log.py`

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime.
- Produces:
  - `DEFAULT_LOG: Path` — `Path.home() / ".claude" / "wam" / "edits.jsonl"`
  - `DIMENSIONS: frozenset[str]` — exactly the ten spec values
  - `PROMOTION_THRESHOLD: int = 2`
  - `validate_observation(obs: dict) -> None` (raises `ValueError` on an unknown dimension or malformed direction)
  - `record_edit(draft_id: str, classification: str, observations: list[dict], factual_changes: list[str], *, reviewed: str, path: Path) -> None`
  - `load_edits(path: Path) -> list[dict]`
  - `promotable(edits: list[dict], threshold: int = PROMOTION_THRESHOLD) -> list[dict]` → `[{"dimension": str, "direction": str, "count": int, "evidence": [str]}]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_edit_log.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from edit_log import (  # noqa: E402
    DIMENSIONS,
    PROMOTION_THRESHOLD,
    load_edits,
    promotable,
    record_edit,
    validate_observation,
)

REVIEWED = "2026-08-19T09:14:00-04:00"


def obs(dimension="hedging", direction="reduce", evidence="removed: 'just'"):
    return {"dimension": dimension, "direction": direction, "evidence": evidence}


def test_dimension_vocabulary_is_the_spec_list():
    assert DIMENSIONS == frozenset({
        "length", "hedging", "opener", "signoff", "ask_placement",
        "structure", "punctuation", "contractions", "formality",
        "closing_offer",
    })


def test_validate_rejects_an_unknown_dimension():
    """Free-text dimensions would never match each other, so nothing would
    ever reach the promotion threshold and the loop would silently do nothing."""
    with pytest.raises(ValueError):
        validate_observation(obs(dimension="hedges"))


def test_validate_rejects_a_malformed_direction():
    with pytest.raises(ValueError):
        validate_observation(obs(direction="less"))


def test_validate_accepts_replace_with_a_value():
    validate_observation(obs(dimension="signoff", direction="replace:none"))


def test_record_and_load_round_trip(tmp_path):
    log = tmp_path / "edits.jsonl"
    record_edit("d-1", "edited", [obs()], ["figure 15th -> 18th"],
                reviewed=REVIEWED, path=log)
    edits = load_edits(log)
    assert len(edits) == 1
    assert edits[0]["draft_id"] == "d-1"
    assert edits[0]["factual_changes"] == ["figure 15th -> 18th"]
    assert edits[0]["observations"][0]["dimension"] == "hedging"


def test_record_rejects_an_invalid_observation(tmp_path):
    log = tmp_path / "edits.jsonl"
    with pytest.raises(ValueError):
        record_edit("d-1", "edited", [obs(dimension="nonsense")], [],
                    reviewed=REVIEWED, path=log)
    assert load_edits(log) == []


def test_one_observation_does_not_promote():
    edits = [{"draft_id": "d-1", "observations": [obs()]}]
    assert promotable(edits) == []


def test_two_in_the_same_direction_promote():
    edits = [
        {"draft_id": "d-1", "observations": [obs(evidence="e1")]},
        {"draft_id": "d-2", "observations": [obs(evidence="e2")]},
    ]
    result = promotable(edits)
    assert len(result) == 1
    assert result[0]["dimension"] == "hedging"
    assert result[0]["direction"] == "reduce"
    assert result[0]["count"] == 2
    assert result[0]["evidence"] == ["e1", "e2"]


def test_two_in_opposite_directions_do_not_promote():
    """A dimension the user has pushed both ways is unresolved, not learned."""
    edits = [
        {"draft_id": "d-1", "observations": [obs(direction="reduce")]},
        {"draft_id": "d-2", "observations": [obs(direction="increase")]},
        {"draft_id": "d-3", "observations": [obs(direction="reduce")]},
    ]
    assert promotable(edits) == []


def test_two_observations_from_the_same_draft_do_not_promote():
    """Two hedges cut from one email is one edit, not two independent signals."""
    edits = [{"draft_id": "d-1",
              "observations": [obs(evidence="e1"), obs(evidence="e2")]}]
    assert promotable(edits) == []


def test_promotion_threshold_is_the_spec_value():
    assert PROMOTION_THRESHOLD == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_edit_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edit_log'`

- [ ] **Step 3: Implement**

```python
# scripts/edit_log.py
"""Voice observations derived from user edits, and the rule that decides when
one becomes a profile directive."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

DEFAULT_LOG = Path.home() / ".claude" / "wam" / "edits.jsonl"
PROMOTION_THRESHOLD = 2

# Closed vocabulary. Promotion counts observations sharing a dimension and a
# direction, so free-text labels would never match each other and nothing would
# ever reach the threshold. Never extend this at runtime.
DIMENSIONS = frozenset({
    "length", "hedging", "opener", "signoff", "ask_placement",
    "structure", "punctuation", "contractions", "formality", "closing_offer",
})
DIRECTIONS = ("reduce", "increase")


def validate_observation(obs: dict) -> None:
    dimension = obs.get("dimension")
    if dimension not in DIMENSIONS:
        raise ValueError(
            f"unknown dimension {dimension!r}; expected one of {sorted(DIMENSIONS)}"
        )
    direction = obs.get("direction", "")
    if direction not in DIRECTIONS and not direction.startswith("replace:"):
        raise ValueError(
            f"bad direction {direction!r}; expected reduce, increase, or replace:<value>"
        )
    if not obs.get("evidence"):
        raise ValueError("observation needs verbatim evidence")


def record_edit(
    draft_id: str,
    classification: str,
    observations: list[dict],
    factual_changes: list[str],
    *,
    reviewed: str,
    path: Path = DEFAULT_LOG,
) -> None:
    for obs in observations:
        validate_observation(obs)
    record = {
        "draft_id": draft_id,
        "reviewed": reviewed,
        "classification": classification,
        "observations": observations,
        "factual_changes": list(factual_changes),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def load_edits(path: Path = DEFAULT_LOG) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def promotable(edits: list[dict], threshold: int = PROMOTION_THRESHOLD) -> list[dict]:
    """Dimensions supported by enough independent edits to propose a change.

    Independence is per draft: two hedges cut from one email is one signal,
    not two. A dimension the user has pushed in both directions is unresolved
    and never promotes.
    """
    drafts_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    evidence_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    directions_by_dimension: dict[str, set[str]] = defaultdict(set)

    for edit in edits:
        draft_id = edit.get("draft_id", "")
        for obs in edit.get("observations") or []:
            dimension = obs.get("dimension")
            direction = obs.get("direction")
            if dimension not in DIMENSIONS or not direction:
                continue
            pair = (dimension, direction)
            directions_by_dimension[dimension].add(direction)
            if draft_id not in drafts_by_pair[pair]:
                drafts_by_pair[pair].add(draft_id)
                evidence_by_pair[pair].append(obs.get("evidence", ""))

    out = []
    for (dimension, direction), draft_ids in sorted(drafts_by_pair.items()):
        if len(directions_by_dimension[dimension]) > 1:
            continue
        if len(draft_ids) >= threshold:
            out.append({
                "dimension": dimension,
                "direction": direction,
                "count": len(draft_ids),
                "evidence": evidence_by_pair[(dimension, direction)],
            })
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_edit_log.py -v`
Expected: 11 passed.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/edit_log.py tests/test_edit_log.py
git commit -m "feat: validated edit observations and a per-draft promotion rule"
```

---

## Task 5: Write mode logs its drafts, and the automatic check

**Files:**
- Modify: `skills/write-as-me/SKILL.md`

**Interfaces:**
- Consumes: `record_draft`, `load_drafts`, `expire_old`, `pending` from `draft_log.py`.
- Produces: a `drafts.jsonl` entry per presented draft; a one-line offer at the top of any `/wam` invocation.

- [ ] **Step 1: Add draft logging to write mode Step 5**

In `skills/write-as-me/SKILL.md`, at the end of write mode's Step 5 (Present), add:

````markdown
### Step 6 — Log the draft

After presenting, record it so review mode can find the sent version later:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --record \
  --register <REGISTER> --recipients "<COMMA SEPARATED>" \
  --subject "<SUBJECT>" --body-file <TEMP FILE> --created "<ISO-8601 NOW>"
```

Write the body to a temp file rather than passing it as an argument — draft
bodies contain newlines and quotes that do not survive a shell argument.

If the recipient was never supplied and the draft uses the `Hi [Name],`
placeholder, pass `--recipients ""`. Review mode will then require an exact
subject match, which is the safe behaviour when there is no recipient to
disambiguate with.

Logging is best-effort: if it fails, say so in one line and move on. A failed
log must never cost the user the draft they asked for.
````

- [ ] **Step 2: Add the `--record` CLI to `draft_log.py`**

```python
def main() -> int:
    ap = argparse.ArgumentParser(description="Record and inspect drafts.")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--register", default="")
    ap.add_argument("--recipients", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--body-file")
    ap.add_argument("--created", default="")
    ap.add_argument("--list-pending", action="store_true")
    ap.add_argument("--match", action="store_true")
    ap.add_argument("--draft-file", help="JSON draft record, for --match")
    ap.add_argument("--candidates-file", help="JSON list of sent messages, for --match")
    ap.add_argument("--now", default="", help="ISO-8601; drives retention")
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    log = Path(args.log)

    if args.match:
        draft = json.loads(Path(args.draft_file).read_text(encoding="utf-8"))
        candidates = json.loads(Path(args.candidates_file).read_text(encoding="utf-8"))
        status, hits = find_match(draft, candidates)
        print(json.dumps({"status": status, "candidates": hits}, indent=2))
        return 0

    if args.record:
        body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
        recipients = [r.strip() for r in args.recipients.split(",") if r.strip()]
        draft_id = record_draft(
            args.register, recipients, args.subject, body,
            created=args.created, path=log,
        )
        print(draft_id)
        return 0

    if args.list_pending:
        drafts = load_drafts(log)
        if args.now:
            kept = expire_old(drafts, args.now)
            if len(kept) != len(drafts):
                _rewrite(kept, log)
                drafts = kept
        for draft in pending(drafts):
            print(json.dumps({k: draft[k] for k in
                              ("id", "created", "register", "recipients", "subject")}))
        return 0

    ap.error("nothing to do: pass --record or --list-pending")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import argparse` to the module's imports.

- [ ] **Step 3: Write the CLI test**

Append to `tests/test_draft_log.py`:

```python
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
```

Also append a test for the match CLI, since review mode depends on it:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_draft_log.py -v`
Expected: 22 passed.

- [ ] **Step 5: Add the automatic check to the top of SKILL.md's mode routing**

Insert directly after the mode-routing table:

````markdown
## Before either mode — the pending-edit check

Run once at the start of every invocation, before doing what the user asked:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --list-pending --now "<ISO-8601 NOW>"
```

For each pending draft, check whether it has since been sent (see review mode's
matching step). If any have, say **exactly one line** and then carry on with the
user's actual request:

> 2 drafts you sent have edits I haven't learned from — review them?

Rules:
- Never block. The user asked for something; this check does not get to
  postpone it.
- If they decline, do not raise it again in this session.
- If no Gmail tools are available, say once that the edit loop cannot run
  without them, and never mention it again.
- If `drafts.jsonl` is missing or unreadable, treat it as empty and say nothing.
````

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/draft_log.py skills/write-as-me/SKILL.md tests/test_draft_log.py
git commit -m "feat: log presented drafts and offer a pending-edit review"
```

---

## Task 6: Review mode, profile updates, and docs

**Files:**
- Modify: `skills/write-as-me/SKILL.md`
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `/wam review`; profile directives tagged with provenance.

- [ ] **Step 1: Add the state files to `.gitignore`**

```gitignore
drafts.jsonl
edits.jsonl
```

These live in `~/.claude/wam/` and should never be in a repo, but a user who
copies one into the working directory to inspect it must not be able to commit
it — the same defensive reasoning as the existing `corpus.json` entry.

- [ ] **Step 2: Append review mode to `SKILL.md`**

````markdown
## Review mode

Triggered by `/wam review`, or by the user accepting the pending-edit offer.

If `~/.claude/wam/default.md` does not exist, there is nothing to update — say
so and offer analyze mode instead.

### Step 1 — Find the sent versions

List pending drafts:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --list-pending --now "<ISO-8601 NOW>"
```

For each, search `in:sent` for its subject, restricted to messages sent after
the draft's `created` timestamp and addressed to one of its recipients. Build
each candidate as `{"subject", "body", "recipients", "date"}`, write the draft
record and the candidate list to temp files, and let the matcher decide — do not
decide by eye:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --match   --draft-file <DRAFT JSON> --candidates-file <CANDIDATES JSON>
```

It prints `{"status": ..., "candidates": [...]}` where status is `matched`,
`ambiguous`, or `none`.

- `matched` — proceed.
- `ambiguous` — show the user the candidate subjects and dates and ask which,
  if any. Never pick one yourself: learning from the wrong message teaches the
  profile from someone else's writing.
- `none` — leave it `pending`. It expires on its own at 30 days. Say nothing.

### Step 2 — Measure the change

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/diff_draft.py \
  --draft <DRAFT FILE> --sent <SENT FILE> \
  --baseline ${CLAUDE_PLUGIN_ROOT}/fixtures/baseline_ngrams.json \
  --out <DIFF FILE>
```

If `classification` is `rewritten`, record it and derive nothing:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --record \
  --draft-id <ID> --classification rewritten --reviewed "<ISO-8601 NOW>"
```

Then tell the user plainly that they replaced rather than edited that draft, and
that a run of rewrites means the profile is wrong at the root — re-running
analyze mode will serve them better than incremental learning.

### Step 3 — Classify every change

Read the diff file. For each removed sentence, added sentence, changed pair, and
non-trivial metric delta, decide which of three buckets it belongs in:

- **Factual** — a number, name, date, link, or fact changed, or content added
  that you could not have known. Record it in `factual_changes`. **It never
  becomes a profile directive.** The profile describes how the user writes, not
  what they know.
- **Voice** — a hedge removed, a sentence cut with no loss of information, an
  opener or signoff changed, a length cut, a structural change.
- **Neutral** — typo fixes, whitespace, reformatting. Ignore.

A single change can be both: "the vendor contract goes out on the 15th" →
"on the 18th" is factual only, while "I just wanted to flag that staging is
still on the old config" → "Staging is still on the old config" is voice only.
Judge them separately.

### Step 4 — Record observations

Each voice change becomes one observation with a dimension from the closed
vocabulary — `length`, `hedging`, `opener`, `signoff`, `ask_placement`,
`structure`, `punctuation`, `contractions`, `formality`, `closing_offer` — a
direction of `reduce`, `increase`, or `replace:<value>`, and **verbatim
evidence**. Paraphrased evidence is worthless later: the whole point is showing
the user the actual sentence they cut.

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --record \
  --draft-id <ID> --classification edited --reviewed "<ISO-8601 NOW>" \
  --observations-file <JSON FILE> --factual-file <JSON FILE>
```

The recorder rejects a dimension outside the vocabulary. That is deliberate:
free-text labels would never match each other and nothing would ever promote.
If a change genuinely does not fit any dimension, drop it rather than inventing
a label.

### Step 5 — Propose what has earned promotion

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --promotable
```

This returns only dimensions with two or more observations from **separate
drafts** pointing the same way. Present each one on its own:

- State the proposed profile line.
- Show **both** pieces of verbatim evidence.
- If it contradicts a directive the profile measured from the corpus, say so
  and show both figures. Two edits do not silently overrule sixteen emails.
- Ask. One approval per change — never a batch yes.

### Step 6 — Apply approved changes

Edit `~/.claude/wam/default.md`, tagging every learned line with provenance:

```markdown
- Cut the closing offer sentence; you delete it. (learned from 2 edits, 2026-08-18)
```

Provenance is required. A directive resting on two edits is weaker evidence than
one resting on the whole corpus, and the profile must not present them as equal.
The tag also lets the user strip learned lines wholesale if the loop drifts.

Then mark each reviewed draft `matched`, and report: how many drafts were
reviewed, how many changes were factual, how many observations were recorded,
and how many are still short of promotion.
````

- [ ] **Step 3: Add the `edit_log.py` CLI**

```python
def main() -> int:
    ap = argparse.ArgumentParser(description="Record edits and check promotions.")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--promotable", action="store_true")
    ap.add_argument("--draft-id", default="")
    ap.add_argument("--classification", default="edited")
    ap.add_argument("--reviewed", default="")
    ap.add_argument("--observations-file")
    ap.add_argument("--factual-file")
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    log = Path(args.log)

    if args.record:
        def read_list(path: str | None) -> list:
            if not path:
                return []
            return json.loads(Path(path).read_text(encoding="utf-8"))

        record_edit(
            args.draft_id, args.classification,
            read_list(args.observations_file), read_list(args.factual_file),
            reviewed=args.reviewed, path=log,
        )
        print(f"recorded {args.classification} for {args.draft_id}")
        return 0

    if args.promotable:
        print(json.dumps(promotable(load_edits(log)), indent=2))
        return 0

    ap.error("nothing to do: pass --record or --promotable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import argparse` to the module's imports.

- [ ] **Step 4: Write the CLI test**

Append to `tests/test_edit_log.py`:

```python
import json
import subprocess


def test_record_and_promotable_cli(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "edits.jsonl"
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps([obs(evidence="cut: 'Happy to jump on a call'")]),
                        encoding="utf-8")

    for draft_id in ("d-1", "d-2"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "edit_log.py"), "--record",
             "--draft-id", draft_id, "--classification", "edited",
             "--reviewed", REVIEWED, "--observations-file", str(obs_file),
             "--log", str(log)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "edit_log.py"), "--promotable",
         "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    promoted = json.loads(result.stdout)
    assert len(promoted) == 1
    assert promoted[0]["dimension"] == "hedging"
    assert promoted[0]["count"] == 2
```

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Document the loop in `README.md`**

Add a section after the ingestion-tiers section covering, in this order: that
wam records the drafts it produces so it can learn from your edits; that it
finds the sent version by searching your sent mail and asks rather than guesses
when more than one message could be it; that only style edits update the
profile, never factual corrections; that a change needs two independent edits
before it is proposed, and every proposal is approved individually; and that
learned lines are tagged with their provenance so you can tell them from
corpus-measured ones.

The privacy paragraph must state plainly: `~/.claude/wam/drafts.jsonl` holds the
full text of drafts wam produced, is kept for 30 days and then dropped, and the
sent messages fetched for comparison are never written to disk.

- [ ] **Step 7: Commit**

```bash
git add skills/write-as-me/SKILL.md README.md .gitignore scripts/edit_log.py tests/test_edit_log.py
git commit -m "feat: review mode, provenance-tagged profile updates, and docs"
```

---

## Self-Review Notes

**Spec coverage.** Every spec section maps to a task: `drafts.jsonl` schema and
retention → Task 1; matching, thresholds, missing-recipient rule → Task 2;
`diff_draft.py` measurements, rewrite detection, fixtures → Task 3;
`edits.jsonl`, closed vocabulary, promotion rule → Task 4; write-mode logging
and the automatic check → Task 5; review mode, classification, profile
provenance, conflict rule, README, `.gitignore` → Task 6. The error-handling
table maps to: corrupt log (Task 1), ambiguous and no-match (Task 2), rewrite
(Task 3), conflicting observations (Task 4), no connector and non-blocking
check (Task 5), no profile (Task 6).

**Deviation from the spec.** The spec says an observation that fits no
dimension is "recorded under the nearest fitting dimension, or discarded".
Task 6's Step 4 instructs dropping it rather than forcing a fit, and
`validate_observation` raises rather than coercing. Forcing a poor fit
manufactures evidence toward a promotion the user never signalled — the same
failure class as write mode inventing an ask. Calling it out because a reader
comparing spec to plan will notice the difference.

**Independence rule made explicit.** The spec says "two independent
observations" without defining independence. The plan defines it as two
*separate drafts*: two hedges cut from one email is one signal. `promotable`
enforces this and `test_two_observations_from_the_same_draft_do_not_promote`
covers it.

**Type consistency.** The draft record schema from Task 1 flows unchanged into
Tasks 2, 3, and 5. `similarity` and `REWRITE_THRESHOLD` are defined in Task 2
and consumed by Task 3. `aggregate` and `flatten` are consumed with their
existing signatures and are not modified. `DIMENSIONS` is defined in Task 4 and
quoted verbatim in Task 6's instructions.
