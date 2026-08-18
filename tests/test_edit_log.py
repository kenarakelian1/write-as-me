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
