# tests/test_redact.py
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from redact import redact  # noqa: E402


def test_redacts_email_addresses():
    assert "priya@harborline.com" not in redact("Ping priya@harborline.com today")
    assert "[EMAIL]" in redact("Ping priya@harborline.com today")


def test_redacts_phone_numbers():
    assert "[PHONE]" in redact("Call +1 555 018 2299 tomorrow")


def test_redacts_urls():
    assert "[URL]" in redact("See https://harborline.com/deck for details")


def test_redacts_currency():
    assert "[$AMOUNT]" in redact("The contract is $47,500 for the year")


def test_preserves_the_users_own_first_name():
    assert "Dana" in redact("Thanks,\nDana", keep_names={"Dana"})


def test_preserves_dates_and_weekdays():
    out = redact("Can you confirm by Thursday, April 17?")
    assert "Thursday" in out and "April" in out


def test_preserves_length_within_tolerance():
    """Rhythm is what we're modeling — redaction must replace, not delete."""
    original = "Hi Priya, the invoice for $4,200 goes to priya@harborline.com today."
    ratio = len(redact(original)) / len(original)
    assert 0.7 < ratio < 1.4


def test_no_raw_emails_survive_full_pipeline(tmp_path):
    """Belt and braces: run the real fixture corpus through and grep the output."""
    root = Path(__file__).parent.parent
    corpus, fp = tmp_path / "corpus.json", tmp_path / "fp.json"
    ex, red = tmp_path / "ex.json", tmp_path / "red.json"

    subprocess.run(
        [sys.executable, str(root / "scripts" / "ingest.py"),
         "--eml-dir", str(root / "fixtures" / "synthetic"),
         "--user", "dana@northwind-labs.com", "--out", str(corpus)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(root / "scripts" / "fingerprint.py"),
         "--corpus", str(corpus),
         "--baseline", str(root / "fixtures" / "baseline_ngrams.json"),
         "--out", str(fp), "--exemplars", str(ex)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(root / "scripts" / "redact.py"),
         "--in", str(ex), "--out", str(red), "--keep-name", "Dana"],
        check=True, capture_output=True,
    )
    text = red.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), "raw email address survived"
    assert not re.search(r"\+?\d[\d\s().-]{8,}\d", text), "raw phone number survived"
    assert "Dana" in text, "profile owner's name should be preserved"
