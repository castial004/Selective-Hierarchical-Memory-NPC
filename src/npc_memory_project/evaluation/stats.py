"""Statistics helpers for the evaluation.

Small n is the honest problem with every experiment in this repository: the
invariant suite runs ~60 scenarios, the labelled set ~40 cases. Reporting a bare
percentage ("100% pass") over that hides the uncertainty, which is exactly what
v0.2 did. These helpers report intervals and paired comparisons instead.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence, Tuple


def wilson_interval(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default).

    Preferred over the normal approximation because it behaves sanely at 0% and
    100%, which is precisely where a 60-scenario suite lands.
    """
    if total == 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def format_interval(successes: int, total: int, z: float = 1.96) -> str:
    low, high = wilson_interval(successes, total, z)
    return f"{successes}/{total} ({100 * successes / total if total else 0:.1f}%, 95% CI {100 * low:.1f}–{100 * high:.1f}%)"


def paired_bootstrap(
    outcomes_a: Sequence[bool],
    outcomes_b: Sequence[bool],
    *,
    iterations: int = 5000,
    seed: int = 20260920,
) -> Dict[str, float]:
    """Bootstrap CI for the accuracy difference between two paired methods.

    Both methods are evaluated on the *same* items, so resample item indices, not
    each method independently. Returns the observed difference (a - b) and its
    95% percentile interval; an interval spanning zero means the two are not
    distinguishable at this sample size.
    """
    if len(outcomes_a) != len(outcomes_b):
        raise ValueError("paired comparison requires equal-length outcome lists")
    n = len(outcomes_a)
    if n == 0:
        return {"difference": 0.0, "low": 0.0, "high": 0.0, "n": 0, "p_gt_zero": 0.0}

    observed = sum(outcomes_a) / n - sum(outcomes_b) / n
    rng = random.Random(seed)
    deltas: List[float] = []
    for _ in range(iterations):
        picks = [rng.randrange(n) for _ in range(n)]
        a = sum(outcomes_a[i] for i in picks) / n
        b = sum(outcomes_b[i] for i in picks) / n
        deltas.append(a - b)
    deltas.sort()
    low = deltas[int(0.025 * iterations)]
    high = deltas[int(0.975 * iterations) - 1]
    return {
        "difference": observed,
        "low": low,
        "high": high,
        "n": n,
        "p_gt_zero": sum(1 for d in deltas if d > 0) / iterations,
    }


def cohens_kappa(labels_a: Sequence[str], labels_b: Sequence[str]) -> float:
    """Cohen's kappa for two label sequences (inter-rater agreement).

    Used by the labelling protocol: shipping a machine-authored ground truth and
    calling it "human-annotated" is not acceptable, so the protocol in
    ``docs/HUMAN_EVAL_PROTOCOL.md`` requires a second rater and this is how the
    agreement gets reported.

    Degenerate case: if every rater used a single category, chance agreement is
    1.0 and kappa is mathematically undefined (0/0). We return 1.0 rather than
    raising, but a caller must not *report* it -- with one category the labels
    carry no information. ``cohens_kappa_is_degenerate`` is the check for that.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must be the same length")
    n = len(labels_a)
    if n == 0:
        return 0.0
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    categories = set(labels_a) | set(labels_b)
    expected = 0.0
    for category in categories:
        pa = sum(1 for a in labels_a if a == category) / n
        pb = sum(1 for b in labels_b if b == category) / n
        expected += pa * pb
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def cohens_kappa_is_degenerate(labels_a: Sequence[str], labels_b: Sequence[str]) -> bool:
    """True when kappa is undefined because only one category was ever used."""
    categories = set(labels_a) | set(labels_b)
    return len(categories) < 2


def summarise(values: Sequence[float]) -> Dict[str, float]:
    """mean / median / p95 / max for latency-style measurements."""
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "mean": sum(ordered) / n,
        "median": ordered[n // 2],
        "p95": ordered[min(n - 1, int(0.95 * n))],
        "max": ordered[-1],
    }
