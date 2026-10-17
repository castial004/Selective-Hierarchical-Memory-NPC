"""Explanation-faithfulness evaluation for the counterfactual verifier.

What this measures -- and does not
---------------------------------
The verifier (explainability/counterfactual.py) certifies a retrieved memory as
causal when ablating it (and its lineage) changes the selected action or moves the
top score. This module turns that into four numbers a paper can report:

* causal-memory PRECISION -- of the memories the verifier flags as factors, what
  share actually change the outcome when ablated? (By construction this should be
  1.0 for action-changing factors; the interesting cases are score-only factors,
  so we report both a strict and a lenient version.)
* causal-memory COVERAGE -- when a known decisive memory is planted, does the
  verifier identify it?
* explanation STABILITY -- across noise-perturbed histories, does the verifier
  keep identifying the same decisive fact?
* derived-memory CORRECTNESS -- does ablating a source remove the summaries
  derived from it (lineage), so the signal cannot leak through the summary?

CRITICAL SCOPE STATEMENT (must appear in any paper that cites these numbers):

    These are counterfactual-sensitivity measures of *memory contribution* under
    a deletion intervention ("the NPC forgot m"). They are NOT formal causal
    effect estimates, and they never ablate trust, personality or world state.
    See the scope note at the top of explainability/counterfactual.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import GameEvent, MemoryRecord, NPCState, WorldState
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import (
    CounterfactualExplanationVerifier, lineage_closure,
)
from npc_memory_project.memory.manager import HierarchicalMemoryManager

SCOPE_STATEMENT = (
    "These are counterfactual-sensitivity measures of memory contribution under a "
    "deletion intervention ('the NPC forgot m'), not formal causal-effect "
    "estimates. Trust, personality and world state are never ablated."
)


def _planted_case(seed: int, noise: int = 0):
    """A store with one known decisive exoneration plus optional noise."""
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()
    rng = random.Random(seed)

    accusation = manager.event_to_memory(GameEvent(
        event_type="theft_accusation", actor="arun", target_npc="mira",
        description="Arun accused the player of stealing medicine.",
        game_day=1, location="pharmacy", emotional_impact=0.8,
        relationship_impact=-0.7, quest_relevance=0.3, novelty=0.8,
        source="arun", confidence=0.6,
        metadata={"conflict_key": "theft", "claim": "player_stole"},
    ))
    exoneration = manager.event_to_memory(GameEvent(
        event_type="innocence_verified", actor="kael", target_npc="mira",
        description="The guard proved Rohan, not the player, stole the medicine.",
        game_day=3, location="pharmacy", emotional_impact=0.9,
        relationship_impact=0.8, quest_relevance=0.6, novelty=0.9,
        source="guard", confidence=0.95,
        metadata={"conflict_key": "theft", "claim": "rohan_stole"},
    ))
    revised, exoneration = updater.revise([accusation], exoneration)
    store = list(revised) + [exoneration]

    # a derived semantic belief, linked to its source
    semantic = updater.build_semantic_belief(
        npc_id="mira", event_id="sem-false-accusation",
        summary="The player was falsely accused of stealing medicine.",
        event_type="belief_player_falsely_accused", game_day=3,
        confidence=0.95, metadata={"claim": "player_falsely_accused"},
        derived_from=[exoneration.event_id],
    )
    store.append(semantic)

    for i in range(noise):
        day = 4 + rng.choice([0, 1, 1, 2])
        store.append(manager.event_to_memory(GameEvent(
            event_type="smalltalk", actor="villager", target_npc="mira",
            description=f"Passing remark {i}.", game_day=day, location="square",
            emotional_impact=0.1, relationship_impact=0.1, quest_relevance=0.1,
            novelty=0.1, source="ambient", confidence=0.5, metadata={},
        )))

    npc = NPCState("mira", "shopkeeper", 0.0, {"fairness": 0.9, "cautious": 0.7},
                   {"medicine": 5})
    world = WorldState(10, "pharmacy", True, False)
    return npc, world, store, exoneration.event_id, semantic.event_id


@dataclass
class FaithfulnessReport:
    precision_action: float
    precision_any: float
    coverage: float
    decisive_retrieved_rate: float
    stability_conditional: float
    stability_unconditional: float
    lineage_correct: bool
    detail: List[Dict[str, object]]


def _precision(engine, verifier, npc, world, retrieved):
    """Of the flagged factors, what fraction actually change outcome?"""
    evidence = verifier.verify_memories(npc, world, retrieved)
    flagged = [e for e in evidence if e.changed_action or abs(e.score_delta) > 1e-9]
    if not flagged:
        return 0.0, 0.0, []
    action_changers = sum(1 for e in flagged if e.changed_action)
    return action_changers / len(flagged), 1.0, flagged


def evaluate_faithfulness(
    *,
    seeds: Optional[Sequence[int]] = None,
    noise_levels: Sequence[int] = (0, 10, 30),
    top_k: int = 10,
) -> FaithfulnessReport:
    seeds = list(seeds or (20260920, 20260921, 20260922))
    manager = HierarchicalMemoryManager()
    engine = UtilityDecisionEngine()
    verifier = CounterfactualExplanationVerifier(engine)

    prec_action_hits = 0
    prec_action_n = 0
    coverage_hits = 0
    coverage_n = 0
    retrieved_hits = 0
    stability_cond_hits = 0
    stability_cond_n = 0
    stability_uncond_hits = 0
    stability_uncond_n = 0
    lineage_ok = True
    detail: List[Dict[str, object]] = []

    for seed in seeds:
        identified_per_noise: List[Optional[str]] = []
        for noise in noise_levels:
            npc, world, store, exo_id, sem_id = _planted_case(seed, noise)
            retrieved = manager.retrieve(store, npc_id="mira",
                                         current_day=world.game_day, top_k=top_k)
            evidence = verifier.verify_memories(npc, world, retrieved)
            flagged = [e for e in evidence if e.changed_action or abs(e.score_delta) > 1e-9]

            # precision (action-changing among flagged)
            if flagged:
                prec_action_hits += sum(1 for e in flagged if e.changed_action)
                prec_action_n += len(flagged)

            # was the decisive record even retrieved? (explanation cannot
            # identify a memory retrieval never surfaced)
            decisive_retrieved = any(m.event_id == exo_id for m in retrieved)
            retrieved_hits += 1 if decisive_retrieved else 0

            # coverage: is the planted exoneration among flagged factors?
            exon_flagged = [e for e in flagged if e.memory_id == exo_id]
            found = bool(exon_flagged)
            coverage_hits += 1 if found else 0
            coverage_n += 1
            identified_per_noise.append(
                {"found": found, "retrieved": decisive_retrieved}
            )

            # lineage correctness: ablation group of the exoneration must include
            # the derived semantic summary
            group = verifier.ablation_group(store, next(m for m in store if m.event_id == exo_id))
            if sem_id not in group:
                lineage_ok = False

            detail.append({
                "seed": seed, "noise": noise,
                "retrieved": len(retrieved),
                "flagged": len(flagged),
                "decisive_found": found,
                "lineage_group_size": len(group),
            })

        # stability has two honest definitions, both reported:
        #  * unconditional: identified at EVERY noise level (fails if the fact is
        #    ever unretrieved -- a retrieval property, not an explanation one)
        #  * conditional: among levels where the fact WAS retrieved, was it always
        #    identified? (the actual explanation-stability question)
        stability_uncond_n += 1
        if all(x["found"] for x in identified_per_noise):
            stability_uncond_hits += 1

        retrieved_levels = [x for x in identified_per_noise if x["retrieved"]]
        if retrieved_levels:
            stability_cond_n += 1
            if all(x["found"] for x in retrieved_levels):
                stability_cond_hits += 1

    return FaithfulnessReport(
        precision_action=(prec_action_hits / prec_action_n) if prec_action_n else 0.0,
        precision_any=1.0 if prec_action_n else 0.0,
        coverage=(coverage_hits / coverage_n) if coverage_n else 0.0,
        decisive_retrieved_rate=(retrieved_hits / coverage_n) if coverage_n else 0.0,
        stability_conditional=(stability_cond_hits / stability_cond_n) if stability_cond_n else 0.0,
        stability_unconditional=(stability_uncond_hits / stability_uncond_n) if stability_uncond_n else 0.0,
        lineage_correct=lineage_ok,
        detail=detail,
    )


def print_faithfulness(report: FaithfulnessReport) -> None:
    print("\nExplanation faithfulness (counterfactual sensitivity)\n")
    print(f"  causal-memory precision (action-changing / flagged) : {100*report.precision_action:.1f}%")
    print(f"  causal-memory precision (any score delta / flagged)  : {100*report.precision_any:.1f}%")
    print(f"  causal-memory coverage (decisive identified)         : {100*report.coverage:.1f}%")
    print(f"  decisive record retrieved (per noise level)          : {100*report.decisive_retrieved_rate:.1f}%")
    print(f"  explanation stability (conditional on retrieval)     : {100*report.stability_conditional:.1f}%")
    print(f"  explanation stability (unconditional, incl. misses)  : {100*report.stability_unconditional:.1f}%")
    print(f"  derived-memory lineage correctness                   : "
          f"{'PASS' if report.lineage_correct else 'FAIL'}")
    print()
    print("  SCOPE:", SCOPE_STATEMENT)
    print()
