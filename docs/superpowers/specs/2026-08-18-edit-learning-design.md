# write-as-me — Edit-Learning Loop Design Spec

**Date:** 2026-08-18
**Status:** Approved for planning
**Repo:** `write-as-me`
**Builds on:** `docs/superpowers/specs/2026-08-16-write-as-me-design.md`

## Summary

Close the loop between what write-as-me drafts and what the user actually sends.

Today the profile is written once by analyze mode and never changes. Every time
the user edits a draft before sending it, they produce the clearest available
signal about how they want to sound — and that signal is discarded.

This adds a third mode: wam records the drafts it produces, later finds the sent
version in Gmail, measures what changed, separates voice edits from factual
corrections, and proposes profile changes once a pattern repeats.

## Goals

1. Learn from edits without the user having to remember the feature exists.
2. Never overfit. One edit is not a pattern; a directive reaching the profile
   must be supported by at least two independent observations.
3. Never confuse a factual correction with a voice signal.
4. Never guess which sent message corresponds to a draft. A wrong match teaches
   the profile from someone else's writing.
5. Add no second copy of the user's mail to disk.

## Non-goals

- Automatic profile edits. Every change is proposed and approved individually.
- Learning from mail wam did not draft. That is analyze mode's job.
- Learning from a total rewrite. See "Rewrite detection" below.
- Retroactive learning from drafts produced before this feature shipped.

## Architecture

Deterministic measurement in Python; interpretation in the model — the same
split the rest of the product uses.

```
write mode --> drafts.jsonl (pending)
                    |
            review mode: search in:sent, match
                    |
              diff_draft.py --> deltas + sentence diff
                    |
        model: classify voice / factual / neutral
                    |
              edits.jsonl (observations + evidence)
                    |
        2+ observations, same direction --> propose
                    |
              user approves --> profile updated, tagged
```

### New files

| Path | Responsibility |
| --- | --- |
| `scripts/diff_draft.py` | Measure draft vs. sent: metric deltas + sentence-level diff |
| `~/.claude/wam/drafts.jsonl` | Append-only record of drafts wam produced |
| `~/.claude/wam/edits.jsonl` | Voice observations with evidence, awaiting promotion |

Both state files live outside any repository and are covered by `.gitignore`
defensively.

## State

### `drafts.jsonl`

One JSON object per line, appended when write mode presents a draft. Fields:
`id`, `created` (ISO-8601), `register`, `recipients` (list), `subject`, `body`,
and `status`.

`status` is one of `pending`, `matched`, `expired`, `ambiguous`.

**Retention: 30 days.** Entries older than that are dropped on the next review
run regardless of status. The file holds real draft bodies; it is not an archive.

### `edits.jsonl`

One object per reviewed draft. Fields: `draft_id`, `reviewed` (ISO-8601),
`classification` (`edited` or `rewritten`), `observations`, and
`factual_changes`.

Each observation carries three fields: `dimension`, `direction`, and `evidence`
— the verbatim text that was cut, added, or changed.

**`dimension` is a closed vocabulary**, not free text. Promotion works by
counting observations that share a dimension and a direction, so free-text
labels would silently never match each other ("hedging" and "hedges" would look
like two unrelated observations and nothing would ever reach two). The permitted
values are exactly:

`length`, `hedging`, `opener`, `signoff`, `ask_placement`, `structure`,
`punctuation`, `contractions`, `formality`, `closing_offer`.

`direction` is one of `reduce`, `increase`, or `replace:<value>` for dimensions
where the change is categorical rather than directional (an opener or signoff
form). An observation that does not fit the vocabulary is recorded under the
nearest fitting dimension, or discarded if none fits — the vocabulary is not
extended silently at runtime.

`factual_changes` is a list of plain strings recorded for the user's benefit. It
never influences the profile.

## Matching a draft to its sent message

The step most likely to go wrong, so it fails closed.

1. Search `in:sent` for the draft's subject, restricted to messages sent after
   `created` and addressed to the same recipient. Exact subject + recipient +
   time window is a confident match.
2. If the subject was edited, fall back to body similarity using the same 5-word
   shingle Jaccard `dedupe()` already uses, over the same recipient and window.
   **Threshold 0.5** — lower than dedupe's 0.70 because an edited draft is
   expected to differ substantially, and the recipient plus time window are
   already doing most of the disambiguation.
3. If the draft was presented with a `[Name]` placeholder and no recipient was
   ever supplied, `recipients` is empty. Match on subject and time window alone,
   and require an exact subject — the recipient was doing most of the
   disambiguation, so without it the shingle fallback is not safe to use.
4. Exactly one candidate → `matched`.
5. Two or more candidates → `ambiguous`; ask the user which, never guess.
6. No candidate after 30 days → `expired`, silently. The user decided not to
   send it, and that is not a failure worth reporting.

