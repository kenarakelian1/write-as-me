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

Do not add real correspondence to this directory. If more fixture pairs are
needed later, keep them equally fictional and keep this README's change list
in sync with whatever tests depend on it.
