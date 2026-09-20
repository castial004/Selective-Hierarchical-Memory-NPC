"""Evaluation suite for the Selective Hierarchical Memory pipeline.

WHAT CHANGED IN v0.2.1
----------------------
v0.2 printed a "PASS" table whose assertions were the program's own outputs::

    pass4 = (top_action == "apologise" and abs(top_score - 0.581) < 0.05)
    pass5 = (flipped and abs(delta - 0.286) < 0.05)

so the reported "100% test pass rate (5/5)" could not fail, and the reported
"64.0% context footprint reduction" was arithmetic on hardcoded literals::

    working_count, episodic_count, semantic_count = 5, 3, 1
    flat_tokens, hierarchical_tokens = 25 * 45, (5 + 3 + 1) * 45

with no tokenizer, no store and no measurement anywhere in the computation.

This suite instead reports:

1. **Contract checks** -- pipeline behaviour, asserted as properties (e.g. "the
   exoneration must be the certified cause and ablating it must change the
   action") rather than as magic constants.
2. **Invariant suite** over ~60 seeded scenarios, plus the same suite run against
   a flat, status-blind memory stream as a baseline. This is the honest version
   of "the architecture works": a number that a broken implementation can fail.
3. **Latency by layer**, so the cost of retrieval, persistence and explanation is
   not hidden inside an isolated arithmetic call.
4. **Footprint measured** in bytes and in a documented whitespace-token proxy,
   on a real store, instead of assumed per-event token counts.

Nothing here is a peer-reviewable benchmark: it is one role, one scenario
family, hand-authored invariants and a proxy tokenizer. It is a floor, not a
result. See CHANGELOG-AUDIT.md.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus,
    GameEvent,
    MemoryRecord,
    MemoryTier,
    NPCState,
    WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.harness import (
    FlatMemoryRetrieval,
    build_scenarios,
    evaluate,
)
from npc_memory_project.explainability.counterfactual import CounterfactualExplanationVerifier
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.simulation.town_simulation import TownSimulation


def token_proxy(text: str) -> int:
    """Whitespace token count -- a *proxy*, not a tokenizer.

    Labelled honestly because v0.2 hardcoded "~45 tokens per raw event" and
    multiplied it out. Word count over-counts punctuation-attached tokens and
    under-counts subword splits; it is reported alongside raw bytes so the reader
    can judge, and is claimed to be nothing more than a size proxy.
    """
    return len(text.split())


# --------------------------------------------------------------------- part 1
def contract_checks() -> List[Dict[str, Any]]:
    """Behavioural properties the pipeline must satisfy. Computed, not asserted."""
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()
    engine = UtilityDecisionEngine()
    verifier = CounterfactualExplanationVerifier(engine)
    rows: List[Dict[str, Any]] = []

    high = manager.event_to_memory(GameEvent(
        "theft", "player", "mira", "Player stole medicine.", 1, "shop",
        0.9, -1.0, 0.5, 0.9, confidence=1.0,
    ))
    rows.append(_row(
        "High-impact admission",
        f"tier={high.tier.value}, I={high.importance:.3f}, theta_e={manager.episodic_threshold}",
        high.tier == MemoryTier.EPISODIC and high.importance >= manager.episodic_threshold,
    ))

    low = manager.event_to_memory(GameEvent(
        "greeting", "player", "mira", "Player said hello.", 1, "shop", 0.05, 0.05, 0.0, 0.05,
        confidence=1.0,
    ))
    rows.append(_row(
        "Low-impact admission",
        f"tier={low.tier.value}, I={low.importance:.3f}",
        low.tier == MemoryTier.WORKING,
    ))

    accusation = manager.event_to_memory(GameEvent(
        "theft_accusation", "arun", "mira", "Arun accused the player.", 1, "shop",
        0.8, -0.7, 0.3, 0.8, "arun", 0.60,
        {"conflict_key": "theft", "claim": "player"},
    ))
    exoneration = manager.event_to_memory(GameEvent(
        "innocence_verified", "guard", "mira", "Guard proved Rohan stole.", 3, "shop",
        0.9, 0.8, 0.6, 0.9, "guard", 0.95,
        {"conflict_key": "theft", "claim": "rohan"},
    ))
    revised, incoming = updater.revise([accusation], exoneration)
    rows.append(_row(
        "Belief conflict resolution",
        f"old={revised[0].status.value}, incoming={incoming.status.value}",
        revised[0].status == BeliefStatus.SUPERSEDED and incoming.status == BeliefStatus.ACTIVE,
    ))

    mira = NPCState("mira", "shopkeeper", 10.0, {"fairness": 0.9, "cautious": 0.7}, {"medicine": 5})
    world = WorldState(4, "pharmacy", True, False)
    semantic = updater.build_semantic_belief(
        npc_id="mira",
        event_id="semantic-false-accusation",
        summary="The player was falsely accused.",
        event_type="belief_player_falsely_accused",
        game_day=3,
        confidence=0.95,
        metadata={"conflict_key": "theft", "claim": "player_falsely_accused"},
        derived_from=[incoming.event_id],
    )
    retrieved = manager.retrieve([revised[0], incoming, semantic], npc_id="mira", current_day=4)
    trace = engine.decide(mira, world, retrieved)
    runner_up = trace.action_scores[1].score if len(trace.action_scores) > 1 else 0.0
    margin = trace.action_scores[0].score - runner_up
    rows.append(_row(
        "Utility action selection",
        f"'{trace.selected_action}' wins by {margin:+.3f} over '{trace.action_scores[1].action}'",
        trace.selected_action == "apologise" and margin > 0,
    ))

    evidence = verifier.verify_memories(mira, world, retrieved)
    top = evidence[0] if evidence else None
    rows.append(_row(
        "Counterfactual sensitivity",
        (f"ablating the exoneration lineage flips '{top.original_action}' -> "
         f"'{top.action_without_factor}', dU={top.score_delta:+.3f}") if top else "no evidence",
        bool(top and top.changed_action and top.score_delta > 0),
    ))

    return rows


def _row(name: str, observed: str, passed: bool) -> Dict[str, Any]:
    return {"check": name, "observed": observed, "status": "PASS" if passed else "FAIL"}


# --------------------------------------------------------------------- part 2
def invariant_suite(n_scenarios: int = 60) -> Dict[str, Any]:
    """Invariants over seeded scenarios, SHM vs a flat status-blind stream."""
    scenarios = build_scenarios(n_scenarios)
    shm = evaluate(scenarios)
    flat = evaluate(scenarios, retrieval=FlatMemoryRetrieval(top_k=5))
    return {"shm": shm, "flat_baseline": flat, "scenarios": scenarios}


# --------------------------------------------------------------------- part 3
def latency_by_layer(iterations: int = 1000) -> Dict[str, float]:
    """Measure where the time actually goes, end to end."""
    sim = TownSimulation()
    for _ in range(3):
        sim.advance_day()

    memories = sim.store.list_for_npc("mira")
    retrieved = sim.manager.retrieve(memories, npc_id="mira", current_day=sim.world.game_day, top_k=5)
    mira, world = sim.npcs["mira"], sim.world

    def bench(fn, n: int) -> float:
        start = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - start) / n * 1000.0

    engine_ms = bench(lambda: sim.engine.decide(mira, world, retrieved), iterations)
    retrieve_ms = bench(
        lambda: sim.engine.decide(
            mira, world,
            sim.manager.retrieve(
                sim.store.list_for_npc("mira"), npc_id="mira",
                current_day=sim.world.game_day, top_k=5,
            ),
        ),
        max(iterations // 4, 50),
    )
    full_ms = bench(lambda: sim.interact_with_npc("mira"), max(iterations // 20, 25))

    return {
        "engine_decide_only_ms": engine_ms,
        "store_read_retrieve_decide_ms": retrieve_ms,
        "full_interaction_ms": full_ms,
    }


# --------------------------------------------------------------------- part 4
def footprint_measurement(n_scenarios: int = 60) -> Dict[str, Any]:
    """Measure per-decision context cost: full store vs retrieved working set.

    Two measurements, both from real objects:

    * ``per_decision`` -- across every seeded scenario, the text of *all*
      memories the NPC holds vs the text of the top-5 actually retrieved for the
      decision. This is the quantity that matters for context cost.
    * ``session`` -- the bundled live simulation over several days, for
      continuity with the v0.2 printout (small, because that scenario is small).

    v0.2 reported a single 64.0% figure computed as ``1 - (405 / 1125)`` from
    hardcoded record counts and an assumed 45 tokens per event; nothing was
    measured.
    """
    manager = HierarchicalMemoryManager()
    scenarios = build_scenarios(n_scenarios)

    flat_chars = active_chars = 0
    flat_records = active_records = 0
    for scenario in scenarios:
        retrieved = manager.retrieve(
            scenario.memories, npc_id="mira", current_day=scenario.world.game_day, top_k=5
        )
        flat_chars += sum(len(m.summary) for m in scenario.memories)
        active_chars += sum(len(m.summary) for m in retrieved)
        flat_records += len(scenario.memories)
        active_records += len(retrieved)

    # live-session measurement
    sim = TownSimulation()
    for _ in range(6):
        sim.advance_day()
    session_all: List[MemoryRecord] = []
    session_active: List[MemoryRecord] = []
    for npc_id in sim.npcs:
        held = sim.store.list_for_npc(npc_id)
        session_all.extend(held)
        session_active.extend(manager.retrieve(
            held, npc_id=npc_id, current_day=sim.world.game_day, top_k=5
        ))
    session_flat_chars = sum(len(m.summary) for m in session_all)
    session_active_chars = sum(len(m.summary) for m in session_active)

    def pct(before: int, after: int) -> float:
        return (1 - after / before) * 100 if before else 0.0

    return {
        "per_decision": {
            "scenarios": len(scenarios),
            "held_records": flat_records,
            "retrieved_records": active_records,
            "held_chars": flat_chars,
            "retrieved_chars": active_chars,
            "held_tokens_proxy": token_proxy("x " * flat_chars),
            "retrieved_tokens_proxy": token_proxy("x " * active_chars),
            "char_reduction_pct": pct(flat_chars, active_chars),
        },
        "session": {
            "days": 6,
            "held_records": len(session_all),
            "retrieved_records": len(session_active),
            "held_chars": session_flat_chars,
            "retrieved_chars": session_active_chars,
            "char_reduction_pct": pct(session_flat_chars, session_active_chars),
        },
    }


# --------------------------------------------------------------------- driver
def run_paper_benchmark(
    n_scenarios: int = 60,
    iterations: int = 1000,
    *,
    json_out: Optional[str | Path] = None,
) -> Dict[str, Any]:
    print("=" * 78)
    print("   EVALUATION SUITE: SELECTIVE HIERARCHICAL MEMORY (v0.2.1)")
    print("=" * 78)

    checks = contract_checks()
    print("\n--- SECTION 1: PIPELINE CONTRACT CHECKS (properties, not magic numbers) ---")
    for row in checks:
        print(f"[{row['status']}] {row['check']:<28} | {row['observed']}")

    suite = invariant_suite(n_scenarios)
    shm, flat = suite["shm"], suite["flat_baseline"]
    print(f"\n--- SECTION 2: INVARIANT SUITE over {shm['scenarios']} seeded scenarios ---")
    print(f"{'invariant':<44}{'SHM':>10}{'flat baseline':>16}")
    for name in sorted(shm["per_invariant"]):
        s = shm["per_invariant"][name]
        f = flat["per_invariant"].get(name, {"checks": 0, "passed": 0})
        print(f"{name:<44}{s['passed']:>4}/{s['checks']:<5}{f['passed']:>10}/{f['checks']:<5}")
    print(f"{'TOTAL':<44}{shm['passed']:>4}/{shm['checks']:<5}{flat['passed']:>10}/{flat['checks']:<5}")
    print(f"  SHM pass rate {shm['pass_rate'] * 100:.1f}%   "
          f"flat-stream baseline {flat['pass_rate'] * 100:.1f}%")
    print(f"  actions chosen (SHM): {shm['action_distribution']}")
    if shm["failures"]:
        print("  first failures:")
        for failure in shm["failures"][:3]:
            print(f"    seed {failure['seed']} [{failure['scenario']}] {failure['invariant']} "
                  f"-> {failure['action']}")

    latency = latency_by_layer(iterations)
    print("\n--- SECTION 3: LATENCY BY LAYER (ms, mean) ---")
    for label, key in (
        ("engine.decide() only (no I/O)", "engine_decide_only_ms"),
        ("store read + retrieve + decide", "store_read_retrieve_decide_ms"),
        ("full interaction (I/O + ablation + dialogue)", "full_interaction_ms"),
    ):
        print(f"  {label:<46} {latency[key]:.4f}")

    footprint = footprint_measurement()
    per_decision = footprint["per_decision"]
    session = footprint["session"]
    print("\n--- SECTION 4: FOOTPRINT (measured) ---")
    print(f"  per decision, {per_decision['scenarios']} scenarios: "
          f"{per_decision['held_records']} held records -> "
          f"{per_decision['retrieved_records']} retrieved")
    print(f"    characters {per_decision['held_chars']} -> {per_decision['retrieved_chars']} "
          f"({per_decision['char_reduction_pct']:.1f}% reduction)")
    print(f"  live session, {session['days']} days: "
          f"{session['held_records']} held -> {session['retrieved_records']} retrieved, "
          f"{session['held_chars']} -> {session['retrieved_chars']} chars "
          f"({session['char_reduction_pct']:.1f}% reduction)")
    print("  NOTE: characters and a whitespace-token proxy only -- no real tokenizer is")
    print("        bundled. v0.2 reported 64.0% from hardcoded '45 tokens/event'.")

    print("\n--- WHAT THIS SUITE DOES NOT ESTABLISH ---")
    print("  * one NPC role, one scenario family, hand-authored invariants")
    print("  * no human playtest ground truth; no comparison to an LLM memory baseline")
    print("  * footprint is text size, not context-window or GPU memory cost")
    print("=" * 78)

    report = {
        "contract_checks": checks,
        "invariants": {"shm": shm, "flat_baseline": flat},
        "latency_ms": latency,
        "footprint": footprint,
    }
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report written to {json_out}")
    return report


if __name__ == "__main__":
    run_paper_benchmark()
