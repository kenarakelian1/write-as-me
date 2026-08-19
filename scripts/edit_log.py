"""Voice observations derived from user edits, and the rule that decides when
one becomes a profile directive."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from jsonl import load_jsonl  # noqa: E402

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
    if not isinstance(draft_id, str) or not draft_id:
        raise ValueError(
            f"draft_id must be a non-empty string; got {draft_id!r}"
        )
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
    """Thin wrapper over jsonl.load_jsonl so this module's on-disk format and
    draft_log.py's stay identical by construction, rather than by two
    hand-copied implementations drifting apart."""
    return load_jsonl(path)


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

        try:
            record_edit(
                args.draft_id, args.classification,
                read_list(args.observations_file), read_list(args.factual_file),
                reviewed=args.reviewed, path=log,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"recorded {args.classification} for {args.draft_id}")
        return 0

    if args.promotable:
        print(json.dumps(promotable(load_edits(log)), indent=2))
        return 0

    ap.error("nothing to do: pass --record or --promotable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
