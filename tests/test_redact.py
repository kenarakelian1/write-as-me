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
    """Belt and braces: run the real fixture corpus through and grep the output.

    Self-validating: several fixtures now plant inline PII (email, phone,
    currency) in surviving body prose (not in stripped signature blocks or
    quoted replies), spread across registers. Before asserting the redacted
    output is clean, this test first asserts the *pre-redaction* exemplars
    actually contain that PII — otherwise a future fixture change that stops
    those exemplars from being selected would make this test pass on an
    empty set instead of failing loudly.
    """
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

    pre_text = ex.read_text(encoding="utf-8")
    email_re = r"[\w.+-]+@[\w-]+\.\w+"
    phone_re = r"\+?\d[\d\s().-]{8,}\d"
    currency_re = r"\$\s?\d[\d,]*(?:\.\d{2})?\b"

    assert re.search(email_re, pre_text), (
        "no raw email address in pre-redaction exemplars.json — the sweep "
        "below would pass vacuously"
    )
    assert re.search(phone_re, pre_text), (
        "no raw phone number in pre-redaction exemplars.json — the sweep "
        "below would pass vacuously"
    )
    assert re.search(currency_re, pre_text), (
        "no raw currency amount in pre-redaction exemplars.json — the sweep "
        "below would pass vacuously"
    )

    text = red.read_text(encoding="utf-8")
    assert not re.search(email_re, text), "raw email address survived"
    assert not re.search(phone_re, text), "raw phone number survived"
    assert not re.search(currency_re, text), "raw currency amount survived"
    assert "Dana" in text, "profile owner's name should be preserved"


def test_redact_cli_creates_missing_output_directory(tmp_path):
    """Finding 1: a user without a prior ~/.claude/wam/cache/ must not hit an
    uncaught FileNotFoundError from Path.write_text on the first run."""
    root = Path(__file__).parent.parent
    src = tmp_path / "exemplars.json"
    src.write_text(json.dumps({"internal": []}), encoding="utf-8")
    out = tmp_path / "does" / "not" / "exist" / "exemplars.redacted.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "redact.py"),
         "--in", str(src), "--out", str(out), "--keep-name", "Dana"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
