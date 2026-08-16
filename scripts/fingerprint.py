# scripts/fingerprint.py
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

# Each lookbehind must include the trailing period: the split point sits AFTER
# the ".", so "(?<!\bDr)" would inspect "r." and never fire.
ABBREV = (
    r"(?<!\bDr\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bSt\.)"
    r"(?<!\bp\.m\.)(?<!\ba\.m\.)(?<!\be\.g\.)(?<!\bi\.e\.)"
)
SENTENCE_END = re.compile(ABBREV + r"(?<=[.!?])\s+(?=[A-Z0-9])")
WORD = re.compile(r"[A-Za-z']+")


def sentences(text: str) -> list[str]:
    parts = [s.strip() for s in SENTENCE_END.split(text.strip()) if s.strip()]
    return parts


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def _summary(values: list[float]) -> dict:
    if not values:
        return {"median": 0.0, "iqr": [0.0, 0.0]}
    ordered = sorted(values)
    if len(ordered) >= 4:
        quartiles = statistics.quantiles(ordered, n=4)
        iqr = [quartiles[0], quartiles[2]]
    else:
        iqr = [ordered[0], ordered[-1]]
    return {"median": statistics.median(ordered), "iqr": iqr}


def shape_metrics(messages: list[dict]) -> dict:
    words_per_email, words_per_sentence = [], []
    sents_per_para, paras_per_email = [], []
    for msg in messages:
        body = msg["body"]
        words_per_email.append(len(WORD.findall(body)))
        paras = paragraphs(body)
        paras_per_email.append(len(paras))
        for para in paras:
            sents = sentences(para)
            sents_per_para.append(len(sents))
            for sent in sents:
                words_per_sentence.append(len(WORD.findall(sent)))
    return {
        "words_per_email": _summary(words_per_email),
        "words_per_sentence": _summary(words_per_sentence),
        "sentences_per_paragraph": _summary(sents_per_para),
        "paragraphs_per_email": _summary(paras_per_email),
    }


CONTRACTIBLE = re.compile(
    r"\b(do not|does not|did not|is not|are not|was not|were not|cannot|can not|"
    r"will not|would not|should not|could not|have not|has not|had not|it is|"
    r"that is|there is|I am|you are|we are|they are|I will|we will)\b",
    re.IGNORECASE,
)
CONTRACTION = re.compile(r"\b\w+'(t|s|re|ll|ve|d|m)\b", re.IGNORECASE)
EMOJI = re.compile("[🌀-🫿☀-➿]")
HEDGES = re.compile(
    r"\b(just|i think|maybe|perhaps|sorry to|a bit|kind of|sort of|possibly|"
    r"if that works|no rush|whenever you get a chance)\b",
    re.IGNORECASE,
)
ASK = re.compile(
    r"(\?|\b(can you|could you|would you|please|let me know|need you to|"
    r"send me|confirm|by (monday|tuesday|wednesday|thursday|friday|eod|end of))\b)",
    re.IGNORECASE,
)
IMPERATIVE_START = re.compile(
    r"^(send|check|confirm|review|let|call|ping|see|take|hold|drop|add|move|use|need)\b(?!-)",
    re.IGNORECASE,
)
SIGNOFFS = [
    "best", "thanks", "thank you", "cheers", "regards", "best regards",
    "talk soon", "sincerely", "all the best", "appreciate it",
]


def opener_pattern(body: str) -> str:
    first = body.strip().split("\n", 1)[0].strip()
    if re.match(r"^hi\s+[A-Z][\w'-]*\b", first, re.IGNORECASE):
        return "hi_name"
    if re.match(r"^(hey|hello)\s+[A-Z][\w'-]*\b", first, re.IGNORECASE):
        return "hey_name"
    if re.match(r"^[A-Z][\w'-]*\s*[—–-]\s*$", first) or re.match(
        r"^[A-Z][\w'-]*\s*[—–-]\s+\S", first
    ):
        return "name_dash"
    if re.match(r"^[A-Z][\w'-]*,\s*$", first):
        return "bare_name"
    return "none"


