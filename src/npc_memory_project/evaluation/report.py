"""Evaluation report: one command per row of the results table.

This is the module `docs/HUMAN_EVAL_PROTOCOL.md` and `evaluation/labelled.py`
refer to. It is the single entry point for every number the project reports, so
that no result in the README or the paper can drift away from runnable code.

Examples
--------
    python -m npc_memory_project.evaluation.report                 # main table
    python -m npc_memory_project.evaluation.report --ablation
    python -m npc_memory_project.evaluation.report --scaling
    python -m npc_memory_project.evaluation.report --json results.json
    python -m npc_memory_project.evaluation.report --export-labels labels.json
    python -m npc_memory_project.evaluation.report --labels labels.json
    python -m npc_memory_project.evaluation.report --preference
    python -m npc_memory_project.evaluation.report --invariants 200

Every accuracy row carries a Wilson interval; every comparison against the full
architecture carries a paired bootstrap CI over *case indices* (the same cases
for both methods, so the pairing is valid). Small N is stated, never hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from npc_memory_project.evaluation.baselines import default_suite
from npc_memory_project.evaluation.harness import build_scenarios, evaluate
from npc_memory_project.evaluation.labelled import FAMILY, author_labelled_cases, run_labelled_suite
from npc_memory_project.evaluation.stats import (
    cohens_kappa, cohens_kappa_is_degenerate, format_interval, paired_bootstrap,
    summarise, wilson_interval,
)
from npc_memory_project.memory.manager import HierarchicalMemoryManager

FULL_NAME = "SHM (this architecture)"


# --------------------------------------------------------------------- table
def main_table(top_k: int = 5, bootstrap_iterations: int = 5000) -> Dict[str, object]:
    """Author-labelled accuracy + invariant compliance for every method."""
    rows: List[Dict[str, object]] = []

    methods: List[tuple] = [(FULL_NAME, HierarchicalMemoryManager())]
    methods += [(policy.name, policy) for policy in default_suite()]

    reference: Optional[Sequence[bool]] = None
    for name, retrieval in methods:
        labelled = run_labelled_suite(retrieval, top_k=top_k)
        invariants = evaluate(build_scenarios(60), retrieval=retrieval, top_k=top_k)
        correct = [bool(o["correct"]) for o in labelled["outcomes"]]  # type: ignore[index]

        if reference is None:
            reference = correct
            comparison = None
        else:
            comparison = paired_bootstrap(
                reference, correct, iterations=bootstrap_iterations,
            )

        rows.append({
            "method": name,
            "labelled_correct": labelled["correct"],
            "labelled_total": labelled["cases"],
            "labelled_accuracy": labelled["accuracy"],
            "labelled_ci": wilson_interval(labelled["correct"], labelled["cases"]),
            "invariants_passed": invariants["passed"],
            "invariants_checked": invariants["checks"],
            "invariants_rate": invariants["pass_rate"],
            "delta_vs_full": None if comparison is None else comparison["difference"],
            "delta_ci": None if comparison is None else (comparison["low"], comparison["high"]),
            "delta_p_gt_zero": None if comparison is None else comparison["p_gt_zero"],
        })

    return {
        "label_source": "author (NOT human ground truth -- see docs/HUMAN_EVAL_PROTOCOL.md)",
        "top_k": top_k,
        "rows": rows,
    }


def print_main_table(report: Dict[str, object]) -> None:
    rows = report["rows"]
    print("\nRetrieval comparison -- author-labelled decision set "
          f"({rows[0]['labelled_total']} cases, label_source=author)")
    print("  Authorship note: these labels were written by the system's author. "
          "They are a regression\n  instrument, not human ground truth."
          " Human validation is specified in docs/HUMAN_EVAL_PROTOCOL.md.\n")
    print(f"  {'method':<34}{'author-labelled (95% Wilson)':>44}{'invariants':>13}"
          f"{'full - method':>22}")
    print("  " + "-" * 113)
    for row in rows:
        ci = format_interval(row["labelled_correct"], row["labelled_total"])
        inv = f"{row['invariants_passed']}/{row['invariants_checked']}"
        if row["delta_vs_full"] is None:
            delta = "-- (reference)"
        else:
            low, high = row["delta_ci"]
            delta = f"{100 * row['delta_vs_full']:+.1f} pts [{100 * low:+.0f},{100 * high:+.0f}]"
        print(f"  {row['method']:<34}{ci:>44}{inv:>13}{delta:>22}")
    print("  'full - method' is the bootstrap advantage of the full architecture over each "
          "baseline;\n  an interval spanning 0 means the two are not distinguishable at this N.")
    print()


# ------------------------------------------------------------------ ablation
def ablation_table() -> List[Dict[str, object]]:
    from npc_memory_project.evaluation.ablation import run_ablation_suite

    return [
        {
            "variant": r.name,
            "notes": r.notes,
            "labelled_correct": r.labelled_correct,
            "labelled_total": r.labelled_total,
            "labelled_accuracy": r.accuracy,
            "labelled_ci": wilson_interval(r.labelled_correct, r.labelled_total),
            "invariants_passed": r.invariants_passed,
            "invariants_checked": r.invariants_checked,
            "invariants_rate": r.invariant_rate,
        }
        for r in run_ablation_suite()
    ]


def print_ablation_table(rows: List[Dict[str, object]]) -> None:
    print("\nComponent and feature ablation\n")
    print(f"  {'variant':<34}{'labelled':>13}{'invariants':>13}  note")
    print("  " + "-" * 100)
    for row in rows:
        acc = f"{100 * row['labelled_accuracy']:.1f}%"
        inv = f"{row['invariants_passed']}/{row['invariants_checked']}"
        print(f"  {row['variant']:<34}{acc:>13}{inv:>13}  {row['notes']}")
    print()


# ------------------------------------------------------------------- scaling
def scaling_table(iterations: int = 60) -> List[Dict[str, object]]:
    from npc_memory_project.evaluation.scaling import run_scaling_experiment

    return [
        {
            "npcs": r.npcs,
            "memories_per_npc": r.memories_per_npc,
            "store_records": r.store_records,
            "decision_median_ms": r.decision_median_ms,
            "decision_p95_ms": r.decision_p95_ms,
            "retrieved_median": r.retrieved_median,
            "invariant_rate": r.invariant_rate,
        }
        for r in run_scaling_experiment(iterations=iterations)
    ]


def print_scaling_table(rows: List[Dict[str, object]]) -> None:
    print("\nScaling -- decision latency against world size\n")
    print(f"  {'NPCs':>5}{'mem/NPC':>9}{'store':>8}{'retrieved':>11}"
          f"{'median ms':>12}{'p95 ms':>10}{'invariants':>12}")
    print("  " + "-" * 69)
    for row in rows:
        print(f"  {row['npcs']:>5}{row['memories_per_npc']:>9}{row['store_records']:>8}"
              f"{row['retrieved_median']:>11}{row['decision_median_ms']:>12.3f}"
              f"{row['decision_p95_ms']:>10.3f}{100 * row['invariant_rate']:>11.0f}%")
    print()


# --------------------------------------------------------- label I/O helpers
def build_label_payload(blind_retrieval: bool = False, top_k: int = 5) -> Dict[str, object]:
    """Build the annotatable payload. Never touches disk -- see export_labels."""
    payload: Dict[str, object] = {
        "schema": "shm-npc/labelled-cases/1",
        "label_source": "author",
        "warning": (
            "These are AUTHOR labels. Do not report them as human ground truth. "
            "See docs/HUMAN_EVAL_PROTOCOL.md."
        ),
        "top_k": top_k,
        "cases": [],
    }

    for case in author_labelled_cases():
        conflict_groups: Dict[str, List[str]] = {}
        for memory in case.memories:
            key = (memory.metadata or {}).get("conflict_key")
            if key:
                conflict_groups.setdefault(key, []).append(
                    (memory.metadata or {}).get("claim", memory.event_type)
                )

        entry: Dict[str, object] = {
            "case_id": case.case_id,
            "npc": {
                "npc_id": case.npc.npc_id, "role": case.npc.role, "trust": case.npc.trust,
                "personality": dict(case.npc.personality),
                "inventory": dict(case.npc.inventory or {}),
                "hostile": case.npc.hostile,
            },
            "world": {
                "game_day": case.world.game_day, "location": case.world.location,
                "player_has_money": case.world.player_has_money,
                "player_wanted": case.world.player_wanted,
                "metadata": dict(case.world.metadata or {}),
            },
            "memories": [
                {
                    "event_id": m.event_id, "summary": m.summary, "event_type": m.event_type,
                    "game_day": m.game_day, "tier": m.tier.value if hasattr(m.tier, "value") else str(m.tier),
                    "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                    "importance": m.importance, "confidence": m.confidence, "source": m.source,
                    "metadata": dict(m.metadata or {}),
                }
                for m in case.memories
            ],
            "conflict_groups": conflict_groups,
            "author_label": {
                "expected_family": case.expected_family,
                "rationale": case.rationale,
                "alternatives": list(case.alternatives),
            },
            # Filled in by raters, then adjudicated. The scorer reads these keys.
            "raters": [],
            "adjudicated_family": None,
        }

        if blind_retrieval:
            rater_view, key = _blind_retrieval_block(case, top_k)
            entry["rater_view"] = rater_view
            entry["facilitator_key"] = key

        payload["cases"].append(entry)  # type: ignore[union-attr]

    return payload


def export_labels(path: Path, blind_retrieval: bool = False, top_k: int = 5) -> Dict[str, object]:
    """Write the labelled case set for independent annotation."""
    payload = build_label_payload(blind_retrieval=blind_retrieval, top_k=top_k)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _blind_retrieval_block(case, top_k: int, seed: int = 20260920) -> tuple:
    """What each method *would* decide, shuffled, with the method names stripped.

    Returns ``(rater_view, facilitator_key)``. The rater view contains no method
    name anywhere -- a test asserts that -- so the study is blind by construction
    rather than by instruction.
    """
    from npc_memory_project.decision.engine import UtilityDecisionEngine

    engine = UtilityDecisionEngine()
    rows: List[Dict[str, object]] = []
    methods: List[tuple] = [(FULL_NAME, HierarchicalMemoryManager())]
    methods += [(policy.name, policy) for policy in default_suite()]

    for name, retrieval in methods:
        retrieved = retrieval.retrieve(case.memories, npc_id=case.npc.npc_id,
                                      current_day=case.world.game_day, top_k=top_k)
        action = engine.decide(case.npc, case.world, retrieved).selected_action
        rows.append({
            "method": name,
            "action": action,
            "family": FAMILY.get(action, "neutral"),
            "retrieved": [m.event_id for m in retrieved],
        })

    rng = random.Random(seed)
    rng.shuffle(rows)

    rater_view: List[Dict[str, object]] = []
    key: Dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        option = f"M{index}"
        key[option] = row["method"]
        rater_view.append({
            "option": option,
            "action": row["action"],
            "family": row["family"],
            "retrieved": row["retrieved"],
        })
    return rater_view, key


def score_against_labels(path: Path, top_k: int = 5) -> Dict[str, object]:
    """Score the system against adjudicated rater labels, with agreement stats."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = {c["case_id"]: c for c in payload.get("cases", [])}
    if not cases:
        raise SystemExit(f"{path}: no cases found")

    engine_retrieval = HierarchicalMemoryManager()
    from npc_memory_project.decision.engine import UtilityDecisionEngine

    engine = UtilityDecisionEngine()
    case_by_id = {c.case_id: c for c in author_labelled_cases()}

    predictions: List[str] = []
    truths: List[str] = []
    skipped: List[str] = []
    unresolved: List[str] = []

    for case_id, entry in cases.items():
        case = case_by_id.get(case_id)
        if case is None:
            raise SystemExit(f"{path}: unknown case_id {case_id!r}")
        raters = entry.get("raters") or []
        if not raters:
            unresolved.append(case_id)
            continue
        adjudicated = entry.get("adjudicated_family")
        if not adjudicated:
            skipped.append(case_id)
            continue
        retrieved = engine_retrieval.retrieve(
            case.memories, npc_id=case.npc.npc_id,
            current_day=case.world.game_day, top_k=top_k,
        )
        action = engine.decide(case.npc, case.world, retrieved).selected_action
        predictions.append(FAMILY.get(action, "neutral"))
        truths.append(adjudicated)

    if not predictions:
        raise SystemExit(
            f"{path}: no adjudicated labels yet ({len(unresolved)} unannotated, "
            f"{len(skipped)} annotated but not adjudicated). Fill in each case's "
            f"'raters' list and 'adjudicated_family', then re-run. "
            f"See docs/HUMAN_EVAL_PROTOCOL.md."
        )

    hits = sum(1 for p, t in zip(predictions, truths) if p == t)
    kappa = None
    if len(cases) >= 2:
        rater_sets = [
            entry.get("raters", []) for entry in cases.values() if entry.get("raters")
        ]
        if rater_sets and min(len(r) for r in rater_sets) >= 2:
            first = [r[0].get("expected_families", [""])[0] if isinstance(r[0].get("expected_families"), list) else r[0].get("expected_family", "") for r in rater_sets]
            second = [r[1].get("expected_families", [""])[0] if isinstance(r[1].get("expected_families"), list) else r[1].get("expected_family", "") for r in rater_sets]
            kappa = cohens_kappa(first, second)

    degenerate = False
    if len(cases) >= 2:
        all_families = [
            f for entry in cases.values()
            for rater in (entry.get("raters") or [])
            for f in rater.get("expected_families", [])
        ]
        degenerate = len(set(all_families)) < 2

    return {
        "labels_path": str(path),
        "labels_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "kappa_degenerate": degenerate,
        "system_correct": hits,
        "scored_cases": len(predictions),
        "system_accuracy": hits / len(predictions),
        "system_ci": wilson_interval(hits, len(predictions)),
        "inter_rater_kappa": kappa,
        "unannotated": len(unresolved),
        "annotated_not_adjudicated": len(skipped),
    }


