---
name: write-as-me
description: Use when the user wants email written in their own voice, wants to analyze their writing style, asks to build or refresh a personal style profile, or wants to review drafts they've sent and learn from their edits. Triggers on "write as me", "in my voice", "sounds like me", "draft this email", "review my drafts", "learn from my edits", "/wam", "/wam review".
---

# write-as-me

Three modes. Pick by whether the user supplied an intent, asked for a review,
or neither.

| Invocation | Mode |
| --- | --- |
| `/write-as-me` or `/wam`, no arguments | **Analyze** — build the style profile |
| `/write-as-me review` or `/wam review` | **Review** — learn from edits made to sent drafts |
| `/write-as-me <what to say>` | **Write** — draft using the existing profile |
| `--refresh` present | **Analyze**, overwriting the existing profile |
| `--no-draft` present | **Write**, but present in chat only — no Gmail draft |

Write mode creates a Gmail draft by default when a recipient address is known; see
its Step 5 for the two cases that do not.

## Before either mode — the pending-edit check

Run once at the start of every invocation, before doing what the user asked:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --list-pending --now "<ISO-8601 NOW>"
```

For each pending draft, check whether it has since been sent (see review mode's
matching step). If any have, say **exactly one line** and then carry on with the
user's actual request:

> 2 drafts you sent have edits I haven't learned from — review them?

Rules:
- Never block. The user asked for something; this check does not get to
  postpone it.
- If they decline, do not raise it again in this session.
- If no Gmail tools are available, say once that the edit loop cannot run
  without them, and never mention it again.
- If `drafts.jsonl` is missing or unreadable, treat it as empty and say nothing.

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
over the last 6 months. Fetch up to 150 messages. Write them to
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
regexes catch). `redact.py` only ever processes `exemplars.json` — it never touches
`fingerprint.json`, and nothing scrubs the lexicon. This step must therefore cover
*both* the exemplars and the lexicon; do not treat it as an exemplars-only pass.

**Part A — Exemplars.** Go exemplar by exemplar, not corpus by corpus:

For each exemplar in `exemplars.redacted.json`, in order:
1. Read the full text of that one exemplar.
2. Check it against each of: person names in the body, company/organization names,
   project code names, account or reference numbers.
3. Replace anything the regexes missed with `[FIRST]`, `[COMPANY]`, or `[PROJECT]`.
   Keep the owner's own first name in signoffs.
4. State explicitly, per exemplar, that it was checked — e.g. "Exemplar 3/20
   (client): checked, no leaks" or "Exemplar 7/20 (cold_outreach): checked, redacted
   company name 'Ashford'."

Do not move to Part B until every exemplar has its own confirmation line. Never
present an exemplar in the final profile that you have not personally checked this
way.

**Part B — Lexicon.** `baseline.lexicon` in `fingerprint.json` is never redacted by
any script — you are the only check it gets. Its ranking method actively selects for
proper nouns: any phrase absent from the baseline gets scored against a smoothing
floor, so a client's company name or a project code name routinely outranks ordinary
words like "the." Step 5 instructs you to quote the top lexicon entries verbatim into
the durable profile, so a name that leaks here is not a transient context leak — it
is written to disk in `default.md` and kept indefinitely.

Apply the same per-entry rigor as Part A, entry by entry, not the list as a whole:

For each of the top entries you are considering quoting from `baseline.lexicon` (and
from each register's own lexicon, if you pull register-specific phrases), in order:
1. Read the phrase on its own.
2. Check it against each of: person names, company/organization names, project code
   names, account or reference numbers.
3. If it names a specific person, company, or project rather than a reached-for
   turn of phrase, drop that entry — do not quote it into the profile, and do not
   substitute a placeholder in its place; just move to the next-ranked entry.
4. State explicitly, per entry considered, that it was checked — e.g. "Lexicon
   entry 'worth a look': checked, no leaks" or "Lexicon entry 'ashford renewal':
   checked, dropped — names a client project."

Do not move to Step 5 until every lexicon entry you plan to quote has its own
confirmation line.

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
was used instead.

**If Gmail tools are available and a recipient address is known, create the Gmail
draft — do not ask first.** Report the draft id alongside the chat copy.

This is deliberate, and it is what makes the edit-learning loop work. The user edits
in Gmail, not in the terminal; a draft they have to request is a draft most of them
will never request, and the loop then has nothing to learn from. Leaving creation
opt-in put a question in front of the single step the whole feature depends on.

Two cases do **not** create a draft:

- **No recipient address.** If the draft carries the `Hi [Name],` placeholder, or the
  user named a person without an address you can resolve, present in chat only and say
  why — there is nothing to address it to. Do not guess an address; an email created
  against the wrong person is worse than one not created at all.
- **`--no-draft` was passed.** Present in chat only, for when the user wants text to
  paste somewhere else.

**Never send email.** Creating a draft is the furthest this skill goes. That boundary
does not move: a draft sits in the user's mailbox until they choose to send it, and
nothing in this skill may send on their behalf, whatever they ask for.

### Step 6 — Log the draft

After presenting, record it so review mode can find the sent version later:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --record \
  --register <REGISTER> --recipients "<COMMA SEPARATED>" \
  --subject "<SUBJECT>" --body-file <TEMP FILE> --created "<ISO-8601 NOW>"
```