def closer_pattern(body: str) -> dict:
    tail = [ln.strip() for ln in body.strip().split("\n") if ln.strip()][-2:]
    signoff = "none"
    name_form = "none"
    for line in tail:
        cleaned = line.rstrip(",").strip().lower()
        if cleaned in SIGNOFFS:
            signoff = cleaned
    last = tail[-1] if tail else ""
    stripped = last.lstrip("—–-").strip().rstrip(",")
    words = stripped.split()
    if 1 <= len(words) <= 3 and all(w[:1].isupper() for w in words if w):
        if len(words) == 1:
            name_form = "initial" if len(words[0]) <= 2 else "first_name"
        else:
            name_form = "full_name"
    return {"signoff": signoff, "name_form": name_form}


def contraction_rate(text: str) -> float:
    contracted = len(CONTRACTION.findall(text))
    expanded = len(CONTRACTIBLE.findall(text))
    total = contracted + expanded
    return contracted / total if total else 0.0


def _per_100(count: int, words: int) -> float:
    return round(count * 100 / words, 3) if words else 0.0


def punct_rates(text: str) -> dict:
    words = len(WORD.findall(text))
    return {
        "em_dash": _per_100(len(re.findall(r"[—–]|--", text)), words),
        "ellipsis": _per_100(len(re.findall(r"\.\.\.|…", text)), words),
        "exclamation": _per_100(text.count("!"), words),
        "semicolon": _per_100(text.count(";"), words),
        "parenthesis": _per_100(text.count("("), words),
        "emoji": _per_100(len(EMOJI.findall(text)), words),
    }


def stance(text: str) -> dict:
    words = len(WORD.findall(text))
    sents = sentences(text)
    questions = sum(1 for s in sents if s.rstrip().endswith("?"))
    imperatives = sum(1 for s in sents if IMPERATIVE_START.match(s))
    bullets = sum(1 for ln in text.split("\n") if re.match(r"^\s*[-*•]\s+", ln))
    return {
        "hedges_per_100w": _per_100(len(HEDGES.findall(text)), words),
        "imperative_rate": round(imperatives / len(sents), 3) if sents else 0.0,
        "question_rate": round(questions / len(sents), 3) if sents else 0.0,
        "bullet_rate": round(bullets / len(sents), 3) if sents else 0.0,
    }


def ask_placement(text: str) -> float | None:
    # Paragraph-first, same as shape_metrics(): a bare greeting line ("Hi
    # Priya,") has no terminal punctuation, so splitting sentences() directly
    # on the raw body fuses the greeting into sentence[0] and pins every ask
    # near the front. Splitting into paragraphs first keeps the greeting as
    # its own unit.
    sents = []
    for para in paragraphs(text):
        sents.extend(sentences(para))
    for index, sent in enumerate(sents):
        if ASK.search(sent) or IMPERATIVE_START.match(sent):
            return round(index / len(sents), 3)
    return None


SMOOTHING = 1e-7


def _baseline_freq(phrase: str, base: dict) -> float:
    """Expected frequency of a phrase in ordinary English.

    Frequency tables are built from apostrophe-free tokens, so "it's", "can't"
    and "i'm" are absent and fall to the smoothing floor — which made every
    contraction score as maximally distinctive and crowd real pet phrases out
    of the ranking entirely. On real data the top five "distinctive phrases"
    came back as it's / that's / i'm / can't / what's.

    A contraction is not unusual English; it is the apostrophe-free form with
    an apostrophe. Score it against that form when the exact string is missing.
    How often someone contracts is already measured by contraction_rate.
    """
    if phrase in base:
        return base[phrase]
    if "'" in phrase:
        stripped = phrase.replace("'", "")
        if stripped in base:
            return base[stripped]
    return SMOOTHING


def lexicon(messages: list[dict], baseline: dict, top_n: int = 15) -> list[dict]:
    """Rank the user's n-grams by log-odds against a common-English baseline."""
    # Bigrams are built per message and summed, not over one flat word list
    # spanning every message — otherwise one email's signoff abuts the next
    # email's greeting (e.g. "...Dana Reyes" + "Hi Priya..." -> "reyes hi"),
    # producing a bigram that never occurred in any actual sentence.
    uni: Counter = Counter()
    bi: Counter = Counter()
    for msg in messages:
        msg_words = [w.lower() for w in WORD.findall(msg["body"])]
        uni.update(msg_words)
        bi.update(f"{a} {b}" for a, b in zip(msg_words, msg_words[1:]))
    uni_total = sum(uni.values()) or 1
    bi_total = sum(bi.values()) or 1

    scored = []
    for counts, total, base_key in (
        (uni, uni_total, "unigrams"),
        (bi, bi_total, "bigrams"),
    ):
        base = baseline.get(base_key, {})
        for phrase, count in counts.items():
            if count < 3:
                continue
            observed = count / total
            expected = _baseline_freq(phrase, base)
            scored.append(
                {
                    "phrase": phrase,
                    "count": count,
                    "log_odds": round(math.log(observed / expected), 3),
                }
            )
    scored.sort(key=lambda item: item["log_odds"], reverse=True)
    return scored[:top_n]