def print_label_score(result: Dict[str, object]) -> None:
    print("\nScored against independently adjudicated labels\n")
    print(f"  labels file        : {result['labels_path']}")
    print(f"  sha256             : {result['labels_sha256'][:16]}...")
    print(f"  system accuracy    : {100 * result['system_accuracy']:.1f}% "
          f"({result['system_correct']}/{result['scored_cases']}) "
          f"95% CI {100 * result['system_ci'][0]:.1f}-{100 * result['system_ci'][1]:.1f}%")
    kappa = result["inter_rater_kappa"]
    print(f"  Cohen's kappa      : {'n/a (fewer than 2 raters per case)' if kappa is None else f'{kappa:.3f}'}")
    if result.get("kappa_degenerate"):
        print("  WARNING            : kappa is degenerate (one category only) -- do not report it")
    print(f"  unannotated cases  : {result['unannotated']}")
    print(f"  not adjudicated    : {result['annotated_not_adjudicated']}")
    print("\n  Reporting checklist (docs/HUMAN_EVAL_PROTOCOL.md section 5): state rater count and "
          "non-authorship,\n  kappa before adjudication, dropped cases, N with a Wilson "
          "interval, and this file's SHA.")
    print()


def preference_block(top_k: int = 5) -> Dict[str, object]:
    """Shuffled, method-blinded outputs for every case, for the protocol's study."""
    return build_label_payload(blind_retrieval=True, top_k=top_k)


