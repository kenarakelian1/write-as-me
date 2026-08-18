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
