# tests/test_eval.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
