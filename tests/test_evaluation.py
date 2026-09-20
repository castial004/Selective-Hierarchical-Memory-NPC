"""Tests for the research-validation layer.

These tests exist to stop the two failure modes this phase was created to fix:

1. **A results table that cannot be reproduced.** Every reported number comes from
   ``evaluation/report.py``; these tests run it.
2. **A comparison that does not compare.** It is easy to build baseline policies
   that look different and decide identically. ``test_baselines_actually_discriminate``
   is the guard: it fails if the baselines stop losing to the full architecture.

Nothing here asserts a *human* result. The labelled fixtures are either
author-labelled (``label_source="author"``) or synthetic and clearly marked as
code-path smoke tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.baselines import (
    ImportanceOnly, RecencyImportanceStatusBlind, RecencyOnly, StatusAwareNoTiers,
    TierAwareNoStatus, default_suite,
)
from npc_memory_project.evaluation.harness import build_scenarios, evaluate
from npc_memory_project.evaluation.labelled import (
    FAMILY, author_labelled_cases, run_labelled_suite,
)
from npc_memory_project.evaluation.report import (
    build_label_payload, main_table, score_against_labels,
)
from npc_memory_project.evaluation.stats import (
    cohens_kappa, cohens_kappa_is_degenerate, format_interval, paired_bootstrap,
    summarise, wilson_interval,
)
from npc_memory_project.memory.manager import HierarchicalMemoryManager

REPO_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------- statistics
def test_wilson_interval_is_sane_at_the_extremes():
    low, high = wilson_interval(21, 21)
    assert high == pytest.approx(1.0)
    assert 0.80 < low < 0.90          # 100% of 21 is not 100% of the population
    assert wilson_interval(0, 21)[0] == 0.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_shrinks_with_more_evidence():
    narrow = wilson_interval(210, 210)
    wide = wilson_interval(21, 21)
    assert narrow[0] > wide[0]


def test_format_interval_states_the_fraction_and_the_interval():
    text = format_interval(19, 21)
    assert "19/21" in text and "90.5%" in text and "CI" in text


def test_paired_bootstrap_detects_nothing_when_methods_agree():
    same = [True, False, True, True, False, True]
    result = paired_bootstrap(same, list(same), iterations=500)
    assert result["difference"] == 0.0
    assert result["low"] == 0.0 and result["high"] == 0.0


def test_paired_bootstrap_reports_an_advantage_with_a_positive_lower_bound():
    better = [True] * 20
    worse = [False] * 20
    result = paired_bootstrap(better, worse, iterations=500)
    assert result["difference"] == pytest.approx(1.0)
    assert result["low"] == pytest.approx(1.0)      # every resample agrees
    assert result["p_gt_zero"] == 1.0


def test_paired_bootstrap_spans_zero_for_a_single_flipped_case():
    a = [True] * 10
    b = [True] * 10
    b[0] = False
    result = paired_bootstrap(a, b, iterations=2000)
    assert result["difference"] == pytest.approx(0.1)
    assert result["low"] == 0.0                      # bootstrap resamples miss the flip
    assert "low" in result and "high" in result


def test_paired_bootstrap_rejects_unpaired_input():
    with pytest.raises(ValueError):
        paired_bootstrap([True], [True, False])


def test_cohens_kappa_matches_known_values():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)
    # raw agreement 4/5 = 0.8; chance agreement 0.48 + 0.08 = 0.56
    # kappa = (0.8 - 0.56) / (1 - 0.56) = 0.5455
    a = ["a", "a", "a", "a", "b"]
    b = ["a", "a", "a", "b", "b"]
    assert cohens_kappa(a, b) == pytest.approx(0.5455, abs=0.001)
    # degenerate input: one category only -> kappa undefined (0/0), reported as 1.0
    # and flagged, because a single-category sample carries no information
    assert cohens_kappa(["a", "a"], ["a", "a"]) == pytest.approx(1.0)
    assert cohens_kappa_is_degenerate(["a", "a"], ["a", "a"]) is True
    assert cohens_kappa_is_degenerate(["a", "b"], ["a", "b"]) is False


def test_summarise_reports_the_tail_not_just_the_mean():
    stats = summarise([1.0, 2.0, 3.0, 4.0, 100.0])
    assert stats["median"] == 3.0
    assert stats["max"] == 100.0
    assert stats["p95"] >= stats["median"]


# ----------------------------------------------------------------- baselines
def test_every_baseline_uses_the_manager_retrieval_signature():
    """The whole point: the harness runs them without knowing they are baselines."""
    import inspect

    signature = inspect.signature(HierarchicalMemoryManager.retrieve)
    for policy in default_suite():
        assert policy.name, "policy needs a name for the results table"
        params = inspect.signature(policy.retrieve).parameters
        for required in ("npc_id", "current_day", "top_k"):
            assert required in params, f"{policy.name} missing {required}"
            assert required in signature.parameters


def test_baselines_actually_discriminate():
    """Guard against a comparison table where every method behaves identically.

    On the first run of this suite all six methods scored 14/17 -- the labelled
    cases were too small for retrieval policy to matter. That is exactly the
    failure this test exists to catch.
    """
    full = run_labelled_suite(HierarchicalMemoryManager())
    scores = {policy.name: run_labelled_suite(policy)["correct"] for policy in default_suite()}

    assert full["correct"] == full["cases"], "the full architecture must pass its own suite"
    assert min(scores.values()) < full["correct"], (
        "every baseline ties the full architecture -- the case set no longer "
        "exercises retrieval policy (see tests for the memory-pressure cases)"
    )
    assert scores[RecencyOnly.name] < full["correct"]
    assert scores[TierAwareNoStatus.name] < full["correct"]


def test_status_filtering_is_load_bearing_and_tiers_are_not():
    """The measured negative result, asserted so future drift is visible.

    Removing belief-status filtering costs accuracy and invariant compliance.
    Removing the tier hierarchy costs nothing measurable on these instruments,
    because status filtering is what actually rejects superseded records. If a
    future change makes tiers measurable, this test fails and the docs must be
    updated -- that is the intent.
    """
    scenarios = build_scenarios(60)
    full = evaluate(scenarios, retrieval=HierarchicalMemoryManager())
    no_tiers = evaluate(scenarios, retrieval=StatusAwareNoTiers())
    no_status = evaluate(scenarios, retrieval=TierAwareNoStatus())

    assert full["passed"] == full["checks"] == 63
    assert no_tiers["passed"] == full["passed"]
    assert no_status["passed"] < full["passed"]

    labelled_full = run_labelled_suite(HierarchicalMemoryManager())
    labelled_no_status = run_labelled_suite(TierAwareNoStatus())
    assert labelled_no_status["correct"] < labelled_full["correct"]


def test_baselines_are_deterministic():
    first = run_labelled_suite(RecencyOnly())
    second = run_labelled_suite(RecencyOnly())
    assert [o["selected_action"] for o in first["outcomes"]] == \
           [o["selected_action"] for o in second["outcomes"]]


# ------------------------------------------------------- dangerous shopkeeper
def test_cautious_npc_without_a_threat_does_not_punish_the_player():
    """Regression: the v0.3.0 gate on the ``cautious`` weight.

    Before the fix, ``cautious`` contributed a flat bonus to refuse/warn/call_guard
    for any cautious NPC, so a shopkeeper with nothing on file still warned the
    player for walking in. Caught by the no-stock / no-money labelled cases.
    """
    cases = {c.case_id: c for c in author_labelled_cases()}
    engine = UtilityDecisionEngine()

    for case_id in ("no-stock-removes-trade", "no-money-removes-trade",
                    "fresh-npc-no-history"):
        case = cases[case_id]
        retrieved = HierarchicalMemoryManager().retrieve(
            case.memories, npc_id=case.npc.npc_id, current_day=case.world.game_day, top_k=5,
        )
        chosen = engine.decide(case.npc, case.world, retrieved)
        assert FAMILY.get(chosen.selected_action) != "punitive", (
            f"{case_id}: cautiousness alone produced {chosen.selected_action} "
            f"(scores: {[(s.action, s.score) for s in chosen.scores]})"
        )


def test_a_believed_accusation_still_closes_the_shop():
    """The gate must not have weakened the behaviour it was never meant to touch."""
    cases = {c.case_id: c for c in author_labelled_cases()}
    case = cases["active-accusation-blocks-trade"]
    retrieved = HierarchicalMemoryManager().retrieve(
        case.memories, npc_id=case.npc.npc_id, current_day=case.world.game_day, top_k=5,
    )
    chosen = UtilityDecisionEngine().decide(case.npc, case.world, retrieved)
    assert chosen.selected_action == "refuse_trade"


def test_cautious_only_fires_when_a_threat_is_retrieved():
    """The gate reads *presence* of a threat, not its magnitude."""
    engine = UtilityDecisionEngine()
    cases = {c.case_id: c for c in author_labelled_cases()}
    clean = cases["fresh-npc-no-history"]
    accused = cases["active-accusation-blocks-trade"]

    clean_retrieved = HierarchicalMemoryManager().retrieve(
        clean.memories, npc_id=clean.npc.npc_id, current_day=clean.world.game_day, top_k=5,
    )
    accused_retrieved = HierarchicalMemoryManager().retrieve(
        accused.memories, npc_id=accused.npc.npc_id, current_day=accused.world.game_day, top_k=5,
    )

    clean_scores = {s.action: s for s in engine.score_actions(clean.npc, clean.world, clean_retrieved)}
    accused_scores = {s.action: s for s in engine.score_actions(accused.npc, accused.world, accused_retrieved)}
    assert clean_scores["warn_player"].factors.get("cautious", 0.0) == 0.0
    assert accused_scores["warn_player"].factors.get("cautious", 0.0) > 0.0


# -------------------------------------------------------------------- report
def test_main_table_covers_every_method_with_an_interval():
    table = main_table(bootstrap_iterations=200)
    rows = table["rows"]
    assert len(rows) == 1 + len(default_suite())
    assert "author" in table["label_source"]
    for row in rows:
        assert row["labelled_total"] == 21
        low, high = row["labelled_ci"]
        # floating-point tolerance: the Wilson bound saturates at 0.999... for 21/21
        assert 0.0 <= low <= row["labelled_accuracy"] + 1e-9
        assert row["labelled_accuracy"] <= high + 1e-9 <= 1.0 + 1e-9
    assert "human" not in rows[0]["method"].lower()


def test_ablation_covers_components_and_every_feature_channel():
    from npc_memory_project.core.features import FEATURE_KEYS
    from npc_memory_project.evaluation.ablation import run_ablation_suite

    results = {r.name: r for r in run_ablation_suite()}
    assert results["full architecture"].accuracy == 1.0
    assert results["no status filter"].accuracy < 1.0
    for key in FEATURE_KEYS:
        assert f"feature off: {key}" in results
    assert results["feature off: theft"].accuracy < results["full architecture"].accuracy


def test_scaling_grows_with_the_store_but_stays_bounded_per_decision():
    from npc_memory_project.evaluation.scaling import run_scaling_experiment

    rows = run_scaling_experiment(((5, 10), (20, 200)), iterations=15)
    assert rows[0].store_records < rows[1].store_records
    assert rows[0].retrieved_median == 5 and rows[1].retrieved_median == 5
    assert rows[1].decision_median_ms >= rows[0].decision_median_ms
    assert rows[1].decision_p95_ms < 50.0        # must stay viable for a game loop


def test_exported_labels_are_annotatable_and_never_claim_to_be_human(tmp_path):
    payload = build_label_payload()
    assert payload["label_source"] == "author"
    assert "human" in payload["warning"].lower()
    assert len(payload["cases"]) == len(author_labelled_cases())

    case = payload["cases"][0]
    assert case["raters"] == []
    assert case["adjudicated_family"] is None
    assert case["author_label"]["expected_family"]
    # raters must see every memory, not a retrieval-pruned subset
    labelled = {c.case_id: c for c in author_labelled_cases()}[case["case_id"]]
    assert len(case["memories"]) == len(labelled.memories)
    assert all({"tier", "status", "confidence", "game_day"} <= set(m) for m in case["memories"])


def test_scoring_refuses_an_unannotated_file(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(build_label_payload()), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        score_against_labels(path)
    assert "protocol" in str(excinfo.value).lower() or "adjudicated" in str(excinfo.value).lower()


def test_scoring_an_annotated_file_reports_accuracy_ci_and_kappa(tmp_path):
    """End-to-end code-path check with synthetic raters.

    The raters here are generated to agree with the author labels on purpose, so
    the resulting accuracy is a smoke-test artefact only. It is NOT evidence about
    the system and must never be reported as a result.
    """
    payload = build_label_payload()
    for index, case in enumerate(payload["cases"]):
        truth = case["author_label"]["expected_family"]
        second = "neutral" if index % 7 == 0 else truth
        case["raters"] = [
            {"rater_id": "A", "expected_families": [truth]},
            {"rater_id": "B", "expected_families": [second]},
        ]
        case["adjudicated_family"] = truth
    path = tmp_path / "annotated.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = score_against_labels(path)
    assert result["scored_cases"] == len(payload["cases"])
    assert result["system_accuracy"] == 1.0
    assert result["system_ci"][1] == pytest.approx(1.0)
    assert result["inter_rater_kappa"] is not None
    assert 0.0 < result["inter_rater_kappa"] < 1.0
    assert len(result["labels_sha256"]) == 64


def test_preference_blocks_are_blind_and_the_key_is_separate():
    payload = build_label_payload(blind_retrieval=True)
    method_names = {p.name for p in default_suite()} | {"SHM (this architecture)"}

    for case in payload["cases"]:
        rater_view = case["rater_view"]
        assert len(rater_view) == len(method_names)
        rendered = json.dumps(rater_view)
        for name in method_names:
            assert name not in rendered, f"rater view leaks the method name {name!r}"
        assert set(case["facilitator_key"].values()) == method_names


def test_cli_help_and_module_entry_point_work():
    result = subprocess.run(
        [sys.executable, "-m", "npc_memory_project.evaluation.report", "--help"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    for flag in ("--ablation", "--scaling", "--export-labels", "--labels", "--preference",
                 "--invariants"):
        assert flag in result.stdout
