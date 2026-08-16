# tests/test_fingerprint.py
from __future__ import annotations

import json
import subprocess
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
from fingerprint import aggregate, classify_register, select_exemplars  # add to imports
from fingerprint import assign_registers  # add to imports

USER_DOMAIN = "northwind-labs.com"


# classify_register no longer infers first-contact from is_reply/subject — that
# conflated "the subject line happens to start with Re:" with "we have an
# established relationship with this recipient", which is not what the design
# spec means by cold_outreach ("no prior thread from that address"). Whether a
# message is first contact is now computed once, corpus-wide, by
# assign_registers() and passed in explicitly.
def test_classify_internal():
    msg = {"to_domains": ["northwind-labs.com"], "is_reply": True, "body": "x"}
    assert classify_register(msg, USER_DOMAIN, is_first_contact=False) == "internal"


def test_classify_personal_consumer_domain():
    msg = {"to_domains": ["gmail.com"], "is_reply": False, "body": "x"}
    assert classify_register(msg, USER_DOMAIN, is_first_contact=True) == "personal"


def test_classify_cold_outreach_is_first_contact():
    msg = {"to_domains": ["harborline.com"], "is_reply": False, "body": "x"}
    assert classify_register(msg, USER_DOMAIN, is_first_contact=True) == "cold_outreach"


def test_classify_client_is_established_contact():
    msg = {"to_domains": ["harborline.com"], "is_reply": False, "body": "x"}
    assert classify_register(msg, USER_DOMAIN, is_first_contact=False) == "client"


def test_assign_registers_second_message_to_seen_domain_is_client():
    msgs = [
        {"id": "1", "date": "2025-01-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Kickoff", "body": "x"},
        {"id": "2", "date": "2025-02-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Follow-up", "body": "x"},
    ]
    result = assign_registers(msgs, USER_DOMAIN)
    assert result["1"] == "cold_outreach"
    assert result["2"] == "client"


def test_assign_registers_first_message_to_new_domain_is_cold_outreach():
    msgs = [
        {"id": "1", "date": "2025-01-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Intro", "body": "x"},
    ]
    result = assign_registers(msgs, USER_DOMAIN)
    assert result["1"] == "cold_outreach"


def test_assign_registers_mixed_new_and_established_domain_is_client():
    msgs = [
        {"id": "1", "date": "2025-01-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Intro", "body": "x"},
        {"id": "2", "date": "2025-02-01T00:00:00",
         "to_domains": ["harborline.com", "brand-new.com"],
         "is_reply": False, "subject": "Update plus new stakeholder", "body": "x"},
    ]
    result = assign_registers(msgs, USER_DOMAIN)
    assert result["1"] == "cold_outreach"
    assert result["2"] == "client"


def test_assign_registers_uses_chronological_order_not_list_order():
    # Listed with the later message first; chronological order must still
    # decide which one counts as first contact.
    msgs = [
        {"id": "later", "date": "2025-03-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Follow-up", "body": "x"},
        {"id": "earlier", "date": "2025-01-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Intro", "body": "x"},
    ]
    result = assign_registers(msgs, USER_DOMAIN)
    assert result["earlier"] == "cold_outreach"
    assert result["later"] == "client"


def test_assign_registers_empty_date_sorts_last():
    # A message with no parseable date can't be placed in time, so it must
    # never be allowed to claim first-contact status ahead of a dated message
    # to the same domain.
    msgs = [
        {"id": "undated", "date": "", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Undated", "body": "x"},
        {"id": "dated", "date": "2025-01-01T00:00:00", "to_domains": ["harborline.com"],
         "is_reply": False, "subject": "Intro", "body": "x"},
    ]
    result = assign_registers(msgs, USER_DOMAIN)
    assert result["dated"] == "cold_outreach"
    assert result["undated"] == "client"


def test_select_exemplars_prefers_median_length_with_an_ask():
    msgs = [
        {"subject": "a", "body": "tiny", "word_count": 1},
        {"subject": "b", "body": "Can you confirm the date? " + "word " * 40,
         "word_count": 45},
        {"subject": "c", "body": "word " * 400, "word_count": 400},
    ]
    picked = select_exemplars(msgs, count=1)
    assert picked[0]["subject"] == "b"


def test_select_exemplars_respects_count():
    msgs = [
        {"subject": str(i), "body": "Can you confirm? " + "word " * 30,
         "word_count": 33}
        for i in range(10)
    ]
    assert len(select_exemplars(msgs, count=4)) == 4


def test_fingerprint_cli_on_synthetic_corpus(tmp_path):
    root = Path(__file__).parent.parent
    corpus = tmp_path / "corpus.json"
    subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(root / "fixtures" / "synthetic"),
         "--user", "dana@northwind-labs.com", "--out", str(corpus)],
        check=True, capture_output=True,
    )
    fp = tmp_path / "fingerprint.json"
    ex = tmp_path / "exemplars.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "fingerprint.py"),
         "--corpus", str(corpus),
         "--baseline", str(root / "fixtures" / "baseline_ngrams.json"),
         "--out", str(fp), "--exemplars", str(ex)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(fp.read_text(encoding="utf-8"))

    # Dana's designed traits must be recovered from the data
    assert data["baseline"]["shape"]["words_per_email"]["median"] < 120
    assert "internal" in data["registers"]
    assert data["baseline"]["punctuation"]["em_dash"] > 0
    phrases = [item["phrase"] for item in data["baseline"]["lexicon"]]
    assert any("worth" in p for p in phrases)

    exemplars = json.loads(ex.read_text(encoding="utf-8"))
    assert exemplars["internal"]


