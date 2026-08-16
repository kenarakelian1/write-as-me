# write-as-me — Design Spec

**Date:** 2026-08-16
**Status:** Approved for planning
**Repo:** `write-as-me` (public, standalone)

## Summary

A Claude Code plugin that reads a person's past sent email, derives a personalized
writing-style guide, and uses that guide to draft new email in their voice.

Two modes on one command:

- `/write-as-me` (no args) — analyze the corpus, produce a style profile
- `/write-as-me <what you want to say>` — draft an email using the existing profile

`/wam` is a thin alias for both.

The guide is written to `~/.claude/wam/`, outside any repository, so it cannot be
committed by accident. (The storage directory keeps the short `wam` name throughout,
matching the shorthand command; only the skill, plugin, and repo are named
`write-as-me`.)

## Goals

1. Produce guidance specific enough to constrain output. "Friendly but professional"
   is a failure; "median 68 words, ask in the first two sentences, never opens with a
   pleasantry" is a success.
2. Work for anyone who installs the plugin, not just the author. No assumption of a
   particular mail provider or connector.
3. Never leak the corpus. Real email stays off disk in shareable locations, and
   excerpts are redacted before they reach the profile.
4. Be testable in public, without anyone's real mail.

## Non-goals

- Sending mail. The skill drafts; the human sends.
- A hosted service, web UI, or persistent index of the user's mailbox.
- Multi-user or team style profiles.
- Languages other than English are supported on a best-effort basis: structural
  metrics (length, paragraphing, openers, punctuation) hold, while English-specific
  metrics (contraction rate, hedge markers) degrade and are suppressed from the
  profile when the corpus is detected as predominantly non-English.

## Users and installation

Distributed as a Claude Code plugin:

```
/plugin marketplace add kenarakelian1/write-as-me
/plugin install write-as-me
```

The repo also works as a plain clone into `~/.claude/skills/`, but the plugin path is
the documented one, since it gives versioning and clean updates.

Runtime requirement: Python 3.9+ on PATH. Standard library only — no pip install, no
virtualenv, no lockfile. This is a deliberate constraint: a public plugin that
requires dependency installation loses most of its would-be users at the first step.

## Architecture

Deterministic work happens in Python; interpretive work happens in the model.

```
sources ──▶ ingest.py ──▶ corpus.json ──▶ fingerprint.py ──▶ fingerprint.json
                                                          └─▶ exemplars.json
                                                                    │
                                                              redact.py
                                                                    │
                                                                    ▼
                                              Claude synthesis ──▶ ~/.claude/wam/<profile>.md
```

The corpus never enters the model's context in bulk. The model sees a compact
fingerprint (a few KB of JSON) plus a handful of redacted exemplars. This keeps
analysis affordable on a large mailbox and keeps the counted metrics actually correct,
rather than eyeballed.

### Repo layout

```
write-as-me/
├─ .claude-plugin/
│  ├─ plugin.json
│  └─ marketplace.json
├─ skills/write-as-me/SKILL.md
├─ commands/wam.md                  # alias → delegates to the skill
├─ scripts/
│  ├─ ingest.py
│  ├─ fingerprint.py
│  ├─ redact.py
│  └─ eval_holdout.py
├─ fixtures/synthetic/              # fake persona, ~40 emails
├─ tests/
│  ├─ test_ingest.py
│  ├─ test_fingerprint.py
│  └─ test_redact.py
├─ docs/superpowers/specs/
├─ .gitignore
└─ README.md
```

## Stage 1 — Corpus acquisition

Three tiers, probed in order. The skill announces which tier it used.

**Tier 1: Gmail connector.** Search `in:sent -in:chats` over the last 12 months.
Target 60–150 messages. Thread context is fetched so each message carries its
recipients and whether it opened a thread or replied to one. Raw results are written
to `~/.claude/wam/cache/raw.json`.

**Tier 2: local export.** Look for `.mbox` or `.eml` files in `./emails/`, then in a
path the user supplies. Handles Google Takeout, Outlook, and Apple Mail exports.
Messages are filtered to those whose `From:` matches the user's address, which the
skill asks for if it cannot infer it.

