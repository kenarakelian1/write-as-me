---
name: write-as-me
description: Use when the user wants email written in their own voice, wants to analyze their writing style, or asks to build or refresh a personal style profile. Triggers on "write as me", "in my voice", "sounds like me", "draft this email", "/wam".
---

# write-as-me

Two modes. Pick by whether the user supplied an intent.

| Invocation | Mode |
| --- | --- |
| `/write-as-me` or `/wam`, no arguments | **Analyze** — build the style profile |
| `/write-as-me <what to say>` | **Write** — draft using the existing profile |
| `--refresh` present | **Analyze**, overwriting the existing profile |

Profiles live in `~/.claude/wam/`. Never write a profile into a repository.

All scripts and fixtures this skill uses live inside the plugin, not the user's
working directory. The environment variable `${CLAUDE_PLUGIN_ROOT}` always points at
this plugin's root. Every command below that touches `scripts/` or `fixtures/` MUST
be prefixed with `${CLAUDE_PLUGIN_ROOT}` — never invoke them as a bare relative path
like `scripts/ingest.py`, because the working directory at run time is the user's
project, not this plugin.

## Analyze mode

If `~/.claude/wam/default.md` already exists and `--refresh` was not passed, tell the
user it exists, show its metadata line, and ask whether to refresh or switch to write
mode. Do not silently overwrite.

### Step 1 — Find the mail

Try in order and announce which tier you used.

**Tier 1, Gmail connector.** If Gmail tools are available, search `in:sent -in:chats`
over the last 12 months. Fetch up to 150 messages. Write them to
`~/.claude/wam/cache/raw.json` as a JSON array of
`{id, from, to, cc, subject, date, body}`.

**Tier 2, local export.** Look for `.mbox` or `.eml` files in `./emails/`. If nothing
is there, ask the user for a path. Google Takeout, Outlook, and Apple Mail exports all
work.

**Tier 3, paste.** Ask the user to paste 15–30 sent emails. Write them into the same
`raw.json` shape.

Ask for the user's own email address if you cannot infer it from the data.

### Step 2 — Run the pipeline

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/ingest.py" --json ~/.claude/wam/cache/raw.json \
  --user <EMAIL> --out ~/.claude/wam/cache/corpus.json

python "${CLAUDE_PLUGIN_ROOT}/scripts/fingerprint.py" --corpus ~/.claude/wam/cache/corpus.json \
  --baseline "${CLAUDE_PLUGIN_ROOT}/fixtures/baseline_ngrams.json" \
  --out ~/.claude/wam/cache/fingerprint.json \
  --exemplars ~/.claude/wam/cache/exemplars.json

python "${CLAUDE_PLUGIN_ROOT}/scripts/redact.py" --in ~/.claude/wam/cache/exemplars.json \
  --out ~/.claude/wam/cache/exemplars.redacted.json --keep-name <FIRST NAME>
