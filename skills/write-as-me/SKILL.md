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

This is the last line of defense before real email excerpts are written to disk. A
skim is not enough — regex misses are rare but real (company names, project code
names, and account numbers are not shaped like the emails/URLs/amounts/phones the
regexes catch). Go exemplar by exemplar, not corpus by corpus:

For each exemplar in `exemplars.redacted.json`, in order:
1. Read the full text of that one exemplar.
2. Check it against each of: person names in the body, company/organization names,
   project code names, account or reference numbers.
3. Replace anything the regexes missed with `[FIRST]`, `[COMPANY]`, or `[PROJECT]`.
   Keep the owner's own first name in signoffs.
4. State explicitly, per exemplar, that it was checked — e.g. "Exemplar 3/20
   (client): checked, no leaks" or "Exemplar 7/20 (cold_outreach): checked, redacted
   company name 'Ashford'."

Do not move to Step 5 until every exemplar has its own confirmation line. Never
present an exemplar in the final profile that you have not personally checked this
way.

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

## Write mode

Triggered when the user supplies an intent: `/wam ask Priya to confirm the Q3 date`.

### Step 1 — Load the profile

Read `~/.claude/wam/default.md`. If it is missing, say so and offer to run analyze mode
instead. Do not draft from a guess about the user's voice — a generic draft with no
profile is worse than declining, because it looks finished.

### Step 2 — Pick the register

Infer from context, in order:
- Recipient's domain matches the user's own → `internal`.
- Recipient's domain is a personal/consumer provider (gmail.com, etc.) → `personal`.
- A named company, an unfamiliar business domain, or an existing-relationship
  recipient → `client`.
- No recipient given and the request reads like first contact / prospecting →
  `cold_outreach`, if that register exists in the profile.

Ask **at most one question**, and only when two candidate registers would produce a
materially different draft (different length band, ask placement, or signoff) and
nothing in the request disambiguates them. Never ask about tone, formality, or "how
would you like this to sound" — the profile already answers that; asking would be
interrogating the user about something the profile exists to settle.

**Missing recipient name.** Register selection above only needs a relationship, not a
name — "the vendor," "my manager," "an existing client" is enough to resolve
`internal` vs. `client` vs. `cold_outreach` without ever learning who the email is to.
But the register's opener may still call for a name (e.g. "Hi [Name],"), and if the
trigger never supplied one, do not invent one to fill it in. In order:
1. If the profile attests a genuine greeting-free opener for this register (a real
   `none` rate, not the leftover remainder from a `hi_name` majority), draft without a
   greeting — the missing name is a non-issue.
2. Otherwise, ask for it. This is allowed to be the one question the paragraph above
   permits, not an addition to it — if register and name are both unclear, resolve
   both with a single question rather than two.
3. If you aren't asking (the question budget went to the register instead, or the
   user asked for the draft without interruption), use the literal placeholder
   `Hi [Name],` in the draft. A placeholder is honest about what's missing; a
   plausible-sounding invented name is not, and it is never a substitute for one of
   the two paths above.

If the chosen register is in the profile's "too thin to profile" list, say so, fall
back to the baseline directives, and flag the draft as unregistered when you present it.

### Step 3 — Draft

Pull for the chosen register specifically — not the baseline — using the **By
audience** delta row and that register's own **Examples** entry as the primary
reference. Where a register has no meaningful delta ("matches baseline"), the Core
directives numbers apply directly. Match:

- length: that register's median word count, not the overall baseline median — trim
  phrasing before trimming facts; a date, name, or number the recipient needs is never
  the thing to cut
- opener: that register's pattern and rate, not the baseline opener
- ask placement: early/mid/late per that register's median position, when the content
  actually contains a request — a status update or FYI has none to place, and nothing
  in Step 4 should manufacture one to give this dimension something to measure
- signoff: that register's closing line and name form
- punctuation tics: that register's rate for each tic named in the profile
- paragraph count and structure, matching the shape of the register's Example

If the request is a one-line reply under ~15 words and the profile documents a
terse-ack pattern, use that micro-mode instead of a full register draft.

Imitate the exemplars for that register first and the metrics second — the exemplars
carry the voice; the metrics are guardrails, not a template to fill in mechanically.

