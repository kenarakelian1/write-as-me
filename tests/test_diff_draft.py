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
    metrics_one_sided,
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


def test_sentence_diff_does_not_marry_unrelated_sentences_on_reorder_plus_edit():
    # Reviewer-reported case: a reorder that coincides with an edit on both
    # sides must not pair sentences positionally within the replace block.
    draft_body = "Cats are great animals. Dogs need long walks daily."
    sent_body = "Dogs need long walks daily and treats. Cats are wonderful animals."
    result = sentence_diff(draft_body, sent_body)
    assert result["changed"] == [
        ["Cats are great animals.", "Cats are wonderful animals."],
        ["Dogs need long walks daily.", "Dogs need long walks daily and treats."],
    ]
    assert result["removed"] == []
    assert result["added"] == []


def test_sentence_diff_sends_an_unmatched_sentence_to_removed_and_added():
    # No candidate on either side clears the similarity floor for one of the
    # pairs, so it must not be forced into a "changed" pairing.
    draft_body = "Alpha bravo charlie. Delta echo foxtrot."
    sent_body = "Alpha bravo charlie modified. Completely different unrelated sentence."
    result = sentence_diff(draft_body, sent_body)
    assert result["changed"] == [["Alpha bravo charlie.", "Alpha bravo charlie modified."]]
    assert result["removed"] == ["Delta echo foxtrot."]
    assert result["added"] == ["Completely different unrelated sentence."]


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


def test_metrics_one_sided_reports_an_opener_category_present_on_only_one_side():
    draft = {"subject": "Status", "body": "Dana -\n\nThe report is finished."}
    sent = {"subject": "Status", "body": "Hi Priya,\n\nThe report is finished."}
    result = metrics_one_sided(draft, sent, baseline())
    assert result["openers.name_dash"] == {"draft": 1.0, "sent": None}
    assert result["openers.hi_name"] == {"draft": None, "sent": 1.0}
    intersection = metric_deltas(draft, sent, baseline())
    assert "openers.name_dash" not in intersection
    assert "openers.hi_name" not in intersection


def test_metrics_one_sided_reports_ask_placement_present_on_only_one_side():
    draft = {
        "subject": "Status",
        "body": "The report is finished. Everything looks good on our end.",
    }
    sent = {
        "subject": "Status",
        "body": "Can you confirm receipt by Friday? Everything looks good on our end.",
    }
    result = metrics_one_sided(draft, sent, baseline())
    assert result["ask_placement_median"] == {"draft": None, "sent": 0.0}
    assert "ask_placement_median" not in metric_deltas(draft, sent, baseline())


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


def test_mixed_fixture_pairs_the_hedge_and_the_figure_into_one_changed_entry():
    """draft_mixed.json / sent_mixed.json fold a hedge cut and a factual
    correction into a single sentence. diff_draft.py must keep that sentence
    as one `changed` pair (not split it into removed/added), so downstream
    review-mode classification has to split the content of one pair into
    both buckets rather than assuming a changed pair carries one verdict."""
    result = diff(load("draft_mixed.json"), load("sent_mixed.json"), baseline())
    assert result["classification"] == "edited"
    sentences = result["sentences"]
    assert sentences["removed"] == []
    assert sentences["added"] == []
    assert len(sentences["changed"]) == 1
    before, after = sentences["changed"][0]
    assert "I just wanted to flag that" in before
    assert "$4,200" in before
    assert "I just wanted to flag that" not in after
    assert "$4,250" in after
    assert "$4,200" not in after


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
                         "metrics", "metrics_one_sided", "sentences"}
