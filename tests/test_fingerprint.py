# tests/test_fingerprint.py
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fingerprint import (  # noqa: E402
    ask_placement,
    closer_pattern,
    contraction_rate,
    opener_pattern,
    paragraphs,
    punct_rates,
    sentences,
    shape_metrics,
    stance,
)
from fingerprint import lexicon  # add to the import block


def test_sentences_splits_on_terminators():
    assert sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_sentences_ignores_common_abbreviations():
    assert len(sentences("Meet Dr. Webb at 5 p.m. tomorrow.")) == 1


def test_paragraphs_split_on_blank_lines():
    assert paragraphs("A\nB\n\nC") == ["A\nB", "C"]


def test_shape_metrics_median():
    msgs = [{"body": "one two three"}, {"body": "one two"}, {"body": "one"}]
    assert shape_metrics(msgs)["words_per_email"]["median"] == 2


def test_opener_patterns():
    assert opener_pattern("Hi Priya,\n\nBody here.") == "hi_name"
    assert opener_pattern("Hey Marcus -\n\nBody.") == "hey_name"
    assert opener_pattern("Priya —\n\nBody.") == "name_dash"
    assert opener_pattern("Priya,\n\nBody.") == "bare_name"
    assert opener_pattern("Pushed the fix.") == "none"


def test_closer_pattern():
    result = closer_pattern("Body text.\n\nBest,\nDana Reyes")
    assert result["signoff"] == "best"
    assert result["name_form"] == "full_name"

    result = closer_pattern("Body text.\n\n— Dana")
    assert result["signoff"] == "none"
    assert result["name_form"] == "first_name"


def test_contraction_rate():
    assert contraction_rate("I don't think we can't win") == 1.0
    assert contraction_rate("I do not think it") == 0.0


def test_punct_rates_per_100_words():
    text = " ".join(["word"] * 100) + " — !"
    rates = punct_rates(text)
    assert rates["em_dash"] == 1.0
    assert rates["exclamation"] == 1.0


def test_stance_detects_hedges_and_questions():
    result = stance("I just think maybe we should wait. Can you confirm?")
    assert result["hedges_per_100w"] > 0
    assert result["question_rate"] == 0.5


def test_ask_placement_front_vs_back():
    front = "Can you confirm by Thursday? The rest is context. More context here."
    back = "Here is context. More context follows. Can you confirm by Thursday?"
    assert ask_placement(front) < 0.5
    assert ask_placement(back) > 0.5
    assert ask_placement("No request in this text at all.") is None


def test_lexicon_surfaces_distinctive_phrases():
    """Every word in the sample must appear in the baseline except the
    distinctive ones. An absent word scores near-infinite log-odds against the
    smoothing floor, which would drown out the phrase under test."""
    baseline = {
        "unigrams": {
            "the": 0.05, "a": 0.03, "at": 0.02, "numbers": 0.001,
            "worth": 0.0000001, "look": 0.0000002,
        },
        "bigrams": {
            "at the": 0.002, "the numbers": 0.001, "a look": 0.0009,
            "look at": 0.002, "numbers worth": 0.0005,
            "worth a": 0.0000001,
        },
    }
    msgs = [{"body": "worth a look at the numbers"} for _ in range(10)]
    phrases = [item["phrase"] for item in lexicon(msgs, baseline, top_n=4)]
    assert "worth" in phrases
    assert "the" not in phrases


def test_lexicon_bigrams_do_not_cross_message_boundaries():
    """A bigram must never be formed from the last word of one message and
    the first word of the next, even when it recurs across many messages —
    e.g. a signoff ("...Dana Reyes") directly followed by the next email's
    greeting ("Hi Priya...") must never surface "reyes hi" as a phrase."""
    baseline = {"unigrams": {}, "bigrams": {}}
    msgs = []
    for _ in range(3):
        msgs.append({"body": "Thanks, best reyes"})
        msgs.append({"body": "Hi priya, following up"})
    phrases = [item["phrase"] for item in lexicon(msgs, baseline, top_n=50)]
    assert "reyes hi" not in phrases


def test_ask_placement_paragraph_split_avoids_greeting_fusion():
    """sentences() has no terminator to split on after a bare greeting line,
    so splitting the raw body directly fuses "Hi Priya," into sentence[0]
    with the ask that immediately follows it, pinning the result at 0.0
    regardless of where the ask actually sits. Splitting into paragraphs
    first (like shape_metrics() does) keeps the greeting as its own unit,
    so a two-unit email (greeting, then ask) correctly reports 0.5 rather
    than collapsing to a single fused unit at 0.0."""
    text = "Hi Priya,\n\nCan you confirm by Thursday?"
    assert ask_placement(text) == 0.5


def test_ask_placement_detects_bare_imperative():
    """A directive with no question mark and no politeness marker ("Need the
    client deck by noon", "Move the travel line...") is still an ask."""
    assert ask_placement("Need the client deck by noon.") == 0.0
    assert ask_placement("Move the travel line into professional services.") == 0.0


def test_ask_placement_ignores_hyphenated_declaratives():
    """IMPERATIVE_START's word boundary fires before a hyphen, so a plain
    declarative like "Need-to-know basis applies here." or "Check-ins are
    weekly now." must not be mistaken for an imperative ask just because it
    starts with a hyphenated word whose prefix happens to be a verb in the
    closed list."""
    assert ask_placement("Need-to-know basis applies here.") is None
    assert ask_placement("Check-ins are weekly now.") is None
