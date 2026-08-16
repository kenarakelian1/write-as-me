# tests/test_fixtures.py
from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"


def load_all():
    parser = BytesParser(policy=policy.default)
    return [parser.parsebytes(p.read_bytes()) for p in sorted(SYNTHETIC.glob("*.eml"))]


def test_corpus_size():
    assert len(list(SYNTHETIC.glob("*.eml"))) == 40


def test_every_message_is_from_dana():
    for msg in load_all():
        assert "dana@northwind-labs.com" in msg["From"]


def test_every_message_parses_with_a_body():
    for msg in load_all():
        assert msg.get_body(preferencelist=("plain",)) is not None


def test_baseline_shape():
    data = json.loads((FIXTURES / "baseline_ngrams.json").read_text(encoding="utf-8"))
    assert set(data) == {"unigrams", "bigrams"}
    assert len(data["unigrams"]) >= 5000
    assert len(data["bigrams"]) >= 5000
    assert data["unigrams"]["the"] > data["unigrams"].get("nevertheless", 0)


def test_baseline_is_modern_english():
    """A literary-prose baseline would rank ordinary business words as
    distinctive. Common workplace vocabulary must be present and non-trivial."""
    data = json.loads((FIXTURES / "baseline_ngrams.json").read_text(encoding="utf-8"))
    for word in ("email", "online", "website", "meeting"):
        assert data["unigrams"].get(word, 0) > 0, f"{word} missing from baseline"