### Step 4 — Self-check before showing anything

This is the load-bearing step. A draft that is approximately in-voice reads as
AI-written; the profile's **Never do this** list exists because absent traits are
what make AI email recognizable as AI email. Work through every item below against
the draft, in order, for the register you drafted in. Do not replace this with a
general "review for quality" pass, and do not skip an item because the draft "feels
right" — feel is exactly what this list is here to override. Two items below (1 and 4)
name an explicit not-applicable case; that is different from skipping an item because
it feels right, and it only applies where stated — never extend it to an item that
doesn't name one.

1. **Length.** Count the words. Compare to *this register's* median (By audience),
   not the overall baseline. Over ~1.8x that median is off-voice — cut content, don't
   compress by deleting articles or contractions to hit a number. Cut phrasing,
   hedging, or scene-setting first; never cut a fact the recipient actually needs — a
   date, a number, a name. If the necessary content genuinely doesn't fit under the
   ceiling, running a little long is the better failure than an email that's missing
   what it was supposed to say.
2. **Never-do-this list, one line at a time.** Open the profile's Never do this
   section and check the draft against each line individually, the same way exemplar
   redaction is checked one exemplar at a time — not as a single skim over the whole
   list. For each line: does the draft contain this exact pattern (a stock phrase, a
   punctuation mark, a structural habit)? If yes, rewrite it out, then continue to the
   next line.
3. **Opener.** Does it match this register's dominant opener pattern and rate? If the
   register's rate is well under 100%, the profile's own variation is license — don't
   force the majority pattern onto every draft — but never invent an opener pattern
   that isn't attested in the profile at all.
4. **Ask placement.** If the draft makes an actual request, is it at roughly this
   register's median position (open / middle / held-back), not wherever felt natural
   while writing? **If the content has no request in it at all — a status update, an
   FYI, a plain acknowledgment — this check does not apply.** Do not invent a
   question, a request, or a call-to-action just to give this item something to
   measure. Manufacturing an ask changes what the email actually asks the recipient
   to do, and the user might send it as written — that is a worse failure than any
   placement miss this check could catch.
5. **Signoff.** Does the closing line and name form match this register exactly —
   full name after a closing word, vs. bare first name after an em dash, vs. no
   signoff at all? A signoff form the profile marks as never occurring (e.g.
   initial-only) is disqualifying on its own.
6. **Punctuation tics.** Check this register's rate for each tic the profile names
   (em dash, semicolon, ellipsis, etc.), not the baseline rate. Marks the profile
   lists at zero must be exactly zero in the draft — "used sparingly" is a fail, not
   a pass.
7. **Contractions.** If the profile states a contraction rate near 100%, no
   fully-expanded form ("do not", "will not", "it is") should appear anywhere a
   contraction was grammatically possible.
8. **Structure.** Paragraph count and list handling should match what the profile
   says for structure (e.g. "never uses bullet points" becomes short prose sentences
   or a colon-led fragment instead), even when a bulleted list is the obvious default
   for the content.
9. **No invented specifics.** This generalizes item 4's rule beyond asks: every proper
   noun and concrete fact in the draft — a recipient's name, a company name, a date, a
   figure, a project name — must trace to one of three sources: the user's triggering
   request, the profile itself (the owner's own name, a phrase from the lexicon), or
   the placeholder conventions in Step 2 (`Hi [Name],`, `[COMPANY]`). If a name, date,
   or number appears anywhere in the draft that doesn't trace to one of those, it was
   invented — pull it and use a placeholder or ask, the same discipline as item 4.
   Matching the voice never licenses inventing the content.

If any check fails, fix it and re-run the full list from item 1 — don't spot-fix one
item and assume the rest still hold; a fix to length or structure can undo an opener
or signoff that previously passed. Do this silently: the user sees a finished draft,
never a checklist, a score, or a running commentary on what got fixed.

### Step 5 — Present

Show subject and body as plain text, ready to copy. Add one line naming the register
used — and, if the register was too thin to profile, say plainly that the baseline
was used instead. If Gmail tools are available, offer to save it as a draft; do not
create the draft without being asked.

**Never send email.** Creating a draft is the furthest this skill goes, and only when
the user explicitly asks for one.
