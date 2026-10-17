"""Multi-seed evaluation: how stable are the results across random draws?

Why this module exists
---------------------
docs/EVALUATION.md limitation 4: "One seed ... the scenarios are a single sample."
This module runs every instrument across many seeds and reports the distribution
plus per-seed win/tie/loss counts against the full architecture.

Instruments combined per seed
-----------------------------
* the invariant suite (harness.build_scenarios)
* the multi-role family suite (families.build_family_scenarios)
* the new scenario families (scenario_families.run_decision_families)

Per-seed results are preserved so an anomalous seed can be inspected; they are
never averaged away. The aggregation reports mean / stdev / min / max / perfect
counts, and counts, for every baseline, how many seeds it beat, tied, or lost to
the full architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from npc_memory_project.evaluation.baselines import default_suite
from npc_memory_project.evaluation.families import (
    build_family_scenarios, evaluate_families,
)
from npc_memory_project.evaluation.harness import build_scenarios, evaluate
from npc_memory_project.evaluation.scenario_families import run_decision_families
from npc_memory_project.memory.manager import HierarchicalMemoryManager

DEFAULT_SEEDS: Sequence[int] = tuple(20260920 + i for i in range(20))
FULL = "SHM (this architecture)"


@dataclass
class SeedSample:
    seed: int
    suite: str
    method: str
    passed: int
    checks: int

    @property
    def rate(self) -> float:
        return self.passed / self.checks if self.checks else 1.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def run_multiseed(
    *,
    seeds: Optional[Sequence[int]] = None,
    n_scenarios: int = 60,
    n_per_role: int = 12,
    top_k: int = 5,
    include_baselines: bool = True,
    include_families_v06: bool = True,
) -> Dict[str, object]:
    """Run every suite across seeds; aggregate per method and per suite."""
    seeds = list(seeds or DEFAULT_SEEDS)
    methods: List[tuple] = [(FULL, HierarchicalMemoryManager())]
    if include_baselines:
        methods += [(policy.name, policy) for policy in default_suite()]

    samples: List[SeedSample] = []

    for seed in seeds:
        inv_scenarios = build_scenarios(n_scenarios, seed=seed)
        fam_scenarios = build_family_scenarios(n_per_role, seed=seed + 1)
        for name, retrieval in methods:
            inv = evaluate(inv_scenarios, retrieval=retrieval, top_k=top_k)
            samples.append(SeedSample(seed, "invariants", name,
                                      inv["passed"], inv["checks"]))
            fam = evaluate_families(fam_scenarios, retrieval=retrieval, top_k=top_k)
            samples.append(SeedSample(seed, "families", name,
                                      fam["passed"], fam["checks"]))
            if include_families_v06:
                v6 = run_decision_families(retrieval=retrieval, seed=seed, top_k=top_k)
                samples.append(SeedSample(seed, "scenario_families", name,
                                          v6["passed"], v6["cases"]))

    return _aggregate(samples, seeds)


def _aggregate(samples: Sequence[SeedSample], seeds: Sequence[int]) -> Dict[str, object]:
    by_suite_method: Dict[str, Dict[str, List[SeedSample]]] = {}
    for s in samples:
        by_suite_method.setdefault(s.suite, {}).setdefault(s.method, []).append(s)

    summary: Dict[str, Dict[str, object]] = {}
    for suite, methods in by_suite_method.items():
        suite_summary: Dict[str, object] = {}
        for method, rows in methods.items():
            rates = [r.rate for r in rows]
            rates_sorted = sorted(rates)
            suite_summary[method] = {
                "seeds": len(rows),
                "mean_rate": _mean(rates),
                "stdev_rate": _stdev(rates),
                "min_rate": rates_sorted[0] if rates else 0.0,
                "max_rate": rates_sorted[-1] if rates else 0.0,
                "perfect_seeds": sum(1 for r in rates if r >= 1.0),
                # per-seed detail preserved so anomalous seeds are inspectable
                "per_seed": {r.seed: r.rate for r in rows},
            }
        summary[suite] = suite_summary

    comparisons: Dict[str, Dict[str, object]] = {}
    for suite, methods in by_suite_method.items():
        full = methods.get(FULL, [])
        full_by_seed = {s.seed: s.rate for s in full}
        cmp: Dict[str, object] = {}
        for method, rows in methods.items():
            if method == FULL:
                continue
            wins = ties = losses = 0
            for r in rows:
                f = full_by_seed.get(r.seed, 0.0)
                if f > r.rate + 1e-9:
                    wins += 1
                elif f < r.rate - 1e-9:
                    losses += 1
                else:
                    ties += 1
            cmp[method] = {"wins": wins, "ties": ties, "losses": losses,
                           "seeds": len(rows)}
        comparisons[suite] = cmp

    return {
        "seeds": list(seeds),
        "seed_count": len(seeds),
        "summary": summary,
        "comparisons": comparisons,
    }


def print_multiseed(result: Dict[str, object]) -> None:
    print(f"\nMulti-seed stability ({result['seed_count']} seeds)\n")
    for suite, methods in result["summary"].items():  # type: ignore[index]
        print(f"  [{suite}]")
        print(f"    {'method':<36}{'mean':>8}{'stdev':>8}{'min':>7}{'max':>7}{'perfect':>9}")
        print("    " + "-" * 75)
        for method, row in methods.items():
            print(f"    {method:<36}"
                  f"{100 * row['mean_rate']:>7.1f}%"
                  f"{100 * row['stdev_rate']:>7.1f}"
                  f"{100 * row['min_rate']:>6.0f}%"
                  f"{100 * row['max_rate']:>6.0f}%"
                  f"{row['perfect_seeds']:>6}/{row['seeds']}")
        print()
    print("  SHM vs each baseline, counted per seed (wins/ties/losses):")
    for suite, cmp in result["comparisons"].items():  # type: ignore[index]
        for method, c in cmp.items():
            print(f"    [{suite}] vs {method:<32} "
                  f"{c['wins']}/{c['ties']}/{c['losses']}")
    print()
    print("  A ranking that flips across seeds (nonzero losses) is not a ranking.")
    print()