**Tier 3: paste.** Prompt for 15–30 sent emails pasted directly. Floor of 12.

If fewer than 12 usable messages survive cleaning, the skill stops and explains what
it found rather than generating a profile from too little signal.

## Stage 2 — Cleaning

Most style tools fail here, by learning the quoted text of the person's
correspondents instead of the person.

- Strip quoted reply blocks: `>` prefixes, `On <date>, <name> wrote:`,
  `-----Original Message-----`, and `<blockquote>` in HTML parts.
- Strip signature blocks: the `-- ` delimiter, trailing contact blocks matched by a
  phone/address/title heuristic, and mobile footers such as "Sent from my iPhone".
- Prefer `text/plain` parts; fall back to HTML with tags stripped.
- Drop auto-replies (`Auto-Submitted`, `X-Autoreply`), calendar invites, and
  delivery notifications.
- Route messages under 15 words into a separate `terse_ack` bucket rather than
  discarding them — brief acknowledgements are a real and distinctive register.
- Deduplicate near-identical messages via normalized shingle overlap above 0.85,
  keeping the earliest. Without this, templated outreach dominates the fingerprint
  and the guide learns the template rather than the voice.

### Normalized message schema (`corpus.json`)

```json
{
  "id": "string",
  "date": "ISO-8601",
  "to_domains": ["example.com"],
  "recipient_count": 1,
  "subject": "string",
  "body": "cleaned plain text",
  "is_reply": true,
  "word_count": 87
}
```

## Stage 3 — Fingerprint

All values computed, none inferred. Emitted per corpus and per register bucket.

**Shape** — median and IQR of words per email, words per sentence, sentences per
paragraph, paragraphs per email.

**Openers** — frequency table over the first line, normalized into patterns:
`Hi <name>`, `Hey <name>`, `<name> —`, bare name, no greeting.

**Closers** — frequency table of signoff phrase, plus name form used (full name,
first name, initial, none).

**Mechanics** — contraction rate (contracted forms over expandable candidates);
per-100-word rates for em dash, ellipsis, exclamation mark, semicolon, parentheses;
emoji rate; all-lowercase-sentence rate.

**Stance** — hedge markers (`just`, `I think`, `maybe`, `sorry to`, `a bit`) per 100
words versus imperative-mood sentence rate; question rate; bullet-list usage rate.

**Structure** — subject line length, capitalization style, question-mark rate; and
**ask placement**, the sentence index of the primary request as a fraction of email
length. Whether someone leads with the ask or buries it is among the most recognizable
things about how they write.

**Lexicon** — distinctive 1–3-grams ranked by log-odds against a bundled
common-English frequency baseline. These are the pet phrases.

## Stage 4 — Register clustering

Messages are bucketed by recipient domain and relationship signal into: `internal`
(shared domain with the user), `client`, `cold_outreach` (no prior thread from that
address), `vendor`, `personal` (consumer mail domains), and `terse_ack`.

Each bucket gets its own fingerprint, reported as a **delta from the overall
baseline** rather than as a standalone table — this keeps the profile short and makes
the differences legible. A bucket needs at least 8 messages to earn a profile;
below that it folds into the baseline and the profile notes the omission.

## Stage 5 — Exemplar selection

Three to five per register, scored on: self-authored ratio after cleaning, proximity
to that register's median length, presence of a clear ask, and absence of
heavy domain-specific jargon. Exemplars are stored as full redacted text.

Exemplars carry more weight than any rule in the profile. Abstract guidance describes
a voice; a real message demonstrates it, and the model imitates demonstrations far
more faithfully than descriptions.

## Stage 6 — Redaction

A deterministic regex layer runs first: email addresses, phone numbers, URLs, street
addresses, and currency amounts. A model pass then catches person and company names
the regexes miss.

Rules:

- Replace, never delete. `[FIRST]`, `[COMPANY]`, `[$AMOUNT]`, `[URL]` preserve
  sentence rhythm and length, which are exactly the properties being modeled.