def print_preference(payload: Dict[str, object]) -> None:
    print("\nMethod-blinded preference blocks (docs/HUMAN_EVAL_PROTOCOL.md section 4)\n")
    for entry in payload["cases"]:  # type: ignore[index]
        print(f"  {entry['case_id']}")
        for row in entry.get("rater_view", []):
            print(f"    {row['option']}  {row['action']:<16} ({row['family']})"
                  f"  from {len(row['retrieved'])} retrieved")
    print("\n  Options are shuffled per case and carry no method names; the facilitator key")
    print("  is written separately (--json) so the file handed to raters stays blind.")
    print()


def invariants_only(count: int, top_k: int = 5) -> Dict[str, object]:
    scenarios = build_scenarios(count)
    full = evaluate(scenarios, retrieval=HierarchicalMemoryManager(), top_k=top_k)
    rows = []
    for policy in default_suite():
        result = evaluate(scenarios, retrieval=policy, top_k=top_k)
        rows.append({
            "method": policy.name,
            "passed": result["passed"],
            "checked": result["checks"],
            "rate": result["pass_rate"],
            "per_invariant": result["per_invariant"],
        })
    return {"scenarios": count, "full": full, "baselines": rows}


# ------------------------------------------------------------------- entry
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m npc_memory_project.evaluation.report",
        description="Reproduce every number the project reports.",
    )
    parser.add_argument("--ablation", action="store_true", help="component/feature ablation")
    parser.add_argument("--scaling", action="store_true", help="latency vs world size")
    parser.add_argument("--all", action="store_true", help="main + ablation + scaling")
    parser.add_argument("--json", type=Path, help="write machine-readable results here")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--scaling-iterations", type=int, default=60)
    parser.add_argument("--invariants", type=int, metavar="N",
                        help="run the invariant suite over N scenarios and exit")
    parser.add_argument("--export-labels", type=Path, metavar="PATH",
                        help="write the labelled case set for independent annotation")
    parser.add_argument("--blind-retrieval", action="store_true",
                        help="with --export-labels/--preference: add shuffled method outputs")
    parser.add_argument("--labels", type=Path, metavar="PATH",
                        help="score the system against adjudicated rater labels")
    parser.add_argument("--preference", action="store_true",
                        help="print shuffle-blinded method outputs")
    args = parser.parse_args(argv)

    payload: Dict[str, object] = {}

    if args.export_labels:
        written = export_labels(args.export_labels, blind_retrieval=args.blind_retrieval,
                                top_k=args.top_k)
        print(f"wrote {len(written['cases'])} cases to {args.export_labels} "
              f"(label_source=author; annotate independently per docs/HUMAN_EVAL_PROTOCOL.md)")
        payload["exported"] = {"path": str(args.export_labels), "cases": len(written["cases"])}

    if args.preference:
        pref = preference_block(top_k=args.top_k)
        payload["preference"] = pref
        print_preference(pref)
        if args.json:
            key_path = args.json.with_suffix(".key.json")
            key_path.write_text(json.dumps(
                {c["case_id"]: c.get("facilitator_key", {}) for c in pref["cases"]},
                indent=2), encoding="utf-8")
            print(f"wrote facilitator key to {key_path} (keep away from raters)")

    if args.labels:
        result = score_against_labels(args.labels, top_k=args.top_k)
        print_label_score(result)
        payload["human_labels"] = result

    if args.invariants:
        result = invariants_only(args.invariants, top_k=args.top_k)
        full = result["full"]
        print(f"\nInvariant suite, {result['scenarios']} scenarios "
              f"({full['checks']} checks)")  # type: ignore[index]
        print(f"  {FULL_NAME:<36}{full['passed']}/{full['checks']}")  # type: ignore[index]
        for row in result["baselines"]:  # type: ignore[index]
            print(f"  {row['method']:<36}{row['passed']}/{row['checked']}")
        for name, detail in full["per_invariant"].items():  # type: ignore[index]
            print(f"    {name:<44}{detail['passed']}/{detail['checks']}")
        print()
        payload["invariants"] = result
        if args.json:
            args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"wrote {args.json}")
        return 0

    if args.export_labels or args.preference or args.labels:
        if args.json:
            args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"wrote {args.json}")
        return 0

    report = main_table(top_k=args.top_k, bootstrap_iterations=args.bootstrap)
    print_main_table(report)
    payload["main"] = report

    if args.ablation or args.all:
        rows = ablation_table()
        print_ablation_table(rows)
        payload["ablation"] = rows

    if args.scaling or args.all:
        rows = scaling_table(iterations=args.scaling_iterations)
        print_scaling_table(rows)
        payload["scaling"] = rows

    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
