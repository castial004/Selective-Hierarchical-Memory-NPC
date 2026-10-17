"""Multi-rater agreement and system scoring for the human-evaluation protocol.

The protocol (docs/HUMAN_EVAL_PROTOCOL.md) needs more than merge + single-family
scoring. This module supplies the agreement statistics and the scoring variants
the paper must report.

Agreement
---------
* Cohen's kappa on the collapsed single-primary-action label (pairwise, averaged),
  with a degeneracy guard -- one category only means kappa is undefined, not 1.0.
* Fleiss' kappa for 3+ raters on the collapsed label.
* Jaccard set-agreement per case for the multi-label form (raters may accept
  several actions); averaged, because a case with two defensible actions is not
  a disagreement.
* Krippendorff's alpha (nominal) as a robust multi-rater alternative when there
  are missing labels.

Scoring (against adjudicated labels)
------------------------------------
* accuracy -- selected action's family in the adjudicated accepted set.
* strict accuracy -- selected action equals the single adjudicated family.
* harmful-action rate -- the system picks a punitive action where the adjudicated
  set contains none. This is the safety-flavoured headline and is reported even
  when unflattering.
* Wilson 95% CI on accuracy.

Everything is computed from a labels payload; no rater file is ever fabricated
here. Synthetic raters are only built in tests, clearly marked.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.evaluation.stats import cohens_kappa, wilson_interval

#: The punitive *family* label (actions are mapped to families via labelled.FAMILY).
PUNITIVE_FAMILY = "punitive"


def _families(rater: Dict[str, object]) -> Tuple[str, ...]:
    fams = rater.get("expected_families")
    if isinstance(fams, list) and fams:
        return tuple(sorted({str(f) for f in fams}))
    single = rater.get("expected_family")
    return (str(single),) if single else ()


def _primary(fams: Sequence[str]) -> Optional[str]:
    """Collapse a multi-family set to a single primary label for kappa.

    Convention: a one-family set uses that family; a multi-family set uses the
    sorted-first, so the collapse is deterministic and reported. Used only for
    agreement statistics -- scoring uses the full set.
    """
    return fams[0] if fams else None


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


def _cohens_pairwise(label_lists: Sequence[Sequence[Optional[str]]]) -> Optional[float]:
    kappas: List[float] = []
    for i, j in combinations(range(len(label_lists)), 2):
        a, b = label_lists[i], label_lists[j]
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if len(pairs) < 2:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        if len(set(xs) | set(ys)) < 2:
            continue
        kappas.append(cohens_kappa(xs, ys))
    return sum(kappas) / len(kappas) if kappas else None


def fleiss_kappa(label_lists: Sequence[Sequence[Optional[str]]]) -> Optional[float]:
    """Fleiss' kappa for a fixed set of raters over items (nominal)."""
    n_items = len(label_lists[0]) if label_lists else 0
    if n_items == 0:
        return None
    categories = sorted({x for row in label_lists for x in row if x is not None})
    if len(categories) < 2:
        return None

    p_i_sum = 0.0
    counted_items = 0
    category_totals = {c: 0 for c in categories}
    total_assignments = 0
    for idx in range(n_items):
        row = [row[idx] for row in label_lists if row[idx] is not None]
        n = len(row)
        if n < 2:
            continue
        counts = {c: row.count(c) for c in categories}
        for c in categories:
            category_totals[c] += counts[c]
        total_assignments += n
        p_i = (sum(v ** 2 for v in counts.values()) - n) / (n * (n - 1))
        p_i_sum += p_i
        counted_items += 1

    if counted_items == 0 or total_assignments == 0:
        return None
    p_bar = p_i_sum / counted_items
    p_e = sum((category_totals[c] / total_assignments) ** 2 for c in categories)
    if p_e >= 1.0:
        return None
    return (p_bar - p_e) / (1 - p_e)


def krippendorff_alpha_nominal(
    label_lists: Sequence[Sequence[Optional[str]]]
) -> Optional[float]:
    """Krippendorff's alpha for nominal data with missing values allowed."""
    n_items = len(label_lists[0]) if label_lists else 0
    if n_items == 0:
        return None

    do_num = 0.0
    do_den = 0.0
    value_counts: Dict[str, int] = {}
    for idx in range(n_items):
        row = [r[idx] for r in label_lists if r[idx] is not None]
        m = len(row)
        if m < 2:
            if m == 1:
                value_counts[row[0]] = value_counts.get(row[0], 0) + 1
            continue
        for x in row:
            value_counts[x] = value_counts.get(x, 0) + (m - 1)
        for a, b in combinations(row, 2):
            do_den += 1
            if a != b:
                do_num += 1

    if do_den == 0:
        return None
    do = do_num / do_den

    total = sum(value_counts.values())
    if total == 0:
        return None
    de = 1.0 - sum((n / total) ** 2 for n in value_counts.values())
    if de <= 0:
        return None
    return 1.0 - do / de


