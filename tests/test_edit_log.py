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


def test_bom_prefixed_log_loads_records(tmp_path):
    """A UTF-8 BOM at the start of the file should not prevent loading."""
    log = tmp_path / "edits.jsonl"
    # Write a BOM-prefixed line with a valid record
    with log.open("wb") as handle:
        handle.write(b"\xef\xbb\xbf")  # UTF-8 BOM
        handle.write('{"draft_id": "d-1", "observations": [{"dimension": "hedging", "direction": "reduce", "evidence": "test"}]}\n'.encode("utf-8"))
    edits = load_edits(log)
    assert len(edits) == 1
    assert edits[0]["draft_id"] == "d-1"


def test_load_edits_skips_non_dict_json(tmp_path):
    """Non-dict JSON (scalars, arrays, null) should be skipped; only dicts are returned."""
    log = tmp_path / "edits.jsonl"
    with log.open("w", encoding="utf-8") as handle:
        handle.write('42\n')
        handle.write('"string"\n')
        handle.write('null\n')
        handle.write('[1, 2, 3]\n')
        handle.write('{"draft_id": "d-1", "observations": [{"dimension": "hedging", "direction": "reduce", "evidence": "valid"}]}\n')
        handle.write('{"draft_id": "d-2", "observations": [{"dimension": "hedging", "direction": "reduce", "evidence": "valid2"}]}\n')
    edits = load_edits(log)
    # Only the two dicts should be returned
    assert len(edits) == 2
    assert all(isinstance(e, dict) for e in edits)
    # promotable should work without crashing on non-dict entries
    result = promotable(edits)
    assert len(result) == 1


def test_record_edit_rejects_missing_draft_id(tmp_path):
    """record_edit should reject missing draft_id and write nothing."""
    log = tmp_path / "edits.jsonl"
    with pytest.raises(ValueError):
        record_edit("", "edited", [obs()], [], reviewed=REVIEWED, path=log)
    assert load_edits(log) == []


def test_record_edit_rejects_non_string_draft_id(tmp_path):
    """record_edit should reject non-string draft_id and write nothing."""
    log = tmp_path / "edits.jsonl"
    with pytest.raises(ValueError):
        record_edit(None, "edited", [obs()], [], reviewed=REVIEWED, path=log)  # type: ignore
    assert load_edits(log) == []


import json
import subprocess


def test_record_and_promotable_cli(tmp_path):
    root = Path(__file__).parent.parent
    log = tmp_path / "edits.jsonl"
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps([obs(evidence="cut: 'Happy to jump on a call'")]),
                        encoding="utf-8")

    for draft_id in ("d-1", "d-2"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "edit_log.py"), "--record",
             "--draft-id", draft_id, "--classification", "edited",
             "--reviewed", REVIEWED, "--observations-file", str(obs_file),
             "--log", str(log)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "edit_log.py"), "--promotable",
         "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    promoted = json.loads(result.stdout)
    assert len(promoted) == 1
    assert promoted[0]["dimension"] == "hedging"
    assert promoted[0]["count"] == 2


def test_record_cli_reports_a_clean_error_for_an_invalid_observation(tmp_path):
    """An unknown dimension must surface as a one-line message, not a raw
    traceback -- review mode is user-facing, and record_edit already
    guarantees nothing is written on a rejected observation."""
    root = Path(__file__).parent.parent
    log = tmp_path / "edits.jsonl"
    obs_file = tmp_path / "bad_obs.json"
    obs_file.write_text(json.dumps([obs(dimension="nonsense")]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "edit_log.py"), "--record",
         "--draft-id", "d-1", "--classification", "edited",
         "--reviewed", REVIEWED, "--observations-file", str(obs_file),
         "--log", str(log)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "unknown dimension" in result.stderr
    assert not log.exists()
