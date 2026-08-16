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
    r"^(send|check|confirm|review|let|call|ping|see|take|hold|drop|add|move|use)\b",
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
    sents = sentences(text)
    for index, sent in enumerate(sents):
        if ASK.search(sent):
            return round(index / len(sents), 3)
    return None


SMOOTHING = 1e-7


def lexicon(messages: list[dict], baseline: dict, top_n: int = 15) -> list[dict]:
    """Rank the user's n-grams by log-odds against a common-English baseline."""
    words: list[str] = []
    for msg in messages:
        words.extend(w.lower() for w in WORD.findall(msg["body"]))

    uni = Counter(words)
    bi = Counter(f"{a} {b}" for a, b in zip(words, words[1:]))
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
            expected = base.get(phrase, SMOOTHING)
            scored.append(
                {
                    "phrase": phrase,
                    "count": count,
                    "log_odds": round(math.log(observed / expected), 3),
                }
            )
    scored.sort(key=lambda item: item["log_odds"], reverse=True)
    return scored[:top_n]
