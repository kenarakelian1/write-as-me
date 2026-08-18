"""Record of the drafts write-as-me produced, so review mode can find them later."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_LOG = Path.home() / ".claude" / "wam" / "drafts.jsonl"
RETENTION_DAYS = 30
STATUSES = ("pending", "matched", "expired", "ambiguous")

sys.path.insert(0, str(Path(__file__).parent))

from ingest import shingles  # noqa: E402

MATCH_THRESHOLD = 0.5
REWRITE_THRESHOLD = 0.25


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def make_id(created: str, subject: str) -> str:
    """Stable id from the draft's own content, so the same draft never
    produces two records and tests do not need a clock or a random source."""
    digest = hashlib.sha1(f"{created}|{subject}".encode("utf-8")).hexdigest()[:8]
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


def _rewrite(drafts: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(d) + "\n" for d in drafts), encoding="utf-8"
    )


def set_status(draft_id: str, status: str, *, path: Path = DEFAULT_LOG) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig").splitlines()

    updated_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if isinstance(record, dict) and record.get("id") == draft_id:
                record["status"] = status
            updated_lines.append(json.dumps(record) if isinstance(record, dict) else line)
        except json.JSONDecodeError:
            # Preserve corrupt lines
            updated_lines.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(l + "\n" for l in updated_lines), encoding="utf-8"
    )


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


def similarity(a: str, b: str) -> float:
    """Shingle Jaccard, the same measure dedupe() uses."""
    if not a.strip() or not b.strip():
        return 0.0
    left, right = shingles(a), shingles(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _clean_addresses(values) -> set[str]:
    """Lowercased, non-empty string addresses only. A None or non-string
    entry is dropped rather than raised on: a malformed recipient list must
    not crash review mode, and a dropped entry cannot spuriously widen a
    match either."""
    return {v.lower() for v in (values or []) if isinstance(v, str) and v}


def find_match(draft: dict, sent: list[dict]) -> tuple[str, list[dict]]:
    """Find the sent message a draft became.

    Fails closed: two plausible candidates return "ambiguous" rather than a
    guess, because learning from the wrong message teaches the profile from
    someone else's writing. Both the exact-subject route and the fuzzy-body
    route feed one shared candidate set, so a strong exact-subject hit can
    never quietly outrank — and hide — an equally plausible fuzzy hit found
    under a different subject.
    """
    created = _parse(draft.get("created", ""))
    if created is None:
        # No way to bound the candidate window without a parseable creation
        # time, so there is no time evidence to match on at all.
        return ("none", [])

    recipients = _clean_addresses(draft.get("recipients"))
    subject_cf = (draft.get("subject") or "").strip().casefold()

    window = []
    for message in sent:
        when = _parse(message.get("date", ""))
        if when is None or when < created:
            # An unparseable message date cannot be shown to be on or after
            # the draft's creation time, so it is excluded rather than
            # assumed in-window.
            continue
        if recipients:
            theirs = _clean_addresses(message.get("recipients"))
            if not (recipients & theirs):
                continue
        window.append(message)

    exact_idx = {
        i for i, m in enumerate(window)
        if (m.get("subject") or "").strip().casefold() == subject_cf
    }

    # No recipient means the time window is the only other filter, so the
    # fuzzy path has nothing left to disambiguate with. Require exact only.
    if not recipients:
        exact = [window[i] for i in sorted(exact_idx)]
        if not exact:
            return ("none", [])
        return ("ambiguous", exact) if len(exact) > 1 else ("matched", exact)

    fuzzy_idx = {
        i for i, m in enumerate(window)
        if similarity(draft.get("body", ""), m.get("body", "")) >= MATCH_THRESHOLD
    }

    # Union by index, not by dict equality: sent-message dicts are not
    # hashable, and two distinct messages could compare equal, so a message
    # that qualifies via both routes must still count as one candidate.
    candidate_idx = sorted(exact_idx | fuzzy_idx)
    candidates = [window[i] for i in candidate_idx]
    if not candidates:
        return ("none", [])
    return ("ambiguous", candidates) if len(candidates) > 1 else ("matched", candidates)


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
        if not args.created:
            ap.error("--record requires --created")
        if not args.body_file:
            ap.error("--record requires --body-file")
        body = Path(args.body_file).read_text(encoding="utf-8")
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
