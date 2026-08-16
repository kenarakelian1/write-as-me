# scripts/eval_holdout.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fingerprint import aggregate  # noqa: E402

PASS_THRESHOLD = 0.7


def flatten(node: dict, prefix: str = "") -> dict:
    """Flatten a metric block to scalar leaves. Lists are skipped as unorderable."""
    out: dict[str, float] = {}
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{path}."))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[path] = float(value)
    return out


def compare(a: dict, b: dict) -> dict:
    flat_a, flat_b = flatten(a), flatten(b)
    return {
        key: abs(flat_a[key] - flat_b[key])
        for key in flat_a.keys() & flat_b.keys()
    }


def verdict(profile_deltas: dict, control_deltas: dict) -> dict:
    """Win rate excluding ties.

    A tied metric (profile delta == control delta — e.g. both are 0 because
    neither the original, the profile draft, nor the control used a
    semicolon) is not evidence against the profile: no draft, however
    perfect, could have "won" a metric where the control was already exactly
    as close as the truth. Counting ties in the denominator makes the pass
    bar unreachable whenever a corpus has several legitimately zero-rate
    metrics, independent of draft quality. Ties are therefore reported (see
    "ties" below) but excluded from the share computed.
    """
    shared = profile_deltas.keys() & control_deltas.keys()
    closer = sum(1 for k in shared if profile_deltas[k] < control_deltas[k])
    opposed = sum(1 for k in shared if control_deltas[k] < profile_deltas[k])
    ties = len(shared) - closer - opposed
    decided = closer + opposed
    share = round(closer / decided, 3) if decided else None
    return {
        "metrics_compared": len(shared),
        "profile_closer": closer,
        "control_closer": opposed,
        "ties": ties,
        "share": share,
        # None (not True/False) when there is no decided metric to judge by:
        # neither a pass nor a meaningful fail, just no signal.
        "pass": (share >= PASS_THRESHOLD) if share is not None else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare profile-guided drafts against held-out originals."
    )
    ap.add_argument("--holdout", required=True, help="JSON list of held-out messages")
    ap.add_argument("--profile-drafts", required=True)
    ap.add_argument("--control-drafts", required=True)
    ap.add_argument("--baseline", required=True)
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731

    truth = aggregate(load(args.holdout), baseline)
    profile_deltas = compare(truth, aggregate(load(args.profile_drafts), baseline))
    control_deltas = compare(truth, aggregate(load(args.control_drafts), baseline))
    result = verdict(profile_deltas, control_deltas)

    print(json.dumps(result, indent=2))
    worst = sorted(profile_deltas.items(), key=lambda kv: -kv[1])[:5]
    print("\nLargest remaining gaps:")
    for metric, delta in worst:
        print(f"  {metric}: {delta:.3f}")

    if result["pass"] is None:
        print(
            "\nInsufficient signal: every compared metric tied "
            f"({result['ties']}/{result['metrics_compared']}). "
            "Neither a pass nor a fail — widen the holdout or the drafts so "
            "some metrics actually differ."
        )
        return 2
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
