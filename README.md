# write-as-me

A Claude Code plugin that reads a person's past sent email, derives a
personalized writing-style guide, and uses that guide to draft new email in
their voice.

```
/write-as-me                       # analyze the corpus, produce a style profile
/write-as-me <what you want to say> # draft an email using the existing profile
/wam                                # short alias for both
```

The style guide is written to `~/.claude/wam/`, outside any repository, so
it is never committed by accident. Real email never enters this repo —
analysis reads from wherever the user's mail already lives, and only
redacted excerpts ever reach model context.

Design details live in `docs/superpowers/specs/2026-08-16-write-as-me-design.md`.

## Status

Early scaffolding. This repo currently contains:

- A synthetic, fully fictional 40-message fixture corpus
  (`fixtures/synthetic/`) used to test extraction logic without anyone's
  real mail.
- A modern-English n-gram frequency baseline (`fixtures/baseline_ngrams.json`)
  built from Peter Norvig's Google Web Trillion Word Corpus tables, used to
  tell a person's distinctive word choices apart from ordinary English.
- The build script for that baseline (`scripts/build_baseline.py`).

The ingest/fingerprint/redact pipeline and the `/write-as-me` skill itself
are not implemented yet — see the design spec and plan for the roadmap.

## Requirements

- Python 3.9+ on PATH. Standard library only at runtime — no `pip install`,
  no virtualenv, no lockfile. This is deliberate: a public plugin that
  requires dependency installation loses most of its would-be users at the
  first step.
- `pytest` is a dev-only dependency, used for the test suite. Install with:

  ```bash
  pip install -r requirements-dev.txt
  ```

## Running the tests

```bash
python -m pytest
```

## Repo layout

```
write-as-me/
├─ fixtures/
│  ├─ baseline_ngrams.json    # modern-English unigram/bigram frequencies
│  ├─ README.md               # baseline source + attribution
│  └─ synthetic/               # fictional 40-message fixture corpus
├─ scripts/
│  └─ build_baseline.py       # builds fixtures/baseline_ngrams.json from TSV counts
├─ tests/
│  └─ test_fixtures.py        # fixture corpus + baseline integrity checks
├─ docs/superpowers/           # design spec and implementation plan
├─ .gitignore
├─ pytest.ini
├─ requirements-dev.txt
└─ README.md
```

## A note on data

`fixtures/synthetic/` is entirely fictional. No real person's email is, or
will be, committed to this repository. See `fixtures/synthetic/README.md`
for the persona and the traits the tests depend on.
