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


def test_compare_only_includes_keys_present_in_both():
    a = {"m1": 0.1, "m2": 0.2}
    b = {"m1": 0.5, "m3": 0.9}
    result = compare(a, b)
    assert result == {"m1": pytest.approx(0.4)}
    assert "m2" not in result
    assert "m3" not in result


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


def test_verdict_ties_are_excluded_from_the_denominator():
    """A three-way tie (holdout, profile, control all identical) is not evidence
    against the profile — it must not count as a loss, or even as a data point."""
    profile = {"m1": 0.1, "m2": 0.0, "m3": 0.0}
    control = {"m1": 0.9, "m2": 0.0, "m3": 0.0}
    result = verdict(profile, control)
    assert result["metrics_compared"] == 3
    assert result["profile_closer"] == 1
    assert result["control_closer"] == 0
    assert result["ties"] == 2
    # Decided metrics: 1 closer, 0 opposed -> share is 1.0, not 1/3.
    assert result["share"] == 1.0
    assert result["pass"] is True


def test_verdict_all_ties_reports_no_signal_not_a_fail():
    """A harness that cannot possibly pass is worse than no harness. When every
    compared metric ties, there is no directional evidence at all — this must not
    silently resolve to pass=False (looks like a real failure) or pass=True
    (looks like a real success)."""
    profile = {"m1": 0.0, "m2": 0.0}
    control = {"m1": 0.0, "m2": 0.0}
    result = verdict(profile, control)
    assert result["metrics_compared"] == 2
    assert result["profile_closer"] == 0
    assert result["control_closer"] == 0
    assert result["ties"] == 2
    assert result["share"] is None
    assert result["pass"] is None


def test_verdict_boundary_share_exactly_at_threshold_passes():
    """share >= 0.7 must pass, including the exact boundary — and ties mixed in
    must not shift where that boundary falls."""
    profile = {f"c{i}": 0.1 for i in range(7)}
    profile.update({f"o{i}": 0.9 for i in range(3)})
    profile.update({f"t{i}": 0.5 for i in range(5)})  # ties, must not dilute share
    control = {f"c{i}": 0.9 for i in range(7)}
    control.update({f"o{i}": 0.1 for i in range(3)})
    control.update({f"t{i}": 0.5 for i in range(5)})
    result = verdict(profile, control)
    assert result["ties"] == 5
    assert result["profile_closer"] == 7
    assert result["control_closer"] == 3
    assert result["share"] == 0.7
    assert result["pass"] is True
