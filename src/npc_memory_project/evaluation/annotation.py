"""Merge rater annotation files into a single adjudicatable labels file.

Pipeline this completes
-----------------------
docs/HUMAN_EVAL_PROTOCOL.md specifies independent annotation by at least two
non-author raters, then adjudication, then scoring. The pieces:

1. python -m npc_memory_project.evaluation.report --export-labels labels.json
     -> the blank instrument (every case, every memory, author label for
        reference only).
2. Each rater opens tools/annotate.html, loads labels.json, selects plausible
   actions per case with a rationale, exports labels_<rater>.json.
3. This module merges those files into one labels.json carrying every rater's
   labels, and pre-fills adjudicated_family ONLY where the raters agree.
4. The facilitator resolves the disagreements by hand (or drops them, reporting
   the count).
5. python -m npc_memory_project.evaluation.report --labels labels.json scores
   the system, refusing to run until every case is adjudicated.

What "agree" means here
-----------------------
Each rater selects a *set* of acceptable action families per case. Two raters
agree when their family sets are identical. When every rater in the merge has
the same set and that set is a single family, adjudicated_family is set to it.
If the common set has several families (e.g. both warm and neutral acceptable),
adjudicated_family is left null because the scorer needs a single family and
choosing one would inject the facilitator's opinion without a record. Those
cases are listed for manual adjudication.

This module never invents a label. It only propagates unanimous agreement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: The kinds of annotator a label file may carry. The human-evaluation protocol
#: requires that HUMAN and LLM labels are never merged: an LLM set is a separate,
#: disclosed instrument, not ground truth. See docs/HUMAN_EVAL_PROTOCOL.md.
ANNOTATOR_TYPES = frozenset({
    "human", "llm_blind", "llm_repo_aware", "author", "synthetic", "unknown",
})


def dataset_kind(payload: Dict[str, object]) -> str:
    """Classify a labels payload by the kind of annotator that produced it."""
    kind = payload.get("annotator_type") or payload.get("label_source")
    return str(kind) if kind else "unknown"


def check_dataset_purity(
    payloads: Sequence[Tuple[str, Dict[str, object]]],
) -> Dict[str, object]:
    """Refuse to mix label files of different annotator kinds.

    This is the guard behind "keep human_labels.json and llm_labels.json
    separate". Passing a human file and an LLM file to the same dataset raises
    instead of silently producing a merged file that a reader could mistake for
    human ground truth.
    """
    by_kind: Dict[str, List[str]] = {}
    for name, payload in payloads:
        by_kind.setdefault(dataset_kind(payload), []).append(name)

    if len(by_kind) > 1:
        detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(by_kind.items()))
        raise SystemExit(
            "refusing to mix annotation kinds in one dataset -> " + detail
            + ". Keep human labels and LLM labels in separate files; see "
            "docs/HUMAN_EVAL_PROTOCOL.md (datasets are never merged)."
        )
    kind = next(iter(by_kind))
    return {"kind": kind, "files": by_kind[kind]}


def validate_annotations(
    labels: Dict[str, object], cases: Dict[str, object],
) -> Dict[str, object]:
    """Check an annotation set against the evaluator validation rules.

    Returns a summary and raises SystemExit on any violation. Checks: every case
    appears exactly once; every selected action is in that case's menu; the
    preferred action is among the acceptable ones; confidence in [0, 1]; every
    decisive memory id exists in the case; contradiction_summary present iff
    contradiction_present.
    """
    case_by_id = {c["case_id"]: c for c in cases.get("cases", [])}
    seen: set = set()
    problems: List[str] = []

    for entry in labels.get("cases", []):
        cid = entry.get("case_id")
        if cid in seen:
            problems.append(f"{cid}: duplicate case")
            continue
        seen.add(cid)
        case = case_by_id.get(cid)
        if case is None:
            problems.append(f"{cid}: not in the case set")
            continue

        menu = set(case.get("action_menu", []))
        acceptable = entry.get("acceptable_actions", [])
        preferred = entry.get("preferred_action")
        for action in acceptable:
            if action not in menu:
                problems.append(f"{cid}: action '{action}' not in the menu")
        if preferred not in acceptable:
            problems.append(f"{cid}: preferred '{preferred}' not in acceptable_actions")

        conf = entry.get("confidence")
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            problems.append(f"{cid}: confidence {conf!r} outside [0, 1]")

        mem_ids = {m["event_id"] for m in case.get("memories", [])}
        for mid in entry.get("decisive_memory_ids", []):
            if mid not in mem_ids:
                problems.append(f"{cid}: decisive memory '{mid}' not in the case")

        has_summary = bool(entry.get("contradiction_summary"))
        if bool(entry.get("contradiction_present")) != has_summary:
            problems.append(f"{cid}: contradiction_present and summary disagree")

    for cid in case_by_id:
        if cid not in seen:
            problems.append(f"{cid}: case has no annotation")

    if problems:
        raise SystemExit("annotation validation failed:\n  " + "\n  ".join(problems))
    return {"cases": len(seen), "valid": True}


def _families_of(rater: Dict[str, object]) -> Tuple[str, ...]:
    fams = rater.get("expected_families")
    if isinstance(fams, list) and fams:
        return tuple(sorted(str(f) for f in fams))
    single = rater.get("expected_family")
    return (str(single),) if single else ()


def load_rater_file(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "cases" not in payload:
        raise SystemExit(f"{path}: not an annotation export (no 'cases')")
    return payload


def merge_rater_files(
    base_path: Path,
    rater_paths: Sequence[Path],
) -> Dict[str, object]:
    """Merge rater exports onto the base instrument. Returns the merged payload."""
    base = load_rater_file(base_path)
    base_cases = {c["case_id"]: c for c in base.get("cases", [])}
    if not base_cases:
        raise SystemExit(f"{base_path}: no cases")

    # case_id -> rater_id -> rater entry
    gathered: Dict[str, Dict[str, Dict[str, object]]] = {cid: {} for cid in base_cases}
    rater_ids: List[str] = []

    for path in rater_paths:
        payload = load_rater_file(path)
        for entry in payload.get("cases", []):
            cid = entry.get("case_id")
            if cid not in base_cases:
                raise SystemExit(f"{path}: unknown case_id {cid!r}")
            for rater in entry.get("raters", []):
                rid = str(rater.get("rater_id") or f"rater-{len(rater_ids) + 1}")
                if rid not in rater_ids:
                    rater_ids.append(rid)
                gathered[cid][rid] = {
                    "rater_id": rid,
                    "expected_actions": list(rater.get("expected_actions", [])),
                    "expected_families": list(rater.get("expected_families", [])),
                    "rationale": rater.get("rationale", ""),
                }

    merged_cases: List[Dict[str, object]] = []
    needs_adjudication: List[str] = []
    unanimous: List[str] = []
    unannotated: List[str] = []

    for cid, base_case in base_cases.items():
        per_rater = gathered.get(cid, {})
        raters = [per_rater[rid] for rid in rater_ids if rid in per_rater]

        case_out = dict(base_case)
        case_out["raters"] = raters
        case_out["adjudicated_family"] = None

        if not raters:
            unannotated.append(cid)
        else:
            family_sets = {_families_of(r) for r in raters}
            if len(family_sets) == 1:
                common = next(iter(family_sets))
                if len(common) == 1:
                    case_out["adjudicated_family"] = common[0]
                    unanimous.append(cid)
                else:
                    # unanimous on a multi-family set: defensible but ambiguous
                    needs_adjudication.append(cid)
            else:
                needs_adjudication.append(cid)

        merged_cases.append(case_out)

    merged = dict(base)
    merged["cases"] = merged_cases
    merged["merge_meta"] = {
        "raters": rater_ids,
        "rater_files": [str(p) for p in rater_paths],
        "unanimous_single_family": len(unanimous),
        "needs_manual_adjudication": len(needs_adjudication),
        "unannotated": len(unannotated),
    }
    return {
        "payload": merged,
        "unanimous": unanimous,
        "needs_adjudication": needs_adjudication,
        "unannotated": unannotated,
        "raters": rater_ids,
    }


def write_merged(result: Dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(result["payload"], indent=2), encoding="utf-8")


def print_merge_summary(result: Dict[str, object], path: Path) -> None:
    print("\nMerged rater annotations\n")
    print(f"  output file        : {path}")
    print(f"  raters             : {', '.join(result['raters']) or '(none)'}")
    print(f"  unanimous (1 family): {len(result['unanimous'])}")
    print(f"  needs adjudication : {len(result['needs_adjudication'])}")
    print(f"  unannotated        : {len(result['unannotated'])}")
    if result["needs_adjudication"]:
        print("\n  Cases requiring manual adjudication (raters disagreed or agreed on a"
              "\n  multi-family set -- open the JSON and set adjudicated_family):")
        for cid in result["needs_adjudication"]:
            print(f"    - {cid}")
    if result["unannotated"]:
        print("\n  Cases with no rater yet:")
        for cid in result["unannotated"]:
            print(f"    - {cid}")
    print("\n  Next: fill adjudicated_family for the cases above, then")
    print(f"  python -m npc_memory_project.evaluation.report --labels {path}")
    print()