@dataclass
class AgreementReport:
    cases: int
    raters: int
    cohens_pairwise_mean: Optional[float]
    fleiss_kappa: Optional[float]
    krippendorff_alpha: Optional[float]
    mean_jaccard: float
    per_case_jaccard: Dict[str, float]
    degenerate: bool


def evaluate_agreement(payload: Dict[str, object]) -> AgreementReport:
    """Agreement statistics over a merged labels payload."""
    cases = payload.get("cases", [])
    raters_per_case = [c.get("raters", []) for c in cases]

    max_raters = max((len(r) for r in raters_per_case), default=0)
    label_lists: List[List[Optional[str]]] = []
    for slot in range(max_raters):
        row: List[Optional[str]] = []
        for raters in raters_per_case:
            if slot < len(raters):
                row.append(_primary(_families(raters[slot])))
            else:
                row.append(None)
        label_lists.append(row)

    per_case_jaccard: Dict[str, float] = {}
    for case in cases:
        raters = case.get("raters", [])
        sets = [_families(r) for r in raters]
        if len(sets) < 2:
            continue
        pairwise = [jaccard(a, b) for a, b in combinations(sets, 2)]
        per_case_jaccard[case["case_id"]] = sum(pairwise) / len(pairwise)

    mean_j = (sum(per_case_jaccard.values()) / len(per_case_jaccard)
              if per_case_jaccard else 1.0)

    all_labels = [x for row in label_lists for x in row if x is not None]
    return AgreementReport(
        cases=len(cases),
        raters=max_raters,
        cohens_pairwise_mean=_cohens_pairwise(label_lists),
        fleiss_kappa=fleiss_kappa(label_lists),
        krippendorff_alpha=krippendorff_alpha_nominal(label_lists),
        mean_jaccard=mean_j,
        per_case_jaccard=per_case_jaccard,
        degenerate=len(set(all_labels)) < 2,
    )


@dataclass
class SystemScore:
    scored_cases: int
    accuracy: float
    accuracy_ci: Tuple[float, float]
    strict_accuracy: float
    harmful_action_rate: float
    unadjudicated: int


def score_system(payload: Dict[str, object], predictions: Dict[str, str]) -> SystemScore:
    """Score predictions (case_id -> action) against adjudicated labels."""
    from npc_memory_project.evaluation.labelled import FAMILY

    cases = payload.get("cases", [])
    correct = strict = harmful = scored = unadjudicated = 0
    for case in cases:
        adj = case.get("adjudicated_family")
        if not adj:
            unadjudicated += 1
            continue
        raters = case.get("raters", [])
        accepted = {adj}
        if raters:
            common = set(_families(raters[0]))
            for r in raters[1:]:
                common &= set(_families(r))
            accepted |= common
        cid = case["case_id"]
        if cid not in predictions:
            continue
        pred_family = FAMILY.get(predictions[cid], "neutral")
        scored += 1
        if pred_family in accepted:
            correct += 1
        if pred_family == adj:
            strict += 1
        if pred_family == PUNITIVE_FAMILY and PUNITIVE_FAMILY not in accepted:
            harmful += 1

    return SystemScore(
        scored_cases=scored,
        accuracy=(correct / scored) if scored else 0.0,
        accuracy_ci=wilson_interval(correct, scored) if scored else (0.0, 1.0),
        strict_accuracy=(strict / scored) if scored else 0.0,
        harmful_action_rate=(harmful / scored) if scored else 0.0,
        unadjudicated=unadjudicated,
    )


def print_agreement(report: AgreementReport) -> None:
    print("\nInter-rater agreement\n")
    print(f"  cases / raters        : {report.cases} / {report.raters}")
    def fmt(v):
        return "n/a (too few usable labels)" if v is None else f"{v:.3f}"
    print(f"  Cohen's kappa (pairwise mean) : {fmt(report.cohens_pairwise_mean)}")
    print(f"  Fleiss' kappa                 : {fmt(report.fleiss_kappa)}")
    print(f"  Krippendorff's alpha (nominal): {fmt(report.krippendorff_alpha)}")
    print(f"  mean Jaccard set-agreement    : {report.mean_jaccard:.3f}")
    if report.degenerate:
        print("  WARNING: only one label category in use -- kappa is degenerate, do not report")
    print()


def print_system_score(score: SystemScore) -> None:
    print("\nSystem score against adjudicated labels\n")
    lo, hi = score.accuracy_ci
    print(f"  scored cases      : {score.scored_cases}")
    print(f"  accuracy          : {100*score.accuracy:.1f}% (95% CI {100*lo:.1f}-{100*hi:.1f}%)")
    print(f"  strict accuracy   : {100*score.strict_accuracy:.1f}%")
    print(f"  harmful-action    : {100*score.harmful_action_rate:.1f}%")
    print(f"  unadjudicated     : {score.unadjudicated}")
    print()
