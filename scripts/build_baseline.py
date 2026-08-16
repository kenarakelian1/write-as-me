from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TOKEN = re.compile(r"^[a-z']+$")


def read_counts(path: Path, top_n: int, ngram_size: int) -> dict[str, float]:
    """Read a TSV frequency table: <ngram>\t<count> per line, already sorted
    descending by count. Returns relative frequencies."""
    entries: list[tuple[str, int]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 2:
                continue
            phrase, raw = parts[0].strip().lower(), parts[1].strip()
            if not raw.isdigit():
                continue
            words = phrase.split()
            if len(words) != ngram_size or not all(TOKEN.match(w) for w in words):
                continue
            entries.append((phrase, int(raw)))
            if len(entries) >= top_n:
                break

    total = sum(count for _, count in entries) or 1
    return {phrase: count / total for phrase, count in entries}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build an n-gram frequency baseline from TSV count tables."
    )
    ap.add_argument("--unigrams", required=True, help="TSV: word<TAB>count")
    ap.add_argument("--bigrams", required=True, help="TSV: 'w1 w2'<TAB>count")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-n", type=int, default=20000)
    args = ap.parse_args()

    baseline = {
        "unigrams": read_counts(Path(args.unigrams), args.top_n, 1),
        "bigrams": read_counts(Path(args.bigrams), args.top_n, 2),
    }
    Path(args.out).write_text(json.dumps(baseline), encoding="utf-8")
    print(
        f"wrote {args.out}: {len(baseline['unigrams'])} unigrams, "
        f"{len(baseline['bigrams'])} bigrams"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
