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
