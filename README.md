# write-as-me

A Claude Code plugin that reads a person's past sent email, derives a
personalized writing-style guide, and uses that guide to draft new email in
their voice. It runs as two slash-command modes:

```
/write-as-me                        # analyze mode: build a style profile from your sent mail
/write-as-me <what you want to say> # write mode: draft an email using the existing profile
/wam                                 # short alias for both
```

Analyze mode reads your sent mail, computes measurable traits (typical
length, sentence and paragraph shape, opener/closer patterns, contraction
rate, punctuation tics, where the "ask" lands in an email, distinctive
words and phrases relative to ordinary English), and writes them to a
Markdown profile. Write mode reads that profile and drafts new email
against it, then runs a self-check against the profile's "never do this"
list before handing you the draft. It never sends email on its own.

Everything runs on the Python standard library — no dependencies to
install, no network calls from the scripts themselves.

## Install

```
/plugin marketplace add kenarakelian1/write-as-me
/plugin install write-as-me
```

## Requirements

- **Python 3.9 or newer, on `PATH`.** The plugin has no dependency-install
  step to catch a Python version mismatch for you — if `python` on your
  machine resolves to something older than 3.9, the scripts will fail with
  a syntax error on `from __future__ import annotations` or a type-hint
  error, not a friendly message. Check with `python --version` before
  running `/write-as-me` for the first time.
- Nothing else. Runtime dependencies are the Python standard library only,
  deliberately — a public plugin that requires a `pip install` step before
  it does anything loses most of its would-be users at the first friction
  point.

## How it finds your mail: three ingestion tiers

Analyze mode tries these in order and tells you which one it used:

1. **Gmail connector.** If Gmail tools are available in your Claude Code
   session, it searches `in:sent -in:chats` over the last 12 months and
   pulls up to 150 messages directly.
2. **Local export.** It looks for `.mbox` or `.eml` files in `./emails/`
   (or asks you for a path). Google Takeout, Outlook, and Apple Mail
   exports all work — `scripts/ingest.py` accepts either `--mbox <path>`
   or `--eml-dir <path>`.
3. **Paste.** If neither of the above is available, it asks you to paste
   15–30 sent emails directly into the conversation.

Whichever tier supplies the raw messages, the same pipeline processes them:
`scripts/ingest.py` strips quoted replies and signatures and normalizes
each message to a common shape; `scripts/fingerprint.py` computes the
style metrics and buckets messages into registers (internal, client,
cold outreach, personal, vendor) when there are at least 8 messages in a
bucket; `scripts/redact.py` strips PII (emails, phone numbers, URLs,
currency amounts) from the handful of example messages that get embedded
in the profile, while preserving your own first name and the rhythm of the
original text. A corpus under 12 usable messages is refused outright,
rather than producing a profile built on too little signal.

## Privacy

Your generated profile contains excerpts of your real email, redacted but
not anonymized. It lives in `~/.claude/wam/`, outside any repository. Do
not commit or share it. The raw corpus cache is deleted after each
analysis run unless you pass `--keep-cache`.

Concretely: `ingest.py` and `fingerprint.py` write intermediate files
(`raw.json`, `corpus.json`, `fingerprint.json`, `exemplars.json`) to
`~/.claude/wam/cache/`, and the skill reads only the small,
already-redacted `fingerprint.json` and `exemplars.redacted.json` into
model context — it is instructed never to read the raw corpus files. At
the end of a run that cache directory is deleted unless you explicitly ask
to keep it. The one durable artifact is `~/.claude/wam/default.md`, the
profile itself, which by design contains a handful of real (redacted)
example emails so both you and the model can see what "in your voice"
concretely means. Nothing under `~/.claude/wam/` is ever written into a
project repository, and this repo's `.gitignore` also blocks accidental
commits of raw mail exports (`*.mbox`, `*.eml`, `emails/`, `corpus.json`,
`raw.json`).

## Evaluating whether it actually sounds like you

"Sounds like me" is falsifiable, not a vibe check. `scripts/eval_holdout.py`
compares profile-guided drafts against messages the profile was never
trained on, and against a control drafted with no profile at all, using
the same metrics `fingerprint.py` computes. It passes when the
profile-guided drafts land closer to the held-out originals than the
control does on at least 70% of compared metrics.

Procedure:

1. Run analyze mode with `--keep-cache`.
2. Move 5 messages out of `corpus.json` into `holdout.json`; re-run
   `fingerprint.py` on the remainder and regenerate the profile.
3. For each held-out message, ask `/wam` to draft from its subject plus a
   one-line intent, without showing it the original. Collect drafts into
   `drafts.json` using the corpus message shape.
4. Repeat with a fresh session and no profile loaded to build `control.json`.
5. Run `eval_holdout.py`. It exits 0 when the profile-guided drafts are
   closer to the originals than the control on at least 70% of metrics.

```bash
python scripts/eval_holdout.py \
  --holdout holdout.json \
  --profile-drafts drafts.json \
  --control-drafts control.json \
  --baseline fixtures/baseline_ngrams.json
```

It prints the verdict (`metrics_compared`, `profile_closer`, `share`,
`pass`) as JSON, plus the five metrics with the largest remaining gap
between the profile-guided drafts and the originals, and exits 1 on a
failing verdict so it can gate CI or a release checklist.

## Development

```bash
pip install -r requirements-dev.txt   # pytest only; nothing else to install
python -m pytest                      # run the full test suite
```

Repo layout:

```
write-as-me/
├─ .claude-plugin/             # plugin.json, marketplace.json
├─ commands/                   # /write-as-me and /wam command definitions
├─ skills/write-as-me/         # SKILL.md — the analyze/write mode instructions
├─ scripts/
│  ├─ ingest.py                # raw mail -> normalized corpus.json
│  ├─ fingerprint.py           # corpus.json -> style metrics + exemplars
│  ├─ redact.py                # strips PII from exemplars before they reach the profile
│  ├─ eval_holdout.py          # holdout eval harness (this task)
│  └─ build_baseline.py        # builds fixtures/baseline_ngrams.json from TSV counts
├─ fixtures/
│  ├─ baseline_ngrams.json     # modern-English unigram/bigram frequencies
│  └─ synthetic/               # fictional 40-message fixture corpus (persona: Dana Reyes)
├─ tests/                      # pytest suite for every script above
├─ pytest.ini
├─ requirements-dev.txt
└─ .gitignore                  # blocks committing raw mail exports and the wam cache
```

All runtime scripts are Python-stdlib-only, target Python 3.9+, and open
every file with an explicit `encoding="utf-8"` (Windows defaults to
cp1252, which silently corrupts non-ASCII text otherwise). `pytest` is the
only development dependency.

## What's verified and what isn't

Every script in `scripts/` — ingestion, fingerprinting, redaction, and the
eval harness — is covered by an automated test suite (`python -m pytest`,
all passing) and was additionally run end to end against the synthetic
fixture corpus during development. The two slash commands
(`/write-as-me` / `/wam`) and `/plugin marketplace add` /
`/plugin install` are interactive Claude Code entry points that could not
be exercised in a non-interactive build session — they have not been
run end to end. If something in the skill's instructions doesn't match
what the CLI scripts actually expect, that's the seam most likely to have
a rough edge; file an issue if you hit one.
