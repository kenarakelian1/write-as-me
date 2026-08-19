# edit_pairs fixture

`draft.json` and `sent.json` are **fictional** test data for `scripts/diff_draft.py`
and its tests (`tests/test_diff_draft.py`). Neither file represents a real email,
a real sender or recipient, or a real vendor deal. Both belong to the fictional
"Dana Reyes" persona used elsewhere in this repo's test fixtures.

`draft.json` is what write-as-me produced. `sent.json` is what the user actually
sent after editing it. The pair encodes three deliberate, hand-authored changes
between draft and sent, because the tests in `tests/test_diff_draft.py` assert
on them directly:

1. **Hedge removed** — `"I just wanted to flag that staging is still on the old
   config."` becomes the direct `"Staging is still on the old config."` This is
   a voice edit: it should show up as a drop in `stance.hedges_per_100w`.
2. **Closing offer sentence cut** — `"Happy to jump on a call if that is
   easier."` is removed entirely with no replacement. This should surface in
   `sentence_diff`'s `removed` list.
3. **Figure corrected** — `"the vendor contract goes out on the 15th"` becomes
   `"...on the 18th"`. This is a factual correction, not a voice edit, and
   should surface in `sentence_diff`'s `changed` list as a same-position
   sentence pair rather than a `removed`/`added` pair.

`draft_mixed.json` and `sent_mixed.json` are a second, equally **fictional**
pair, added to exercise the hard case the voice/factual split exists for: a
single sentence that carries both kinds of edit at once, rather than each
kind living in its own sentence the way the first pair separates them.

1. **Hedge removed and figure corrected, in one sentence** —
   `"I just wanted to flag that the invoice came to $4,200 for August's
   usage."` becomes `"The invoice came to $4,250 for August's usage."` The
   hedge `"I just wanted to flag that"` is a voice edit (dimension
   `hedging`); the amount changing from $4,200 to $4,250 is a factual
   correction that must never become a profile directive. `diff_draft.py`
   pairs these as a single `changed` entry (word-set similarity keeps them
   paired rather than split into `removed`/`added`), so a reviewer — human
   or model — must split the *content* of one changed pair into both
   buckets rather than assuming one changed pair carries only one verdict.

Neither fixture pair represents real correspondence, a real sender or
recipient, a real vendor deal, or a real invoice. Do not add real
correspondence to this directory. If more fixture pairs are needed later,
keep them equally fictional and keep this README's change list in sync with
whatever tests depend on it.
