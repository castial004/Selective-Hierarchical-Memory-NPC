"""Consolidation pressure curve: under what conditions does consolidation matter?

Why this module exists
---------------------
evaluation/consolidation_study.py proved existence: in ONE hand-chosen regime
(weak exoneration, heavy noise) consolidation raises decisive-fact coverage from
0/60 to 60/60. A single point is not a curve, and "it matters here" is not "it
matters when X". This module sweeps the variables the question actually depends
on and reports where each mechanism is load-bearing.

Swept independently
-------------------
* competing memories:  0, 5, 10, 20, 50, 100, 200, 500
* age of decisive evidence: 5, 20, 50, 100 days before the probe
* decisive-event importance: weak, medium, strong
* top-k: 3, 5, 10

Policies compared (the five the task asks for)
----------------------------------------------
1. recency-only
2. importance-only
3. status-aware, flat (no tiers)
4. hierarchical, no semantic consolidation
5. full hierarchical + semantic consolidation (SHM)

Metrics (all four the task asks for, plus footprint)
----------------------------------------------------
A. decision accuracy       -- correct action family selected?
B. decisive-feature coverage -- is the decisive feature in the retrieved set?
C. grounded-decision rate  -- correct AND grounded (not a lucky no-signal answer)
D. retrieval latency       -- measured, milliseconds
E. reachable count         -- how many records remain eligible for retrieval
F. footprint               -- chars of retrieved set vs stored history (proxy,
                              explicitly labelled a proxy -- no tokenizer bundled)

The decisive scenario here is the resolved conflict from consolidation_study:
an accusation + a WEAK exoneration (so the exoneration's importance is low and
noise can outrank it). Consolidation emits a semantic consensus record with high
importance that carries the innocence feature. Whether that record survives
top-k as competing memories grow is the whole question.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.features import features_of
from npc_memory_project.core.models import GameEvent, MemoryRecord, NPCState, WorldState
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.labelled import FAMILY
from npc_memory_project.memory.consolidation import SemanticConsolidator
from npc_memory_project.memory.manager import HierarchicalMemoryManager

COMPETING_LEVELS: Sequence[int] = (0, 5, 10, 20, 50, 100, 200, 500)
AGE_LEVELS: Sequence[int] = (5, 20, 50, 100)
IMPORTANCE_LEVELS: Dict[str, float] = {"weak": 0.15, "medium": 0.30, "strong": 0.55}
TOP_K_LEVELS: Sequence[int] = (3, 5, 10)


# ------------------------------------------------------------- store builders
def _conflict_store(
    *, npc_id: str, probe_day: int, age: int, exoneration_impact: float,
    competing: int, noise_impact: float, rng: random.Random,
) -> List[MemoryRecord]:
    """accusation + weak exoneration (resolved) + N competing recent memories."""
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()

    decisive_day = max(1, probe_day - age)
    accusation = manager.event_to_memory(GameEvent(
        event_type="theft_accusation", actor="arun", target_npc=npc_id,
        description="Arun accused the player of stealing medicine.",
        game_day=1, location="pharmacy", emotional_impact=0.8,
        relationship_impact=-0.7, quest_relevance=0.3, novelty=0.8,
        source="arun", confidence=0.6,
        metadata={"conflict_key": "theft", "claim": "player_stole"},
    ))
    exoneration = manager.event_to_memory(GameEvent(
        event_type="innocence_verified", actor="kael", target_npc=npc_id,
        description="The guard proved Rohan, not the player, stole the medicine.",
        game_day=decisive_day, location="pharmacy",
        emotional_impact=exoneration_impact,
        relationship_impact=exoneration_impact,
        quest_relevance=exoneration_impact, novelty=exoneration_impact,
        source="guard", confidence=0.95,
        metadata={"conflict_key": "theft", "claim": "rohan_stole"},
    ))
    revised, exoneration = updater.revise([accusation], exoneration)
    store = list(revised) + [exoneration]

    for i in range(competing):
        day = max(1, probe_day - rng.choice([0, 1, 1, 2, 3]))
        store.append(manager.event_to_memory(GameEvent(
            event_type=rng.choice(["smalltalk", "weather", "errand", "market_chatter"]),
            actor="villager", target_npc=npc_id,
            description=f"Ambient remark {i}.", game_day=day, location="square",
            emotional_impact=noise_impact, relationship_impact=noise_impact,
            quest_relevance=noise_impact, novelty=noise_impact,
            source="ambient", confidence=0.5, metadata={},
        )))
    return store


# ------------------------------------------------------------------- policies
class Recency:
    name = "recency-only"

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = [m for m in memories if m.npc_id == npc_id]
        held.sort(key=lambda m: (m.game_day, m.importance), reverse=True)
        return held[:top_k]


class Importance:
    name = "importance-only"

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = [m for m in memories if m.npc_id == npc_id]
        held.sort(key=lambda m: (m.importance, m.confidence), reverse=True)
        return held[:top_k]


class StatusFlat:
    name = "status-aware flat"

    def __init__(self) -> None:
        from npc_memory_project.evaluation.baselines import StatusAwareNoTiers
        self._p = StatusAwareNoTiers()

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        return self._p.retrieve(memories, npc_id=npc_id, current_day=current_day,
                                top_k=top_k)


class HierNoSemantic:
    name = "hierarchical, no consolidation"

    def __init__(self) -> None:
        self._m = HierarchicalMemoryManager()

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        return self._m.retrieve(memories, npc_id=npc_id, current_day=current_day,
                                top_k=top_k)


class HierWithConsolidation:
    name = "SHM (full + consolidation)"

    def __init__(self, threshold: int = 2) -> None:
        self._m = HierarchicalMemoryManager()
        self._c = SemanticConsolidator(consolidation_threshold=threshold)

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        consolidated = self._c.consolidate(memories, current_day, npc_id)
        return self._m.retrieve(consolidated, npc_id=npc_id,
                                current_day=current_day, top_k=top_k)


def _policies() -> List[object]:
    return [Recency(), Importance(), StatusFlat(), HierNoSemantic(),
            HierWithConsolidation()]


# -------------------------------------------------------------------- measure
def _covers(retrieved: Sequence[MemoryRecord], feature: str) -> bool:
    return any(feature in features_of(m) for m in retrieved)


def _chars(records: Sequence[MemoryRecord]) -> int:
    return sum(len(m.summary) for m in records)


def _reachable(store: Sequence[MemoryRecord], npc_id: str) -> int:
    """Records a decision could legally see (status + archive filter)."""
    from npc_memory_project.core.models import BeliefStatus, MemoryTier
    excluded = {BeliefStatus.SUPERSEDED, BeliefStatus.EXPIRED, BeliefStatus.DISPUTED}
    return sum(
        1 for m in store
        if m.npc_id == npc_id and m.status not in excluded and m.tier != MemoryTier.ARCHIVE
    )


@dataclass
class Point:
    policy: str
    competing: int
    age: int
    importance: str
    top_k: int
    accuracy: float
    coverage: float
    grounded: float
    latency_ms: float
    reachable: int
    retrieved_chars: int
    stored_chars: int


def _run_one(
    policy, *, npc, world, store, engine, top_k, competing, age, importance_label
) -> Point:
    start = time.perf_counter()
    retrieved = policy.retrieve(store, npc_id=npc.npc_id,
                                current_day=world.game_day, top_k=top_k)
    latency = (time.perf_counter() - start) * 1000

    action = engine.decide(npc, world, retrieved).selected_action
    family = FAMILY.get(action, "neutral")
    correct = family == "warm"          # exoneration resolved => expect warm
    covered = _covers(retrieved, "innocence")
    grounded = correct and covered

    return Point(
        policy=policy.name, competing=competing, age=age,
        importance=importance_label, top_k=top_k,
        accuracy=1.0 if correct else 0.0,
        coverage=1.0 if covered else 0.0,
        grounded=1.0 if grounded else 0.0,
        latency_ms=latency,
        reachable=_reachable(store, npc.npc_id),
        retrieved_chars=_chars(retrieved),
        stored_chars=_chars(store),
    )


def run_pressure_curve(
    *,
    competing_levels: Sequence[int] = COMPETING_LEVELS,
    age_levels: Sequence[int] = AGE_LEVELS,
    importance_levels: Dict[str, float] = IMPORTANCE_LEVELS,
    top_k_levels: Sequence[int] = TOP_K_LEVELS,
    seed: int = 20260920,
) -> Dict[str, object]:
    """Sweep competing-count x age x importance x top_k for every policy."""
    engine = UtilityDecisionEngine()
    npc = NPCState("mira", "shopkeeper", 0.0, {"fairness": 0.9, "cautious": 0.7},
                   {"medicine": 5})
    points: List[Point] = []

    for importance_label, impact in importance_levels.items():
        for age in age_levels:
            for competing in competing_levels:
                probe_day = age + 10
                rng = random.Random(seed + age + competing)
                noise_impact = 0.4
                store = _conflict_store(
                    npc_id="mira", probe_day=probe_day, age=age,
                    exoneration_impact=impact, competing=competing,
                    noise_impact=noise_impact, rng=rng,
                )
                world = WorldState(probe_day, "pharmacy", True, False)
                for top_k in top_k_levels:
                    for policy in _policies():
                        points.append(_run_one(
                            policy, npc=npc, world=world, store=store,
                            engine=engine, top_k=top_k, competing=competing,
                            age=age, importance_label=importance_label,
                        ))

    return {
        "points": points,
        "competing_levels": list(competing_levels),
        "age_levels": list(age_levels),
        "importance_levels": list(importance_levels),
        "top_k_levels": list(top_k_levels),
    }


def summarise_curve(result: Dict[str, object], *,
                    importance: str = "weak", age: int = 50,
                    top_k: int = 5) -> Dict[str, Dict[int, Dict[str, float]]]:
    """Pivot the curve into per-policy series for one (importance, age, top_k)."""
    out: Dict[str, Dict[int, Dict[str, float]]] = {}
    for p in result["points"]:  # type: ignore[assignment]
        if p.importance != importance or p.age != age or p.top_k != top_k:
            continue
        out.setdefault(p.policy, {})[p.competing] = {
            "accuracy": p.accuracy, "coverage": p.coverage,
            "grounded": p.grounded, "latency_ms": p.latency_ms,
            "reachable": p.reachable,
        }
    return out


def print_pressure_report(result: Dict[str, object], *,
                          importance: str = "weak", age: int = 50,
                          top_k: int = 5) -> None:
    series = summarise_curve(result, importance=importance, age=age, top_k=top_k)
    levels = result["competing_levels"]
    print(f"\nConsolidation pressure curve -- importance={importance}, "
          f"age={age}d, top_k={top_k}\n")
    print("  metric = decisive-feature coverage (is the decisive fact retrieved?)\n")
    header = "  " + f"{'policy':<30}" + "".join(f"{c:>7}" for c in levels)
    print(header)
    print("  " + "-" * (30 + 7 * len(levels)))
    for policy, by_count in series.items():
        row = f"  {policy:<30}" + "".join(
            f"{100 * by_count.get(c, {}).get('coverage', 0):>6.0f}%" for c in levels
        )
        print(row)
    print()
    print("  metric = grounded-decision rate (correct AND decisive fact retrieved)\n")
    print(header)
    print("  " + "-" * (30 + 7 * len(levels)))
    for policy, by_count in series.items():
        row = f"  {policy:<30}" + "".join(
            f"{100 * by_count.get(c, {}).get('grounded', 0):>6.0f}%" for c in levels
        )
        print(row)
    print()