CONSUMER_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "me.com", "aol.com", "proton.me",
}
VENDOR_HINTS = ("billing", "support", "invoices", "noreply", "accounts")
MIN_REGISTER_SIZE = 8
MIN_CORPUS_SIZE = 12


def classify_register(msg: dict, user_domain: str, is_first_contact: bool) -> str:
    """Bucket a message by relationship, not by subject-line shape.

    internal/personal/vendor are decided from the message alone. client vs.
    cold_outreach is NOT inferred from is_reply (a "Re:" subject says nothing
    about whether *this* recipient has a prior relationship with the user) —
    it is handed in by assign_registers(), which derives it from whether any
    recipient domain on the message has appeared earlier in the user's own
    chronological send history.
    """
    domains = msg.get("to_domains") or []

    # A user on a consumer mailbox (gmail.com and friends) has no colleagues at
    # their own domain, so "shares my domain" cannot mean "internal" for them.
    # Applying that rule anyway swept every Gmail recipient into `internal`,
    # made `personal` unreachable, and mislabelled business mail that merely
    # CC'd one Gmail address. Consultants and freelancers on personal Gmail are
    # a large share of this plugin's users, so guard the rule rather than
    # assuming a corporate domain.
    user_is_consumer = user_domain in CONSUMER_DOMAINS
    if not user_is_consumer and any(d == user_domain for d in domains):
        return "internal"

    # Business domains decide the register; a consumer address alongside them
    # (a CC to someone's personal account) must not hijack it.
    business = [d for d in domains if d not in CONSUMER_DOMAINS and d != user_domain]
    if not business and any(d in CONSUMER_DOMAINS for d in domains):
        return "personal"

    subject = (msg.get("subject") or "").lower()
    if any(hint in subject for hint in VENDOR_HINTS):
        return "vendor"
    return "cold_outreach" if is_first_contact else "client"


def assign_registers(messages: list[dict], user_domain: str) -> dict[str, str]:
    """Map each message id to its register, deriving cold_outreach vs. client
    from relationship history instead of the reply flag.

    Walks messages in chronological order (undated messages sort last, so an
    unorderable message can never wrongly claim first-contact status) and
    tracks which external, non-consumer recipient domains have already been
    written to. A message counts as first contact only when *every* such
    domain on it is new; if any domain was seen on an earlier message, the
    whole message is "client" even if it also includes a brand-new domain.

    is_reply is used as a secondary signal, not the primary rule: a reply
    ("Re:") is evidence a thread already existed even when this sent-mail-only
    corpus has no earlier message to prove it, so a first-domain message that
    is a reply is still treated as an established contact rather than cold
    outreach.
    """
    def sort_key(msg: dict) -> tuple[bool, str]:
        date = msg.get("date") or ""
        return (date == "", date)

    seen_domains: set[str] = set()
    result: dict[str, str] = {}
    for msg in sorted(messages, key=sort_key):
        domains = [
            d for d in (msg.get("to_domains") or [])
            if d != user_domain and d not in CONSUMER_DOMAINS
        ]
        domain_repeat = bool(domains) and any(d in seen_domains for d in domains)
        is_first_contact = not domain_repeat and not msg.get("is_reply")
        result[msg["id"]] = classify_register(msg, user_domain, is_first_contact)
        seen_domains.update(domains)
    return result


