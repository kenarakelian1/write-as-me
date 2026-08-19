# scripts/diff_draft.py
"""Measure the difference between a draft write-as-me produced and what the
user actually sent."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

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


# Floor for pairing two sentences inside a difflib "replace" block as a
# "changed" pair, on lowercased word-set Jaccard similarity. Below this, the
# old sentence is a removal and the new sentence is an addition rather than
# a fabricated pairing: difflib's replace opcode only tells us a block of
# old sentences was swapped for a block of new ones, not which old sentence
# corresponds to which new one, so pairing by position alone can marry two
# unrelated sentences whenever a reorder coincides with an edit. Wrongly
# calling something "removed" and "added" is recoverable by a downstream
# reader; a wrong pairing masquerading as one edited sentence is not.
PAIR_SIMILARITY_FLOOR = 0.3


def _word_set(sentence: str) -> set[str]:
    return set(sentence.lower().split())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# A mail client is not an editor. Gmail rewraps lines on send and rewrites bare
# URLs into click-tracking redirects, so a naive comparison reports both as
# edits the user never made. On the first real round-trip through this pipeline,
# three of the four detected "changes" were artifacts of exactly these two
# behaviours, and only one was a genuine edit. Normalizing them away is
# deterministic; leaving them in asks a model to sift noise that never had to
# reach it.
GMAIL_TRACKING_URL = re.compile(r"https?://(?:www\.)?google\.com/url\?q=([^&\s]+)\S*")
LIST_ITEM = re.compile(r"^([-*•]|\d+[.)])\s")


def unwrap_tracking_urls(text: str) -> str:
    """Recover the target of a Gmail click-tracking redirect."""
    return GMAIL_TRACKING_URL.sub(lambda m: unquote(m.group(1)), text)


def normalize_wrapping(text: str) -> str:
    """Join lines a mail client soft-wrapped, without flattening structure.

    Paragraph breaks survive, and so does any line that begins a list item —
    collapsing those would merge a bulleted list onto one line and silently
    zero out the bullet_rate metric.
    """
    out_paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        lines: list[str] = []
        for raw in paragraph.split("\n"):
            stripped = raw.strip()
            if not stripped:
                continue
            if not lines or LIST_ITEM.match(stripped):
                lines.append(stripped)
            else:
                lines[-1] = f"{lines[-1]} {stripped}"
        out_paragraphs.append("\n".join(lines))
    return "\n\n".join(out_paragraphs)


# Gmail also supplies a scheme the user never typed: a bare "github.com/x" comes
# back as "http://github.com/x" inside the redirect. For edit detection the two
# are the same link, so the scheme is dropped on both sides. This applies only to
# text being compared, never to anything shown to the user.
URL_SCHEME = re.compile(r"\bhttps?://")


def _for_comparison(body: str) -> str:
    return normalize_wrapping(URL_SCHEME.sub("", unwrap_tracking_urls(body)))


def sentence_diff(draft_body: str, sent_body: str) -> dict:
    """Sentence-level diff.

    A removed sentence is the single most interpretable output this module
    produces — "cut 'Happy to jump on a call'" is actionable in a way that
    "bullet rate fell 0.04" is not.
    """
    # Normalization is scoped to the sentence diff on purpose. structural_deltas
    # reads raw line structure — closer_pattern inspects the last two lines to
    # tell "Best,\nDana Reyes" from a bare signoff — so normalizing there would
    # break signoff detection.
    before = sentences(_for_comparison(draft_body))
    after = sentences(_for_comparison(sent_body))
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
            new_sets = [_word_set(s) for s in new]
            used_new: set[int] = set()
            for old_sentence in old:
                old_set = _word_set(old_sentence)
                best_j = None
                best_score = 0.0
                for j, new_set in enumerate(new_sets):
                    if j in used_new:
                        continue
                    score = _jaccard(old_set, new_set)
                    if score > best_score:
                        best_score = score
                        best_j = j
                if best_j is not None and best_score >= PAIR_SIMILARITY_FLOOR:
                    changed.append([old_sentence, new[best_j]])
                    used_new.add(best_j)
                else:
                    removed.append(old_sentence)
            added.extend(new[j] for j in range(len(new)) if j not in used_new)
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
    """Sent minus draft, over every scalar metric present on both sides.

    A metric absent from one side (e.g. a message with no ask has no
    ask_placement_median at all, not an ask_placement_median of 0) is not
    comparable as a delta — see metrics_one_sided() for those.
    """
    before = flatten(aggregate([draft], baseline))
    after = flatten(aggregate([sent], baseline))
    return {
        key: round(after[key] - before[key], 4)
        for key in before.keys() & after.keys()
    }


def metrics_one_sided(draft: dict, sent: dict, baseline: dict) -> dict:
    """Metrics that exist on only one side, verbatim, nothing fabricated.

    Defaulting an absent metric to 0.0 would invent a signal — e.g. reporting
    "no ask at all" as "ask moved to position 0.0". Instead each one-sided
    metric reports both raw values, with the missing side as None/null so a
    consumer can tell "went from 0.71 to no ask at all" from "went from 0.71
    to 0.2".
    """
    before = flatten(aggregate([draft], baseline))
    after = flatten(aggregate([sent], baseline))
    return {
        key: {"draft": before.get(key), "sent": after.get(key)}
        for key in before.keys() ^ after.keys()
    }


def diff(draft: dict, sent: dict, baseline: dict) -> dict:
    score = similarity(draft.get("body", ""), sent.get("body", ""))
    return {
        "classification": "rewritten" if score < REWRITE_THRESHOLD else "edited",
        "similarity": round(score, 4),
        "structural": structural_deltas(draft, sent),
        "metrics": metric_deltas(draft, sent, baseline),
        "metrics_one_sided": metrics_one_sided(draft, sent, baseline),
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