def test_fingerprint_cli_creates_missing_output_directories(tmp_path):
    """Finding 1: a user without a prior ~/.claude/wam/cache/ must not hit an
    uncaught FileNotFoundError from Path.write_text on the first run — for
    both --out and --exemplars, which are written to separately."""
    root = Path(__file__).parent.parent
    corpus = tmp_path / "corpus.json"
    subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(root / "fixtures" / "synthetic"),
         "--user", "dana@northwind-labs.com", "--out", str(corpus)],
        check=True, capture_output=True,
    )
    fp = tmp_path / "does" / "not" / "exist" / "fingerprint.json"
    ex = tmp_path / "also" / "missing" / "exemplars.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "fingerprint.py"),
         "--corpus", str(corpus),
         "--baseline", str(root / "fixtures" / "baseline_ngrams.json"),
         "--out", str(fp), "--exemplars", str(ex)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert fp.exists()
    assert ex.exists()


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


# --- Consumer-domain users (defect found on real Gmail data) ---


def test_consumer_domain_user_has_no_internal_register():
    """A user whose own domain is gmail.com has no colleagues at gmail.com.
    Treating every Gmail recipient as `internal` swallows the whole corpus and
    makes `personal` unreachable — which is exactly what happened on real data."""
    msg = {"to_domains": ["gmail.com"], "is_reply": False, "body": "x", "subject": ""}
    assert classify_register(msg, "gmail.com", True) == "personal"


def test_consumer_domain_user_still_classifies_business_mail():
    msg = {"to_domains": ["acme.com"], "is_reply": False, "body": "x", "subject": ""}
    assert classify_register(msg, "gmail.com", True) == "cold_outreach"
    assert classify_register(msg, "gmail.com", False) == "client"


def test_cc_to_a_consumer_domain_does_not_hijack_the_register():
    """A business message that CCs one Gmail address is still business mail."""
    msg = {"to_domains": ["codediv.com", "gmail.com"], "is_reply": False,
           "body": "x", "subject": ""}
    assert classify_register(msg, "gmail.com", False) == "client"


def test_corporate_domain_user_keeps_internal_register():
    msg = {"to_domains": ["northwind-labs.com"], "is_reply": True, "body": "x",
           "subject": ""}
    assert classify_register(msg, "northwind-labs.com", False) == "internal"


# --- Lexicon must not be dominated by contractions ---


def test_contractions_do_not_dominate_the_lexicon():
    """The frequency baseline holds no apostrophe forms, so every contraction
    scored against the smoothing floor and ranked as maximally distinctive.
    "it's" should be scored against "its", not against nothing."""
    baseline = {
        "unigrams": {"its": 0.004, "cant": 0.0005, "worth": 0.0000001},
        # Every bigram present, so bigram scoring cannot mask the unigram
        # behaviour under test.
        "bigrams": {"its worth": 0.002, "worth it": 0.002, "it cant": 0.002},
    }
    msgs = [{"body": "it's worth it can't"} for _ in range(5)]
    ranked = lexicon(msgs, baseline, top_n=3)
    phrases = [x["phrase"] for x in ranked]
    assert "worth" in phrases, f"real pet phrase crowded out by contractions: {phrases}"
    assert "it's" not in phrases, f"contraction still ranking as distinctive: {phrases}"