The fetched sent message is held in memory for the duration of the diff and is
never written to disk. Only derived observations persist.

### Rewrite detection

If shingle similarity between draft and sent version is **below 0.25**, the user
did not edit the draft — they replaced it. Record `classification: rewritten`
and derive no observations.

A rewrite is arguably the strongest possible signal, but it is not expressible
as a delta: there is no "removed hedge" to point at, only two different emails.
Treating it as a pile of voice observations would flood `edits.jsonl` with noise
from a single message. Rewrites are surfaced in the review summary so the user
can see the count, and the right response to a run of them is re-running analyze
mode, not incremental learning.

## What `diff_draft.py` measures

CLI: `python scripts/diff_draft.py --draft FILE --sent FILE --baseline FILE
--out FILE`, emitting JSON.

**Structural** — word count absolute and percent change; sentence count;
paragraph count; opener pattern before and after; signoff phrase and name form
before and after; whether the subject changed, and both values.

**Metric deltas**, computed by reusing `aggregate()` on each version —
contraction rate, every punctuation tic, hedges per 100 words, imperative rate,
question rate, bullet rate, ask placement.

**Sentence-level diff** via `difflib.SequenceMatcher` over sentences from
`sentences()`, producing three lists: `removed`, `added`, `changed`.

The sentence diff is the highest-value output. A removed sentence is directly
interpretable in a way no aggregate is: cutting "Happy to send the full
breakdown if it's useful" is actionable; "bullet rate fell 0.04" is not.

## Review mode

Invoked as `/wam review`, and offered automatically.

**Automatic check.** At the start of any `/wam` invocation, read `drafts.jsonl`
for `pending` entries and check whether any have been sent. If so, print exactly
one line — "2 drafts you sent have edits I haven't learned from — review them?"
— and then do what the user actually asked. The check never blocks the request
it interrupted, and declining is not re-asked in the same session.

If no Gmail connector is available, say so once and never raise it again.

**Per matched draft:**

1. Run `diff_draft.py`.
2. Classify every change as **voice**, **factual**, or **neutral**:
   - *Factual* — numbers, names, dates, links, or content wam could not have
     known. Recorded in `factual_changes`, never promoted.
   - *Voice* — a hedge removed, a sentence cut with no informational loss, an
     opener or signoff changed, a length cut, a structural change.
   - *Neutral* — typo fixes, whitespace, reformatting.
3. Append observations with verbatim evidence to `edits.jsonl`.
4. Scan `edits.jsonl` for any dimension with **two or more observations in the
   same direction**. Only those are proposed.
5. Present each proposed profile change on its own, with both pieces of
   evidence, and ask. One approval per change — never a batch yes.

## Profile updates

Approved changes are written into `~/.claude/wam/default.md` with provenance:

```markdown
- Cut the closing offer sentence; you delete it. (learned from 2 edits, 2026-08-18)
```

**Provenance is required.** A directive resting on two edits is weaker evidence
than one resting on 1,900 words of corpus, and the profile must not present them
as equally solid. The tag also lets the user strip learned lines wholesale if the
loop drifts.

**Conflict rule.** When an edit observation contradicts a corpus-measured
directive, the proposal states the conflict explicitly and shows both figures.
Two edits do not silently overrule sixteen emails; the user decides.

## Error handling

| Condition | Behavior |
| --- | --- |
| No Gmail connector | Say once that the loop cannot run; never raise again |
| Draft never sent | `expired` at 30 days, silently |
| Subject edited | Shingle fallback at 0.5 |
| Two or more candidates | `ambiguous`; ask which, never guess |
| Similarity below 0.25 | `rewritten`; record, derive nothing |
| No profile exists | Review mode unavailable; offer analyze mode |
| `drafts.jsonl` missing or corrupt | Treat as empty; warn once; do not crash write mode |
| Observations conflict with each other | No promotion; both retained as evidence |

## Testing

**Fixtures.** A synthetic draft/sent pair for persona Dana Reyes with known
deltas — a hedge removed, a closing sentence cut, one figure corrected — so the
voice-versus-factual split is testable without real mail.

**Unit tests (pytest, deterministic).**

- `test_diff_draft.py` — every structural and metric delta against hand-computed
  values; sentence diff produces the expected removed/added/changed lists.
- Matching — exact subject; edited subject via shingles; ambiguous candidates;
  no match; rewrite below 0.25.
- Promotion — one observation does not promote; two in the same direction do;
  two in opposite directions do not.
- Retention — entries older than 30 days are dropped.
- Privacy — the sent body never appears in `edits.jsonl`.

## Out of scope for v1

Learning from drafts wam did not produce; automatic profile edits without
approval; learning from rewrites; cross-profile learning; any UI beyond chat.