Write the body to a temp file rather than passing it as an argument — draft
bodies contain newlines and quotes that do not survive a shell argument.

If the recipient was never supplied and the draft uses the `Hi [Name],`
placeholder, pass `--recipients ""`. Review mode will then require an exact
subject match, which is the safe behaviour when there is no recipient to
disambiguate with.

Logging is best-effort: if it fails, say so in one line and move on. A failed
log must never cost the user the draft they asked for.

## Review mode

Triggered by `/wam review`, or by the user accepting the pending-edit offer.

If `~/.claude/wam/default.md` does not exist, there is nothing to update — say
so and offer analyze mode instead.

### Every intermediate file goes in `~/.claude/wam/tmp/`, never the project

Review mode necessarily handles verbatim sent-mail text — the fetched sent
message, the draft/candidate JSON handed to `--match`, and the diff file
`diff_draft.py` writes all contain real sentences the user wrote. None of that
may ever land in the user's working directory, the same rule the rest of this
skill already follows for `~/.claude/wam/cache/`.

Every temp file this mode creates (draft JSON, candidates JSON, sent-message
JSON, the diff output) MUST be written under `~/.claude/wam/tmp/`, created if
missing. At the end of a review run — including a run that stops early because
the user declines, an `ambiguous` match is never resolved, or an error occurs —
delete `~/.claude/wam/tmp/` entirely. Treat this cleanup as unconditional, the
same way Analyze mode's Step 6 always deletes `~/.claude/wam/cache/`.

### Step 1 — Find the sent versions

List pending drafts. This call is intentionally compact — it feeds the
one-line non-blocking check and must never pull draft bodies into context:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --list-pending --now "<ISO-8601 NOW>"
```

Each line is `{"id", "created", "register", "recipients", "subject"}` —
no `body`. Before matching, fetch the complete record for each pending draft,
which includes the body that matching and diffing both need:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --get --draft-id <ID>
```

Then search `in:sent` for its subject, restricted to messages sent after the
draft's `created` timestamp and addressed to one of its recipients. Build each
candidate as `{"subject", "body", "recipients", "date"}` — all four keys,
`body` populated with the full message text, not left out or empty. Write the
draft record (from `--get`, unmodified) and the candidate list to
`~/.claude/wam/tmp/draft-<ID>.json` and `~/.claude/wam/tmp/candidates-<ID>.json`,
and let the matcher decide — do not decide by eye:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --match \
  --draft-file ~/.claude/wam/tmp/draft-<ID>.json \
  --candidates-file ~/.claude/wam/tmp/candidates-<ID>.json
```

A draft record with no `body` breaks matching silently rather than loudly: the
fuzzy-body fallback (`similarity()` against an empty string) always scores
0.0, so an edited-subject match that should fall back to the body simply never
fires. Always use the `--get` output, never the compact `--list-pending` line,
as the `--draft-file` input.

It prints `{"status": ..., "candidates": [...]}` where status is `matched`,
`ambiguous`, or `none`.

- `matched` — proceed to Step 2 using the one candidate as the sent file.
- `ambiguous` — show the user the candidate subjects and dates and ask which,
  if any. Never pick one yourself: learning from the wrong message teaches the
  profile from someone else's writing. If the user identifies one, proceed to
  Step 2 with it. If none of the candidates is the right message, mark the
  draft so it stops being re-offered:
  ```bash
  python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --set-status \
    --draft-id <ID> --status ambiguous
  ```
- `none` — leave it `pending`. It expires on its own at 30 days. Say nothing.

### Step 2 — Measure the change

`diff_draft.py`'s `--draft` and `--sent` files must each carry, at minimum,
`subject` and `body` — the same shape `--get` and a Gmail-fetched sent message
already produce. A record missing `body` fails with `KeyError: 'body'` rather
than a readable error, so never hand it a `--list-pending` line or a
partial record.

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/diff_draft.py \
  --draft ~/.claude/wam/tmp/draft-<ID>.json --sent ~/.claude/wam/tmp/sent-<ID>.json \
  --baseline ${CLAUDE_PLUGIN_ROOT}/fixtures/baseline_ngrams.json \
  --out ~/.claude/wam/tmp/diff-<ID>.json
```

