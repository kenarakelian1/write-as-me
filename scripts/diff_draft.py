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