```

Use `--eml-dir <path>` or `--mbox <path>` instead of `--json` for Tier 2 — still
invoke the script itself as `python "${CLAUDE_PLUGIN_ROOT}/scripts/ingest.py"`.

If `fingerprint.py` exits non-zero with a corpus-size error, relay its message
verbatim and stop. Do not generate a profile from fewer than 12 messages.

### Step 3 — Read the small artifacts

Read `fingerprint.json` and `exemplars.redacted.json`. **Never read `corpus.json` or
`raw.json`** — they hold the full unredacted corpus and will flood context.

### Step 4 — Verify the redaction

Scan the redacted exemplars for anything the regexes missed: person names in the body,
company names, project code names, account numbers. Replace with `[FIRST]`,
`[COMPANY]`, `[PROJECT]`. Keep the owner's own first name in signoffs.

Never present an exemplar you have not personally checked.

### Step 5 — Write the profile

Write `~/.claude/wam/default.md` in the exact structure below. This is the artifact
the user reads to internalize their own style and the artifact write-mode reads to
draft with, so every line must be a rule, not a mood.

**The failure mode to avoid**: a profile that says "professional and friendly," "clear
and concise," or "warm but efficient" is worthless — it describes every email ever
written. If a line you're about to write could apply to a stranger's inbox without
changes, delete it and replace it with the number that makes it specific to *this*
corpus.

Rules for the prose:
- **Directives, not description.** "Median 68 words; over 120 is off-voice" — not
  "concise and direct." Every adjective needs a number attached or it doesn't belong.
- Every claim carries its number, pulled directly from `fingerprint.json` — do not
  round to a qualitative label. Source each `## Core directives` line from a specific
  field:
  - Length: `baseline.shape.words_per_email.median` (state as "Median N words"); flag
    "over N*1.8 is off-voice" using that same median.
  - Opener: the highest-value key in `baseline.openers` (e.g. `hi_name`, `bare_name`,
    `none`), written as the literal pattern it represents, with its rate as a percent.
  - Ask placement: `baseline.ask_placement_median`, described as "median position X
    of the way through the email" (or "no clear ask" if null).
  - Contractions: `baseline.contraction_rate` as a percent, only if
    `english_metrics_valid` is true.
  - Punctuation tics: any `baseline.punctuation` rate that is clearly nonzero and
    distinctive (em dash, semicolon, ellipsis, parenthesis) — state as "N per 100
    words," not "occasional."
  - Lexicon: the top 2–3 entries from `baseline.lexicon` by `log_odds`, quoted
    verbatim as phrases this person actually reaches for. Skip entries that are just
    the closing signoff plus the person's own name (e.g. "best dana", "dana reyes")
    — that's structural and already covered by `closers`/`name_forms`, not a
    reached-for phrase. If adjacent unigram/bigram entries are fragments of one
    longer phrase (e.g. "worth a" + "a look"), report the combined phrase once
    ("worth a look") rather than both fragments.
- The **Never do this** section is the most valuable part. Derive it from what is
  *absent*: signoffs at 0%, zero exclamation marks to clients, hedges below baseline.
  Include the standard AI tells the corpus never uses — "I hope this finds you well",
  "circle back", "touch base", "reach out", "delve", "leverage" as a verb — and confirm
  each is genuinely absent from the exemplars/lexicon before listing it, don't just
  assert it by template.
- Register sections state *deltas* from baseline, never repeat the full metric block.
  For each register in `fingerprint.registers`, compare its `metrics` block to
  `baseline` field by field and report only what moved meaningfully (e.g. "median
  length halves to N words," "opener switches to bare name," "asks come at position X
  instead of Y"). A register with no meaningful delta gets a one-line "matches
  baseline" note, not a restated table.
- If `english_metrics_valid` is false, omit contraction rate and hedge markers, and
  note the omission explicitly in Core directives (state it as a line, don't just
  drop it silently).
- Name suppressed registers with their counts, from `fingerprint.suppressed_registers`,
  so the user knows what was too thin to profile (e.g. "personal (5) — too few to
  characterize").
- `exemplars.redacted.json` may contain a `terse_ack` key alongside the register keys.
  These are one-line replies (under 15 words — "Got it — will do.") that `ingest.py`
  set aside before any register metrics were computed, so they never appear in
  `fingerprint.json` and have no register of their own. If present, add one line to
  Core directives about the terse-ack pattern and include one as an Examples entry —
  don't fold it into a register's delta table, since no metrics back it.

```markdown
# How to write as <Name>

## Core directives
- Median length <N> words. Over <N*1.8> is off-voice.
- Open with "<pattern>" (<X>%) ...
- Put the ask <early/late>: median position <X> of the way in.
- <contraction guidance>, <punctuation tics with rates>

## Never do this
- Never opens with "I hope this finds you well."
- <absence-derived rules with counts>

## By audience
| Register | Messages | Delta from baseline |
| --- | --- | --- |

## Examples
### <Register> — <what it does>
<redacted exemplar>

## Metadata
Corpus: <N> messages, <start> to <end>. Registers: <list>.
Too thin to profile: <suppressed with counts>. Generated <date>.
```

### Step 6 — Clean up and report

Delete `~/.claude/wam/cache/` unless the user passed `--keep-cache`. Report: tier used,
messages analyzed, registers found, profile path. Show the **Never do this** list, since
it is the most immediately useful part, and offer to draft something as a test.