- The user's own first name is preserved wherever it appears in signoffs. That is
  style, not private data.
- Dates and weekdays are preserved.
- Redaction applies to exemplars and to any quoted snippet in the profile. It does
  not apply to `corpus.json`, which is treated as sensitive and deleted after the run
  unless `--keep-cache` is passed.

## Stage 7 — Profile output

Written to `~/.claude/wam/<profile>.md`, default profile name `default`.

Phrased as **directives, not description**. "Keep it under 80 words" is actionable;
"concise and direct" is not.

```markdown
# How to write as <Name>

## Core directives
- Median length 68 words. Over 120 is off-voice.
- Open with "Hi <first name>" (61%) or no greeting on replies (28%).
- Put the ask in the first two sentences. ...

## Never do this
- Never opens with "I hope this finds you well."
- Never uses "circle back", "touch base", "reach out".
- Never uses exclamation marks with clients (0 in 47 messages).

## By audience
| Register | Delta from baseline |
| --- | --- |
| client | +40% length, no contractions, formal signoff |
| internal | −30% length, lowercase subjects, heavy em dash |

## Examples
### Client — asking for a decision
<redacted verbatim email>

## Metadata
Corpus: 112 messages, 2025-08-14 → 2026-08-12. Generated 2026-08-16.
```

The **Never do this** section is the highest-value part. Positive guidance nudges;
prohibitions are what stop output from reading as generic AI prose, because the
tells are mostly things the person never writes.

## Write mode

`/write-as-me <intent>`:

1. Load the profile; if none exists, offer to run analysis first.
2. Determine register from the recipient if supplied; ask only when genuinely
   ambiguous.
3. Draft.
4. Self-check the draft against the anti-pattern list and the length band before
   presenting. Revise silently on a violation.
5. Present the draft in chat. Offer to create a Gmail draft when the connector is
   available. Never send.

## Testing

**Synthetic fixtures.** A fake persona with roughly 40 emails across registers,
committed to the repo. The entire pipeline is exercised publicly without anyone's real
mail, which also gives contributors something to develop against.

**Unit tests (pytest, deterministic).**
- `test_ingest.py` — quote-stripping across Gmail, Outlook, and Apple formats;
  signature detection; auto-reply rejection; dedupe threshold.
- `test_fingerprint.py` — every metric against hand-computed values on a small
  fixture.
- `test_redact.py` — PII patterns caught; length preserved within tolerance; the
  user's own name survives in signoffs.

**Holdout eval (`scripts/eval_holdout.py`, manual).** Five messages are withheld
before fingerprinting. Drafts are generated from each held-out subject plus a one-line
intent, with no sight of the original. The harness then compares fingerprints three
ways: draft versus held-out original, and a control draft written with no profile
versus the same original.

Success criterion: the profile-guided draft is closer to the original than the control
on at least 70% of metrics. This makes "it sounds like me" falsifiable, which it
otherwise is not, and it catches regressions when the analysis logic changes.

## Error handling

| Condition | Behavior |
| --- | --- |
| Fewer than 12 usable messages | Stop; report counts found and dropped, with reasons |
| No connector, no local files | Fall through to paste mode |
| Python missing | Clear message naming the requirement; no silent degradation |
| Single register only | Generate baseline profile; note the limitation in metadata |
| Corpus mostly non-English | Suppress English-specific metrics; note it |
| Profile missing in write mode | Offer to run analysis |
| Corrupt mbox | Skip unparseable messages, report the count, continue |

## Privacy

- Profiles and cache live in `~/.claude/wam/`, never inside the repo.
- `corpus.json` and `raw.json` are deleted at the end of an analysis run unless
  `--keep-cache` is passed.
- `.gitignore` covers `emails/`, `*.mbox`, `*.eml`, and `.wam/` so that a user who
  puts an export in the working directory cannot commit it.
- The README states plainly that a generated profile contains excerpts of real mail
  and should not be shared or committed.

## Out of scope for v1

Sending mail; tone adjustment sliders; profiles for people other than the user;
non-email formats such as Slack or LinkedIn; automatic profile refresh on a schedule.