If `classification` is `rewritten`, record it and derive nothing:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --record \
  --draft-id <ID> --classification rewritten --reviewed "<ISO-8601 NOW>"
```

Then mark the draft `matched` (it has been reviewed and resolved, even though
no observations came out of it) — same command as Step 6 — and tell the user
plainly that they replaced rather than edited that draft, and that a run of
rewrites means the profile is wrong at the root — re-running analyze mode
will serve them better than incremental learning.

### Step 3 — Classify every change

Read the diff file. For each removed sentence, added sentence, changed pair, and
non-trivial metric delta, decide which of three buckets it belongs in:

- **Factual** — a number, name, date, link, or fact changed, or content added
  that you could not have known. Record it in `factual_changes`. **It never
  becomes a profile directive.** The profile describes how the user writes, not
  what they know.
- **Voice** — a hedge removed, a sentence cut with no loss of information, an
  opener or signoff changed, a length cut, a structural change.
- **Neutral** — typo fixes, whitespace, reformatting. Ignore.

A single changed pair can be factual only, voice only, or both at once folded
into one sentence. Three examples — none of these sentences appear in this
skill's own fixtures, so treat them as illustrations of the rule, not answers
to copy:

- Factual only: "The renewal fee is $1,800" → "The renewal fee is $1,850" —
  only the number moved; the phrasing is untouched.
- Voice only: "I wanted to check in and see how things are progressing" →
  "How's it going?" — nothing about the facts changed, only the phrasing and
  length.
- Both, in one sentence: "I just wanted to let you know the shipment left the
  warehouse on the 9th" → "The shipment left the warehouse on the 11th." Two
  verdicts live in that one changed pair: the hedge "I just wanted to let you
  know" is cut (voice, dimension `hedging`), and the date moved from the 9th
  to the 11th (factual, goes to `factual_changes` and never becomes a
  directive). Record both. A single changed pair is not automatically a
  single verdict — read every changed pair for both kinds of edit before
  moving to the next one, even when it looks like one clean substitution.

A metric delta is not automatically its own observation, separate from the
sentence-level changes above. Check it against what you already classified:
if a delta is fully explained by a sentence change you already recorded —
cutting a closing-offer sentence also drops `word_count` and
`paragraph_count`, but that is one edit, not three — do not log a second
observation for it. A metric delta earns its own observation only when it
reflects something the sentence diff does not already explain: a punctuation
rate shifted across the whole email, a contraction-rate change, an opener or
signoff swap with no corresponding sentence entry. Counting one edit twice
hands promotion two votes for a single behavior, which quietly defeats the
two-independent-drafts rule the rest of this design rests on.

### Step 4 — Record observations

Each voice change becomes one observation with a dimension from the closed
vocabulary — `length`, `hedging`, `opener`, `signoff`, `ask_placement`,
`structure`, `punctuation`, `contractions`, `formality`, `closing_offer` — a
direction of `reduce`, `increase`, or `replace:<value>`, and **verbatim
evidence**. Paraphrased evidence is worthless later: the whole point is showing
the user the actual sentence they cut.

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --record \
  --draft-id <ID> --classification edited --reviewed "<ISO-8601 NOW>" \
  --observations-file <JSON FILE> --factual-file <JSON FILE>
```

The recorder rejects a dimension outside the vocabulary. That is deliberate:
free-text labels would never match each other and nothing would ever promote.
If a change genuinely does not fit any dimension, drop it rather than inventing
a label.

### Step 5 — Propose what has earned promotion

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/edit_log.py --promotable
```

This returns only dimensions with two or more observations from **separate
drafts** pointing the same way. Present each one on its own:

- State the proposed profile line.
- Show **both** pieces of verbatim evidence.
- If it contradicts a directive the profile measured from the corpus, say so
  and show both figures. Two edits do not silently overrule sixteen emails.
- Ask. One approval per change — never a batch yes.

### Step 6 — Apply approved changes

Edit `~/.claude/wam/default.md`, tagging every learned line with provenance:

```markdown
- Cut the closing offer sentence; you delete it. (learned from 2 edits, 2026-08-18)
```

Provenance is required. A directive resting on two edits is weaker evidence than
one resting on the whole corpus, and the profile must not present them as equal.
The tag also lets the user strip learned lines wholesale if the loop drifts.

Then mark each reviewed draft `matched`, one call per draft:

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/draft_log.py --set-status \
  --draft-id <ID> --status matched
```

This is not optional bookkeeping: without it the draft stays `pending`
forever, the pending-edit check re-nags about it for the rest of its 30-day
retention window, and reviewing it again would append duplicate observations
to `edits.jsonl`.

Finally, delete `~/.claude/wam/tmp/` (see the note at the top of this mode),
and report: how many drafts were reviewed, how many changes were factual, how
many observations were recorded, and how many are still short of promotion.
