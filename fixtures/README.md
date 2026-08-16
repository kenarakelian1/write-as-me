# fixtures/

## `baseline_ngrams.json`

A precomputed unigram/bigram relative-frequency table used as the "modern
English" baseline that a user's writing sample is compared against.

**Source:** Peter Norvig's n-gram frequency tables
(<https://norvig.com/ngrams/>), derived from the Google Web Trillion Word
Corpus. The underlying Google data is licensed **CC BY 3.0**; Norvig's
`count_1w.txt` (unigrams) and `count_2w.txt` (bigrams) redistribute it as
plain TSV (`<ngram>\t<count>`, sorted descending by count).

This is modern web English, not literary prose. That distinction matters: a
baseline built from 19th-century novels would rank ordinary business
vocabulary ("meeting", "deadline", "invoice") as highly distinctive, which
would drown out a user's actual pet phrases and stylistic quirks with noise
from the corpus mismatch.

**Build process:** `scripts/build_baseline.py` reads the two TSV files,
keeps only lowercase alphabetic (plus apostrophe) single- or two-word
entries, takes the top 20,000 of each by frequency, and rewrites counts as
relative frequencies (each section sums to ~1.0). The downloaded TSV source
files are not committed to this repo — see `scripts/build_baseline.py` for
regeneration instructions.

To regenerate:

```bash
curl -sL https://norvig.com/ngrams/count_1w.txt -o /path/to/scratch/count_1w.txt
curl -sL https://norvig.com/ngrams/count_2w.txt -o /path/to/scratch/count_2w.txt
python scripts/build_baseline.py \
  --unigrams /path/to/scratch/count_1w.txt \
  --bigrams /path/to/scratch/count_2w.txt \
  --out fixtures/baseline_ngrams.json
```

**Attribution:** Data derived from the Google Web Trillion Word Corpus,
copyright 2006 Google Inc., used under the Creative Commons Attribution 3.0
Unported License (CC BY 3.0), as redistributed by Peter Norvig at
<https://norvig.com/ngrams/>.

## `synthetic/`

A fictional persona corpus used to test style-extraction logic. See
`synthetic/README.md` for details.
