# tests/test_diff_draft.py
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from diff_draft import (  # noqa: E402
    diff,
    metric_deltas,
    sentence_diff,
    structural_deltas,
)

ROOT = Path(__file__).parent.parent
PAIR = ROOT / "fixtures" / "edit_pairs"


def load(name):
    return json.loads((PAIR / name).read_text(encoding="utf-8"))


def baseline():
    return json.loads(
        (ROOT / "fixtures" / "baseline_ngrams.json").read_text(encoding="utf-8")
    )


def test_sentence_diff_reports_a_removed_sentence():
    result = sentence_diff("One. Two. Three.", "One. Three.")
    assert result["removed"] == ["Two."]
    assert result["added"] == []


def test_sentence_diff_reports_an_added_sentence():
    result = sentence_diff("One. Three.", "One. Two. Three.")
    assert result["added"] == ["Two."]
    assert result["removed"] == []


def test_sentence_diff_reports_a_changed_sentence_as_a_pair():
    result = sentence_diff("Ship on the 15th.", "Ship on the 18th.")
    assert result["changed"] == [["Ship on the 15th.", "Ship on the 18th."]]


def test_sentence_diff_on_the_fixture_pair_finds_the_cut_offer():
    result = sentence_diff(load("draft.json")["body"], load("sent.json")["body"])
    joined = " ".join(result["removed"])
    assert "Happy to jump on a call" in joined


def test_structural_deltas_report_the_length_cut():
    result = structural_deltas(load("draft.json"), load("sent.json"))
    assert result["word_count_delta"] < 0
    assert result["word_count_pct"] < 0
    assert result["subject_changed"] is False


def test_structural_deltas_carry_opener_and_signoff_both_sides():
    result = structural_deltas(load("draft.json"), load("sent.json"))
    assert result["opener"]["draft"] == "hi_name"
    assert result["opener"]["sent"] == "hi_name"
    assert result["signoff"]["draft"]["signoff"] == "best"
    assert result["signoff"]["sent"]["signoff"] == "best"


def test_metric_deltas_show_hedging_fell():
    result = metric_deltas(load("draft.json"), load("sent.json"), baseline())
    assert result["stance.hedges_per_100w"] < 0


def test_metric_deltas_are_sent_minus_draft():
    same = load("draft.json")
    result = metric_deltas(same, same, baseline())
    assert all(abs(v) < 1e-9 for v in result.values())


def test_diff_classifies_the_fixture_pair_as_edited():
    result = diff(load("draft.json"), load("sent.json"), baseline())
    assert result["classification"] == "edited"
    assert result["similarity"] >= 0.25


def test_diff_classifies_a_replacement_as_rewritten():
    draft = load("draft.json")
    replacement = {
        **draft,
        "body": "Priya - moving the whole conversation to a call tomorrow "
                "instead. Nothing else to report from my side this week.",
    }
    result = diff(draft, replacement, baseline())
    assert result["classification"] == "rewritten"
    assert result["similarity"] < 0.25


def test_cli_writes_a_diff_file(tmp_path):
    out = tmp_path / "diff.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diff_draft.py"),
         "--draft", str(PAIR / "draft.json"),
         "--sent", str(PAIR / "sent.json"),
         "--baseline", str(ROOT / "fixtures" / "baseline_ngrams.json"),
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"classification", "similarity", "structural",
                         "metrics", "sentences"}
