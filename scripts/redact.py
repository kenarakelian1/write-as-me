# scripts/redact.py
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"https?://\S+|\bwww\.\S+"), "[URL]"),
    (re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?\b"), "[$AMOUNT]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)"), "[PHONE]"),
    (re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Blvd)\b"),
     "[ADDRESS]"),
]

WEEKDAYS_MONTHS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}

# Capitalized words in salutation or signoff position are almost always people.
SALUTATION = re.compile(
    r"^(Hi|Hey|Hello|Dear)\s+([A-Z][\w'-]+)", re.MULTILINE
)
SIGNOFF_NAME = re.compile(
    r"^(Best|Thanks|Cheers|Regards|Sincerely|Best regards),?\s*\n\s*([A-Z][\w'-]+"
    r"(?:\s+[A-Z][\w'-]+)?)\s*$",
    re.MULTILINE,
)


# A line consisting only of capitalised names and commas, e.g. "Steven," or
# "Craig, Terri," — the bare-name greeting. SALUTATION only catches the
# "Hi <name>" form, so on real mail this leaked the recipient's first name on
# 44% of messages, the most common opener in the corpus.
BARE_NAME_OPENER = re.compile(
    r"\A[ \t]*([A-Z][\w'-]*(?:[ \t]*,[ \t]*[A-Z][\w'-]*)*)[ \t]*,[ \t]*$",
    re.MULTILINE,
)

# Greeting-shaped words that are not personal names. Redacting these would
# mangle ordinary openers without protecting anyone.
NOT_A_NAME = {
    "team", "all", "everyone", "folks", "hi", "hello", "hey", "thanks",
    "regards", "cheers", "good", "morning", "afternoon", "evening", "sincerely",
}


def _redact_bare_name_opener(text: str, keep: set[str]) -> str:
    """Replace a leading bare-name greeting line with placeholders."""
    match = BARE_NAME_OPENER.match(text)
    if not match:
        return text
    names = [n.strip() for n in match.group(0).strip().rstrip(",").split(",")]
    if not names or any(n.lower() in NOT_A_NAME for n in names if n):
        return text
    replaced = ", ".join(
        n if n.lower() in keep else "[FIRST]" for n in names if n
    )
    return replaced + "," + text[match.end():]


def redact(text: str, keep_names: set[str] | None = None) -> str:
    keep = {n.lower() for n in (keep_names or set())}

    for pattern, placeholder in PATTERNS:
        text = pattern.sub(placeholder, text)

    def _salutation(match: re.Match) -> str:
        greeting, name = match.group(1), match.group(2)
        if name.lower() in keep or name.lower() in WEEKDAYS_MONTHS:
            return match.group(0)
        return f"{greeting} [FIRST]"

    text = SALUTATION.sub(_salutation, text)
    text = _redact_bare_name_opener(text, keep)

    def _signoff(match: re.Match) -> str:
        closer, name = match.group(1), match.group(2)
        if name.split()[0].lower() in keep:
            return match.group(0)
        return f"{closer},\n[FIRST]"

    return SIGNOFF_NAME.sub(_signoff, text)


def redact_exemplars(data: dict, keep_names: set[str]) -> dict:
    return {
        register: [
            {**ex, "body": redact(ex["body"], keep_names),
             "subject": redact(ex["subject"], keep_names)}
            for ex in items
        ]
        for register, items in data.items()
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrub PII from exemplars.")
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-name", action="append", default=[],
                    help="Name to preserve, repeatable. Use the profile owner's name.")
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    result = redact_exemplars(data, set(args.keep_name))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"redacted -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
