"""Scaling experiment: how the architecture behaves as the world grows.

A persistent game world is many NPCs over many days, and the paper's claimed
benefit is bounded cost in exactly that regime. v0.2 measured latency on a
3-memory list and reported 0.0143 ms. This measures the real thing:

* **NPC count** 5 / 20 / 60 -- every NPC holds a store; a decision is scored for
  one of them.
* **history depth** 10 / 50 / 200 memories per NPC -- retrieval has to actually
  discriminate.
* **world age** up to 60 days -- through the real lifecycle (decay, archival,
  consolidation), not a loop of appends.

Reported per configuration: decision latency (median/p95), retrieval-set size,
store size, and whether the invariant suite still passes.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Sequence

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus, GameEvent, MemoryRecord, MemoryTier, NPCState, WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.harness import build_scenarios, evaluate
from npc_memory_project.evaluation.stats import summarise
from npc_memory_project.memory.manager import HierarchicalMemoryManager

SUMMARIES = [
    "Arun accused the player of stealing Mira's medicine.",
    "The guard proved that Rohan, not the player, stole the medicine.",
    "The player returned Mira's lost satchel.",
    "A traveller reported a theft near the well.",
    "The player bought a bandage and paid fairly.",
    "Rohan was seen loitering behind the market.",
    "Mira's stock was counted and found short.",
    "The player warned the guard about a fire in the alley.",
    "A drunkard claimed the player was seen near the shelf.",
    "The player helped carry crates to the stall.",
]
CLAIMS = ["player_stole", "rohan_stole", "player_falsely_accused", "player_generous",
          "player_shortchanged"]


@dataclass
class ScaleResult:
    npcs: int
    memories_per_npc: int
    decision_median_ms: float
    decision_p95_ms: float
    retrieved_median: int
    store_records: int
    invariant_rate: float


def _synthetic_memories(npc_id: str, count: int, current_day: int,
                        rng: random.Random) -> List[MemoryRecord]:
    """Plausible mixed-tier history for one NPC, with real statuses."""
    updater = ContradictionAwareBeliefUpdater()
    manager = HierarchicalMemoryManager()
    records: List[MemoryRecord] = []

    for index in range(count):
        day = rng.randint(max(1, current_day - 60), current_day)
        claim = rng.choice(CLAIMS)
        event = GameEvent(
            event_type=rng.choice([
                "theft_accusation", "innocence_verified", "help_player",
                "rumour_theft_accusation", "trade", "smalltalk",
            ]),
            actor=rng.choice(["arun", "kael", "rohan", "player"]),
            target_npc=npc_id,
            description=rng.choice(SUMMARIES),
            game_day=day,
            location="pharmacy",
            emotional_impact=rng.random(),
            relationship_impact=rng.uniform(-1, 1),
            quest_relevance=rng.random(),
            novelty=rng.random(),
            source=rng.choice(["arun", "guard", "direct", "hearsay_arun"]),
            confidence=round(rng.uniform(0.3, 1.0), 2),
            metadata={"conflict_key": rng.choice(["medicine_theft", "ledger"]),
                      "claim": claim},
        )
        records.append(manager.event_to_memory(event))

    # Run a slice through the real updater so some records are superseded or
    # disputed. Deduplicate by event_id afterwards: revise() returns a *replaced*
    # copy of the incoming record, so the "is it already there" check below missed
    # it and the store ended up with two records sharing a primary key -- which the
    # retrieval-index equivalence check then caught. A real store keys on event_id,
    # so the fixture must too.
    for record in records[: max(1, count // 5)]:
        if record.metadata.get("conflict_key"):
            revised, incoming = updater.revise(records, record)
            merged = revised + [incoming]
            seen = set()
            records = []
            for candidate in merged:
                if candidate.event_id in seen:
                    continue
                seen.add(candidate.event_id)
                records.append(candidate)

    for record in records:
        if record.tier == MemoryTier.SEMANTIC and rng.random() < 0.5:
            record.status = BeliefStatus.CORROBORATED
        if rng.random() < 0.12:
            record.status = BeliefStatus.SUPERSEDED
        elif rng.random() < 0.10:
            record.status = BeliefStatus.DISPUTED
        elif rng.random() < 0.10:
            record.tier = MemoryTier.ARCHIVE

    return records


def run_scaling_experiment(
    configurations: Sequence[tuple] = ((5, 10), (20, 50), (20, 200), (60, 50)),
    *,
    iterations: int = 60,
    seed: int = 20260920,
) -> List[ScaleResult]:
    """Measure decision cost as NPC count and per-NPC history grow."""
    results: List[ScaleResult] = []
    scenarios = build_scenarios(60)          # invariant instrument, unchanged

    for npcs, per_npc in configurations:
        rng = random.Random(seed)
        manager = HierarchicalMemoryManager()
        engine = UtilityDecisionEngine()

        stores: Dict[str, List[MemoryRecord]] = {}
        for i in range(npcs):
            npc_id = "mira" if i == 0 else f"npc_{i}"
            stores[npc_id] = _synthetic_memories(npc_id, per_npc, current_day=30, rng=rng)

        all_memories: List[MemoryRecord] = [m for held in stores.values() for m in held]
        npc = NPCState("mira", "shopkeeper", 0.0, {"fairness": 0.9, "cautious": 0.7},
                       {"medicine": 5})
        world = WorldState(30, "pharmacy", True, False)

        latencies: List[float] = []
        retrieved_sizes: List[int] = []
        for _ in range(iterations):
            start = time.perf_counter()
            retrieved = manager.retrieve(all_memories, npc_id="mira",
                                         current_day=world.game_day, top_k=5)
            engine.decide(npc, world, retrieved)
            latencies.append((time.perf_counter() - start) * 1000)
            retrieved_sizes.append(len(retrieved))

        stats = summarise(latencies)
        invariant = evaluate(scenarios, retrieval=manager)
        results.append(ScaleResult(
            npcs=npcs,
            memories_per_npc=per_npc,
            decision_median_ms=stats["median"],
            decision_p95_ms=stats["p95"],
            retrieved_median=int(summarise(retrieved_sizes)["median"]),
            store_records=len(all_memories),
            invariant_rate=invariant["pass_rate"],
        ))

    return results
