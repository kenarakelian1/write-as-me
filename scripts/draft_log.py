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
# "expired" is deliberately not a reachable status: expire_old() below deletes
# past-retention rows outright rather than marking them, so a real draft body
# is never kept on disk past its retention window just to record that it
# expired. If a status vocabulary is ever needed for expiry, add it back
# alongside a rewrite of expire_old() to mark instead of delete.
STATUSES = ("pending", "matched", "ambiguous")

sys.path.insert(0, str(Path(__file__).parent))

from ingest import shingles  # noqa: E402
from jsonl import load_jsonl  # noqa: E402

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
    write mode down with it. Thin wrapper over jsonl.load_jsonl so this
    module's on-disk format and edit_log.py's stay identical by construction."""
    return load_jsonl(path)


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


def find_match(
    draft: dict, sent: list[dict], user_email: str | None = None
) -> tuple[str, list[dict]]:
    """Find the sent message a draft became.

    Fails closed: two plausible candidates return "ambiguous" rather than a
    guess, because learning from the wrong message teaches the profile from
    someone else's writing. Both the exact-subject route and the fuzzy-body
    route feed one shared candidate set, so a strong exact-subject hit can
    never quietly outrank — and hide — an equally plausible fuzzy hit found
    under a different subject.

    `user_email` opens one narrow carve-out. Redirecting a draft to yourself
    instead of its intended recipient is the natural way to try the feature,
    and on real mail it silently cost a genuine edit signal: the recipients
    did not overlap, so the matcher declined and the loop learned nothing.

    The carve-out is principled rather than a loosening. The recipient guard
    exists to stop the profile learning from a message someone else composed.
    A message addressed solely to the user is, by definition, the user's own
    composition, so that risk cannot arise. It stays narrow: the user must be
    the *only* recipient (a message to them and someone else is ordinary
    correspondence), the subject must match exactly, and the time window still
    applies. Callers that pass no `user_email` behave exactly as before.
    """
    created = _parse(draft.get("created", ""))
    if created is None:
        # No way to bound the candidate window without a parseable creation
        # time, so there is no time evidence to match on at all.
        return ("none", [])

    recipients = _clean_addresses(draft.get("recipients"))
    subject_cf = (draft.get("subject") or "").strip().casefold()
    self_only = _clean_addresses([user_email]) if user_email else set()

    window = []
    # Indices into `window` for messages admitted only by the self-redirect
    # carve-out. They are held to the exact-subject route alone.
    self_redirect_idx: set[int] = set()
    for message in sent:
        when = _parse(message.get("date", ""))
        if when is None or when < created:
            # An unparseable message date cannot be shown to be on or after
            # the draft's creation time, so it is excluded rather than
            # assumed in-window.
            continue
        theirs = _clean_addresses(message.get("recipients"))
        overlaps = bool(recipients & theirs) if recipients else True
        is_self_redirect = bool(self_only) and theirs == self_only
        if not overlaps and not is_self_redirect:
            continue
        if not overlaps:
            self_redirect_idx.add(len(window))
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

    # Self-redirected messages are excluded from the fuzzy route for the same
    # reason the no-recipient case is: without a recipient signal there is
    # nothing left to disambiguate a loose body match against.
    fuzzy_idx = {
        i for i, m in enumerate(window)
        if i not in self_redirect_idx
        and similarity(draft.get("body", ""), m.get("body", "")) >= MATCH_THRESHOLD
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
    ap.add_argument("--get", action="store_true",
                    help="print the full record (including body) for --draft-id")
    ap.add_argument("--set-status", action="store_true",
                    help="update the status of --draft-id to --status")
    ap.add_argument("--draft-id", default="", help="for --get and --set-status")
    ap.add_argument("--status", default="", help="for --set-status; one of STATUSES")
    ap.add_argument("--match", action="store_true")
    ap.add_argument("--draft-file", help="JSON draft record, for --match")
    ap.add_argument("--candidates-file", help="JSON list of sent messages, for --match")
    ap.add_argument("--user", default="",
                    help="The user's own address; enables the self-redirect "
                         "carve-out on --match")
    ap.add_argument("--now", default="", help="ISO-8601; drives retention")
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    log = Path(args.log)

    if args.match:
        draft = json.loads(Path(args.draft_file).read_text(encoding="utf-8"))
        candidates = json.loads(Path(args.candidates_file).read_text(encoding="utf-8"))
        status, hits = find_match(draft, candidates, user_email=args.user or None)
        print(json.dumps({"status": status, "candidates": hits}, indent=2))
        return 0

    if args.get:
        if not args.draft_id:
            ap.error("--get requires --draft-id")
        for draft in load_drafts(log):
            if draft.get("id") == args.draft_id:
                print(json.dumps(draft, indent=2))
                return 0
        print(f"error: no draft with id {args.draft_id!r}", file=sys.stderr)
        return 1

    if args.set_status:
        if not args.draft_id:
            ap.error("--set-status requires --draft-id")
        if args.status not in STATUSES:
            ap.error(f"--status must be one of {STATUSES}; got {args.status!r}")
        set_status(args.draft_id, args.status, path=log)
        print(f"{args.draft_id} -> {args.status}")
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

    ap.error("nothing to do: pass --record, --list-pending, --get, "
             "--set-status, or --match")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
