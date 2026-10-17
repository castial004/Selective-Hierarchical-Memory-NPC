"""Tests for the v0.5 research-strengthening modules.

Covers:
  * evaluation/families.py           -- multi-role scenario suite
  * evaluation/consolidation_study.py -- the consolidation-necessity experiment
  * evaluation/multiseed.py          -- multi-seed aggregation
  * evaluation/annotation.py         -- rater-merge pipeline

Same philosophy as the rest of the evaluation tests: assert properties that a
broken implementation would fail, and assert the *documented* results (including
the honest negatives) so future drift is visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc_memory_project.decision.valid_actions import ROLE_ACTIONS
from npc_memory_project.evaluation.baselines import default_suite
from npc_memory_project.evaluation.families import (
    ROLE_PROFILES, build_family_scenarios, evaluate_families,
)
from npc_memory_project.evaluation.multiseed import run_multiseed
from npc_memory_project.memory.manager import HierarchicalMemoryManager

REPO_ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ families
def test_family_suite_covers_every_role():
    scenarios = build_family_scenarios(6)
    roles = {s.role for s in scenarios}
    assert roles == set(ROLE_ACTIONS), "every role in valid_actions must be exercised"
    assert len(ROLE_PROFILES) == len(ROLE_ACTIONS)


def test_family_scenarios_only_carry_role_valid_invariants():
    """An invariant must not be attached to a role that cannot exhibit it.

    E1 asserts *no punitive action*; the suspect role has no punitive action in
    its menu, so E1 there would be vacuously true and meaningless. C1 needs a
    warm action to suppress. Both are gated on the role profile.
    """
    scenarios = build_family_scenarios(12)
    for s in scenarios:
        if "E1_exoneration_suppresses_punishment" in s.invariants:
            assert ROLE_PROFILES[s.role].has_punitive, s.role
        if "C1_accusation_suppresses_warmth" in s.invariants:
            assert ROLE_PROFILES[s.role].has_warm, s.role


def test_full_architecture_passes_the_family_suite():
    result = evaluate_families(build_family_scenarios(12),
                               retrieval=HierarchicalMemoryManager())
    assert result["passed"] == result["checks"]
    for role, detail in result["per_role"].items():
        assert detail["passed"] == detail["checks"], f"{role} failed"


def test_family_suite_discriminates_against_recency_only():
    """The instrument must separate the naive stream from the architecture.

    If every policy ties, the suite is not measuring retrieval and is useless.
    Recency-only is the baseline this construction is tuned to separate (the
    other baselines tie at this scale -- the honest documented result).
    """
    scenarios = build_family_scenarios(12)
    full = evaluate_families(scenarios, retrieval=HierarchicalMemoryManager())
    from npc_memory_project.evaluation.baselines import RecencyOnly
    naive = evaluate_families(scenarios, retrieval=RecencyOnly())
    assert naive["passed"] < full["passed"], (
        "recency-only tied the full architecture -- the family suite no longer "
        "exercises retrieval policy"
    )


def test_family_suite_is_deterministic():
    a = evaluate_families(build_family_scenarios(8), retrieval=HierarchicalMemoryManager())
    b = evaluate_families(build_family_scenarios(8), retrieval=HierarchicalMemoryManager())
    assert a["passed"] == b["passed"] and a["checks"] == b["checks"]


# --------------------------------------------------------- consolidation study
def test_consolidation_study_shows_the_documented_effect():
    """Consolidation preserves the decisive fact under retrieval pressure.

    This is the constructive existence test: without consolidation the weak
    exoneration is crowded out of top-k (coverage near zero); with it the
    consolidated semantic record survives (coverage near one). If this flips,
    either retrieval or consolidation changed and docs/EVALUATION.md is stale.
    """
    from npc_memory_project.evaluation.consolidation_study import run_consolidation_study

    result = run_consolidation_study(n=30)
    nc = result["no_consolidation"]
    wc = result["with_consolidation"]
    assert nc["rate"] < 0.2, "expected the raw evidence to be crowded out"
    assert wc["rate"] > 0.9, "expected consolidation to preserve the decisive fact"
    assert result["preserved_by_consolidation"] > 0
    assert result["degraded_by_consolidation"] == 0


def test_consolidation_study_is_deterministic():
    from npc_memory_project.evaluation.consolidation_study import (
        build_consolidation_scenarios, run_consolidation_study,
    )
    s1 = build_consolidation_scenarios(10)
    s2 = build_consolidation_scenarios(10)
    r1 = run_consolidation_study(s1)
    r2 = run_consolidation_study(s2)
    assert r1["with_consolidation"] == r2["with_consolidation"]


# ------------------------------------------------------------------ multiseed
def test_multiseed_aggregates_over_every_seed():
    result = run_multiseed(seeds=[1, 2, 3], include_baselines=True)
    assert result["seed_count"] == 3
    assert "invariants" in result["summary"] and "families" in result["summary"]
    for suite, methods in result["summary"].items():
        for method, row in methods.items():
            assert row["seeds"] == 3
            assert 0.0 <= row["mean_rate"] <= 1.0
            assert row["min_rate"] <= row["mean_rate"] <= row["max_rate"]


def test_multiseed_full_architecture_never_loses_to_a_baseline():
    """Across seeds the architecture must not be beaten by any baseline.

    It may tie (most baselines tie at this scale -- the documented result), but
    a baseline that is strictly better on some seed would contradict every other
    instrument and must fail this test.
    """
    result = run_multiseed(seeds=[20260920 + i for i in range(4)], include_baselines=True)
    for suite, cmp in result["comparisons"].items():
        for method, counts in cmp.items():
            assert counts["losses"] == 0, f"{suite}: SHM lost to {method} on some seed"


def test_multiseed_beats_recency_only_on_every_seed():
    result = run_multiseed(seeds=[20260920 + i for i in range(4)], include_baselines=True)
    for suite in ("invariants", "families"):
        cmp = result["comparisons"][suite]["recency-only"]
        assert cmp["wins"] == cmp["seeds"], f"{suite}: recency-only not beaten every seed"


# ----------------------------------------------------------------- annotation
def _export(tmp_path: Path) -> Path:
    from npc_memory_project.evaluation.report import export_labels
    base = tmp_path / "labels.json"
    export_labels(base)
    return base


def _rater_file(base: Path, rid: str, out: Path, flip: tuple = ()) -> Path:
    payload = json.loads(base.read_text())
    for i, case in enumerate(payload["cases"]):
        fam = case["author_label"]["expected_family"]
        if i in flip:
            fam = "neutral" if fam != "neutral" else "warm"
        case["raters"] = [{
            "rater_id": rid, "expected_actions": [],
            "expected_families": [fam], "rationale": "test",
        }]
    out.write_text(json.dumps(payload, indent=2))
    return out


def test_merge_propagates_only_unanimous_single_family(tmp_path):
    from npc_memory_project.evaluation.annotation import merge_rater_files

    base = _export(tmp_path)
    r1 = _rater_file(base, "a", tmp_path / "a.json")
    r2 = _rater_file(base, "b", tmp_path / "b.json", flip=(0, 3))

    result = merge_rater_files(base, [r1, r2])
    # disagreements must be flagged, not silently averaged
    assert set(result["needs_adjudication"]) == {
        result["payload"]["cases"][0]["case_id"],
        result["payload"]["cases"][3]["case_id"],
    }
    # agreed cases get an adjudicated family pre-filled
    agreed = [c for c in result["payload"]["cases"]
              if c["case_id"] not in result["needs_adjudication"]]
    assert all(c["adjudicated_family"] for c in agreed)


def test_merge_leaves_disagreements_unadjudicated(tmp_path):
    from npc_memory_project.evaluation.annotation import merge_rater_files

    base = _export(tmp_path)
    r1 = _rater_file(base, "a", tmp_path / "a.json")
    r2 = _rater_file(base, "b", tmp_path / "b.json", flip=(0,))
    result = merge_rater_files(base, [r1, r2])
    cid = result["payload"]["cases"][0]["case_id"]
    flagged = [c for c in result["payload"]["cases"] if c["case_id"] == cid][0]
    assert flagged["adjudicated_family"] is None


def test_merge_rejects_an_unknown_case(tmp_path):
    from npc_memory_project.evaluation.annotation import merge_rater_files

    base = _export(tmp_path)
    bad = json.loads(base.read_text())
    bad["cases"][0]["case_id"] = "not-a-real-case"
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit):
        merge_rater_files(base, [bad_path])


def test_annotation_tool_exists_and_has_no_method_names():
    """The shipped rater tool must not leak method identities."""
    tool = REPO_ROOT / "tools" / "annotate.html"
    assert tool.exists(), "tools/annotate.html must ship for the human-eval protocol"
    text = tool.read_text(encoding="utf-8").lower()
    for leaked in ("recency-only", "importance-only", "shm (this architecture)"):
        assert leaked not in text
