"""Tests for the v0.6 research-validation modules.

Covers:
  * evaluation/scenario_families.py -- reciprocity, betrayal, obligation,
    rumour provenance, conflicting witnesses
  * evaluation/pressure.py           -- consolidation pressure curve
  * evaluation/faithfulness.py       -- explanation-faithfulness metrics
  * evaluation/rater_agreement.py    -- agreement statistics + scoring
  * evaluation/multiseed.py          -- per-seed preservation

Philosophy: assert properties a broken implementation fails, assert the
documented results (including negatives) so drift is visible, and never fabricate
human data -- synthetic raters appear only here, marked as such.
"""

from __future__ import annotations

from npc_memory_project.evaluation.baselines import default_suite
from npc_memory_project.evaluation.faithfulness import (
    SCOPE_STATEMENT, evaluate_faithfulness,
)
from npc_memory_project.evaluation.multiseed import run_multiseed
from npc_memory_project.evaluation.pressure import (
    HierWithConsolidation, run_pressure_curve, summarise_curve,
)
from npc_memory_project.evaluation.rater_agreement import (
    evaluate_agreement, fleiss_kappa, jaccard, krippendorff_alpha_nominal,
    score_system,
)
from npc_memory_project.evaluation.scenario_families import (
    betrayal_cases, obligation_cases, reciprocity_cases, rumour_provenance_cases,
    run_belief_families, run_decision_families,
)


# --------------------------------------------------------- scenario families
def test_every_family_builds_nonempty_cases():
    for builder in (reciprocity_cases, betrayal_cases, obligation_cases):
        cases = builder()
        assert cases, f"{builder.__name__} produced no cases"
        for c in cases:
            assert c.memories, "a case must carry memories"
            assert c.acceptable, "a case must declare acceptable families"
            assert c.reason, "every invariant must state why it is reasonable"


def test_belief_families_prove_the_provenance_properties():
    """Echo chains must not corroborate; an independent source must."""
    detail = {c.invariant: c.passed for c in rumour_provenance_cases()}
    assert detail["D1_echo_does_not_raise_confidence"] is True
    assert detail["D2_independent_source_raises_confidence"] is True


def test_belief_families_all_pass():
    result = run_belief_families()
    assert result["passed"] == result["cases"], result["detail"]


def test_decision_families_run_against_every_baseline():
    """Every policy must be able to run the families without crashing."""
    for policy in default_suite():
        result = run_decision_families(retrieval=policy)
        assert result["cases"] > 0
        assert 0.0 <= result["pass_rate"] <= 1.0


def test_decision_families_tie_by_default_is_documented():
    """The honest negative: A-C do not discriminate at default retrieval.

    If a future change makes them discriminate, this test fails and the docs
    must be updated -- that is the intent.
    """
    full = run_decision_families()
    from npc_memory_project.evaluation.baselines import RecencyOnly
    naive = run_decision_families(retrieval=RecencyOnly())
    assert full["passed"] == naive["passed"], (
        "decision families now discriminate at default retrieval -- update "
        "docs/EVALUATION.md and remove the 'tie' note in --newfamilies"
    )


# --------------------------------------------------------------- pressure
def test_pressure_curve_covers_the_full_grid():
    result = run_pressure_curve(
        competing_levels=(0, 10), age_levels=(50,),
        importance_levels={"weak": 0.15}, top_k_levels=(5,),
    )
    # 2 competing x 1 age x 1 importance x 1 top_k x 5 policies
    assert len(result["points"]) == 2 * 1 * 1 * 1 * 5


def test_consolidation_preserves_coverage_under_pressure():
    """The core documented result: weak evidence is rescued by consolidation."""
    result = run_pressure_curve(
        competing_levels=(0, 50), age_levels=(50,),
        importance_levels={"weak": 0.15}, top_k_levels=(5,),
    )
    series = summarise_curve(result, importance="weak", age=50, top_k=5)
    shm = series["SHM (full + consolidation)"]
    hier = series["hierarchical, no consolidation"]
    # at 50 competitors: consolidation keeps coverage, plain hierarchy loses it
    assert shm[50]["coverage"] == 1.0
    assert hier[50]["coverage"] == 0.0