def aggregate(messages: list[dict], baseline: dict) -> dict:
    joined = "\n\n".join(m["body"] for m in messages)
    openers = Counter(opener_pattern(m["body"]) for m in messages)
    closer_data = [closer_pattern(m["body"]) for m in messages]
    closers = Counter(c["signoff"] for c in closer_data)
    name_forms = Counter(c["name_form"] for c in closer_data)
    placements = [
        p for p in (ask_placement(m["body"]) for m in messages) if p is not None
    ]
    subjects = [m["subject"] for m in messages if m["subject"]]
    return {
        "shape": shape_metrics(messages),
        "openers": {k: round(v / len(messages), 3) for k, v in openers.items()},
        "closers": {k: round(v / len(messages), 3) for k, v in closers.items()},
        "name_forms": {k: round(v / len(messages), 3) for k, v in name_forms.items()},
        "contraction_rate": round(contraction_rate(joined), 3),
        "punctuation": punct_rates(joined),
        "stance": stance(joined),
        "ask_placement_median": (
            round(statistics.median(placements), 3) if placements else None
        ),
        "subject": {
            "median_words": (
                statistics.median([len(s.split()) for s in subjects])
                if subjects else 0
            ),
            "lowercase_rate": round(
                sum(1 for s in subjects if s == s.lower()) / len(subjects), 3
            ) if subjects else 0.0,
            "question_rate": round(
                sum(1 for s in subjects if s.rstrip().endswith("?")) / len(subjects), 3
            ) if subjects else 0.0,
        },
        "lexicon": lexicon(messages, baseline),
    }


def select_exemplars(messages: list[dict], count: int = 4) -> list[dict]:
    """Pick messages that best demonstrate the voice: near-median length, with an ask."""
    if not messages:
        return []
    median_words = statistics.median(m["word_count"] for m in messages)

    def score(msg: dict) -> float:
        spread = abs(msg["word_count"] - median_words) / (median_words or 1)
        has_ask = 1.0 if ASK.search(msg["body"]) else 0.0
        multi_para = 0.3 if len(paragraphs(msg["body"])) > 1 else 0.0
        return has_ask + multi_para - spread

    ranked = sorted(messages, key=score, reverse=True)
    return [
        {"subject": m["subject"], "body": m["body"], "word_count": m["word_count"]}
        for m in ranked[:count]
    ]


NON_ASCII_THRESHOLD = 0.15


def _english_likely(messages: list[dict]) -> bool:
    joined = "".join(m["body"] for m in messages)
    if not joined:
        return True
    non_ascii = sum(1 for ch in joined if ord(ch) > 127)
    return non_ascii / len(joined) < NON_ASCII_THRESHOLD


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute a style fingerprint.")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exemplars", required=True)
    args = ap.parse_args()

    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    messages = corpus["messages"]

    if len(messages) < MIN_CORPUS_SIZE:
        print(
            f"ERROR: {len(messages)} usable messages, need {MIN_CORPUS_SIZE}. "
            f"Parsed {corpus['stats']['raw']}, "
            f"dropped {corpus['stats']['raw'] - len(messages)} as quoted-only, "
            f"auto-replies, duplicates, or too short."
        )
        return 1

    user_domain = corpus["user"].split("@", 1)[1].lower()
    register_by_id = assign_registers(messages, user_domain)
    buckets: dict[str, list[dict]] = {}
    for msg in messages:
        buckets.setdefault(register_by_id[msg["id"]], []).append(msg)

    registers, suppressed = {}, {}
    for name, group in buckets.items():
        if len(group) >= MIN_REGISTER_SIZE:
            registers[name] = {"count": len(group), "metrics": aggregate(group, baseline)}
        else:
            suppressed[name] = len(group)

    dates = sorted(m["date"] for m in messages if m["date"])
    fingerprint = {
        "user": corpus["user"],
        "corpus_size": len(messages),
        "date_range": [dates[0], dates[-1]] if dates else ["", ""],
        "baseline": aggregate(messages, baseline),
        "registers": registers,
        "suppressed_registers": suppressed,
        "english_metrics_valid": _english_likely(messages),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")

    exemplars = {name: select_exemplars(group) for name, group in buckets.items()}
    if corpus.get("terse_ack"):
        exemplars["terse_ack"] = select_exemplars(corpus["terse_ack"], count=3)
    Path(args.exemplars).parent.mkdir(parents=True, exist_ok=True)
    Path(args.exemplars).write_text(json.dumps(exemplars, indent=2), encoding="utf-8")

    print(
        f"{len(messages)} messages, {len(registers)} registers "
        f"-> {args.out}, {args.exemplars}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