def test_pressure_curve_is_deterministic():
    kwargs = dict(competing_levels=(0, 10), age_levels=(50,),
                  importance_levels={"weak": 0.15}, top_k_levels=(5,))
    a = run_pressure_curve(**kwargs)
    b = run_pressure_curve(**kwargs)
    for pa, pb in zip(a["points"], b["points"]):
        assert (pa.policy, pa.competing, pa.coverage, pa.grounded) ==                (pb.policy, pb.competing, pb.coverage, pb.grounded)


# ------------------------------------------------------------ faithfulness
def test_faithfulness_identifies_the_decisive_record():
    report = evaluate_faithfulness()
    assert report.coverage > 0.9, "the planted decisive memory must be identified"
    assert report.lineage_correct, "ablation must follow lineage to derived summaries"


def test_faithfulness_scope_statement_is_explicit():
    """The module must not claim formal causality."""
    assert "not formal causal" in SCOPE_STATEMENT.lower()


# ---------------------------------------------------------- rater agreement
def test_jaccard_basic_properties():
    assert jaccard(["warm"], ["warm"]) == 1.0
    assert jaccard(["warm"], ["punitive"]) == 0.0
    assert jaccard(["warm", "neutral"], ["warm"]) == 0.5
    assert jaccard([], []) == 1.0


def test_fleiss_and_krippendorff_agree_on_clean_data():
    A = ["warm", "punitive", "warm", "neutral"]
    B = ["warm", "punitive", "warm", "neutral"]
    C = ["warm", "punitive", "neutral", "neutral"]
    fk = fleiss_kappa([A, B, C])
    ka = krippendorff_alpha_nominal([A, B, C])
    assert fk is not None and ka is not None
    assert abs(fk - ka) < 0.05


def test_degenerate_agreement_returns_none_not_one():
    """A single category means kappa is undefined; it must not be reported as 1."""
    assert fleiss_kappa([["warm"] * 4, ["warm"] * 4]) is None


def test_agreement_and_scoring_on_synthetic_raters_are_clearly_synthetic():
    """SYNTHETIC FIXTURE ONLY -- this is not human data and is never reported."""
    payload = {
        "cases": [
            {
                "case_id": "c1", "adjudicated_family": "warm",
                "raters": [
                    {"rater_id": "syn-a", "expected_families": ["warm"]},
                    {"rater_id": "syn-b", "expected_families": ["warm"]},
                ],
            },
            {
                "case_id": "c2", "adjudicated_family": "punitive",
                "raters": [
                    {"rater_id": "syn-a", "expected_families": ["punitive"]},
                    {"rater_id": "syn-b", "expected_families": ["neutral"]},
                ],
            },
        ]
    }
    agreement = evaluate_agreement(payload)
    assert agreement.cases == 2
    assert agreement.raters == 2
    assert agreement.mean_jaccard <= 1.0

    # predictions: one correct, one harmful (punitive where adjudicated warm)
    preds = {"c1": "refuse_trade", "c2": "arrest_player"}
    score = score_system(payload, preds)
    assert score.scored_cases == 2
    assert 0.0 <= score.accuracy <= 1.0
    assert score.harmful_action_rate >= 0.0


def test_harmful_action_rate_counts_punitive_when_none_accepted():
    payload = {
        "cases": [{
            "case_id": "c1", "adjudicated_family": "warm",
            "raters": [{"rater_id": "x", "expected_families": ["warm"]}],
        }]
    }
    score = score_system(payload, {"c1": "arrest_player"})
    assert score.harmful_action_rate == 1.0
    assert score.accuracy == 0.0


# ------------------------------------------------------------------ multiseed
def test_multiseed_preserves_per_seed_detail():
    result = run_multiseed(seeds=[1, 2, 3], include_baselines=False,
                           include_families_v06=True)
    for suite, methods in result["summary"].items():
        for method, row in methods.items():
            assert set(row["per_seed"].keys()) == {1, 2, 3}


def test_multiseed_full_architecture_never_loses():
    result = run_multiseed(seeds=[20260920 + i for i in range(3)],
                           include_baselines=True)
    for suite, cmp in result["comparisons"].items():
        for method, counts in cmp.items():
            assert counts["losses"] == 0, f"{suite}: SHM lost to {method}"
