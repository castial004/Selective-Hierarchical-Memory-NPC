"""Seeded scenario generation and property-based invariants for evaluation.

Why this module exists
----------------------
v0.2's ``benchmark.py`` could not fail. Its checks were::

    pass4 = (top_action == "apologise" and abs(top_score - 0.581) < 0.05)
    pass5 = (flipped and abs(delta - 0.286) < 0.05)

-- i.e. the program asserting its own output -- and its headline "64.0% context
footprint reduction" was arithmetic on literals with no tokenizer and no store::

    working_count, episodic_count, semantic_count = 5, 3, 1
    reduction_pct = 1 - (405 / 1125)          # 64.0%, always

This harness replaces self-assertion with *invariants that a broken system can
fail*: properties every correct implementation must satisfy, evaluated over many
seeded scenarios, plus a flat-memory baseline to measure what belief-status
filtering actually buys.

Invariants (shopkeeper role; scenario vocabulary is the Mira theft case):

I1  If an ACTIVE exonerating belief is available, the NPC must not choose a
    punitive action (refuse_trade / warn_player / call_guard / arrest_player).
I2  If an ACTIVE theft belief exists and trust is not positive, the NPC must not
    offer a warm action (trade / offer_discount / apologise). Scoped to
    ``trust <= 0`` deliberately: a system that trades with a trusted customer
    despite an old accusation is making a policy trade-off, not committing an
    error, and asserting otherwise would encode opinion rather than correctness.
I3  A belief the updater marked DISPUTED must not change behaviour: decisions
    with a disputed belief present must match the no-belief baseline exactly.

Scenarios also carry ambient "noise" memories so retrieval pressure is real: a
stream that ignores belief status is expected to surface stale or contested
records once recent trivia competes for the same top-k slots.

These are necessary conditions, not a full behavioural specification -- passing
them does not prove the policy is *good*, only that it is not obviously wrong.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

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
from npc_memory_project.memory.manager import HierarchicalMemoryManager

PUNITIVE_ACTIONS = {"refuse_trade", "warn_player", "call_guard", "arrest_player"}
WARM_ACTIONS = {"trade", "offer_discount", "apologise"}


@dataclass
class Scenario:
    """One generated day-N decision situation for the shopkeeper benchmark."""

    seed: int
    name: str
    npc: NPCState
    world: WorldState
    memories: List[MemoryRecord]
    expected: Dict[str, bool] = field(default_factory=dict)
    #: which invariant the scenario exercises
    invariants: Tuple[str, ...] = ()


def _event(
    *,
    event_type: str,
    actor: str,
    summary: str,
    claim: str,
    confidence: float,
    day: int,
    source: Optional[str] = None,
    relationship_impact: float = -0.7,
    emotional_impact: float = 0.8,
    quest_relevance: float = 0.3,
    novelty: float = 0.8,
) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        actor=actor,
        target_npc="mira",
        description=summary,
        game_day=day,
        location="pharmacy",
        emotional_impact=emotional_impact,
        relationship_impact=relationship_impact,
        quest_relevance=quest_relevance,
        novelty=novelty,
        source=source or actor,
        confidence=confidence,
        metadata={"conflict_key": "medicine_theft", "claim": claim},
    )


def build_scenarios(
    n: int = 60,
    *,
    seed: int = 20260920,
    exoneration_probability: float = 0.6,
    disputed_probability: float = 0.25,
) -> List[Scenario]:
    """Generate ``n`` seeded scenarios covering the invariants above."""
    rng = random.Random(seed)
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()
    scenarios: List[Scenario] = []

    for i in range(n):
        day = rng.choice([4, 5, 6, 9, 14])
        trust = rng.choice([-40.0, -30.0, -10.0, 0.0, 10.0, 25.0])
        npc = NPCState(
            "mira",
            "shopkeeper",
            trust,
            {"fairness": rng.choice([0.5, 0.7, 0.9]), "cautious": rng.choice([0.4, 0.7])},
            {"medicine": rng.choice([0, 3, 5])},
        )
        world = WorldState(day, "pharmacy", player_has_money=True, player_wanted=False)

        memories: List[MemoryRecord] = []
        statements: List[str] = []
        invariants: List[str] = []

        # --- accusation, possibly corroborated by independent witnesses -------
        accusation = manager.event_to_memory(_event(
            event_type="theft_accusation",
            actor="arun",
            summary="Arun accused the player of stealing Mira's medicine.",
            claim="player_stole",
            confidence=round(rng.uniform(0.45, 0.75), 2),
            day=1,
        ))
        memories.append(accusation)
        statements.append("accusation")

        for w in range(rng.choice([0, 0, 1, 2])):
            witness = manager.event_to_memory(_event(
                event_type="theft_accusation",
                actor=f"vendor_{w}",
                summary=f"Vendor {w} also reported the player stealing medicine.",
                claim="player_stole",
                confidence=round(rng.uniform(0.45, 0.8), 2),
                day=2,
            ))
            memories.append(witness)

        # --- exoneration ----------------------------- -------------------------
        has_exoneration = rng.random() < exoneration_probability
        if has_exoneration:
            exoneration = manager.event_to_memory(_event(
                event_type="innocence_verified",
                actor="kael",
                summary="The guard proved that Rohan, not the player, stole the medicine.",
                claim="rohan_stole",
                confidence=round(rng.uniform(0.85, 1.0), 2),
                day=3,
                source="guard",
                relationship_impact=0.8,
                emotional_impact=0.9,
                quest_relevance=0.6,
                novelty=0.9,
            ))
            memories, exoneration = updater.revise(memories, exoneration)
            memories = list(memories) + [exoneration]
            statements.append("exoneration")
            if exoneration.status == BeliefStatus.ACTIVE:
                invariants.append("I1_exoneration_suppresses_punishment")

        # --- a disputed claim from a low-confidence rumour --------------------
        has_disputed = rng.random() < disputed_probability
        if has_disputed:
            rumour = manager.event_to_memory(_event(
                event_type="rumour_theft_accusation",
                actor="drunkard",
                summary="A drunkard claimed the player was seen near the medicine shelf.",
                claim="player_stole",
                confidence=0.30,
                day=day - 1,
                source="hearsay_drunkard",
            ))
            revised, rumour = updater.revise(memories, rumour)
            memories = revised + [rumour]
            if rumour.status == BeliefStatus.DISPUTED:
                invariants.append("I3_disputed_changes_nothing")
            statements.append("disputed_rumour")

        # --- ambient noise: recent, low-importance trivia ---------------------
        # Without this, top-k retrieval returns everything relevant and a
        # status-blind stream looks as good as a selective one. Real sessions do
        # not have that luxury.
        for n in range(rng.choice([0, 2, 4, 6, 9, 12])):
            noise_day = max(1, day - rng.choice([0, 1, 1, 2, 3]))
            memories.append(manager.event_to_memory(GameEvent(
                event_type=rng.choice(["smalltalk", "weather", "errand", "market_chatter"]),
                actor="villager",
                target_npc="mira",
                description=f"Passing remark {n} in the square.",
                game_day=noise_day,
                location="town_square",
                emotional_impact=0.02,
                relationship_impact=0.01,
                quest_relevance=0.0,
                novelty=0.05,
                source="ambient",
                confidence=0.5,
                metadata={},
            )))
        if memories and any(m.event_type in {"smalltalk", "weather", "errand", "market_chatter"}
                            for m in memories):
            statements.append("noise")

        if (not has_exoneration
                and trust <= 0
                and any(m.event_type == "theft_accusation"
                        and m.status != BeliefStatus.SUPERSEDED for m in memories)):
            invariants.append("I2_accusation_suppresses_warmth")

        scenarios.append(Scenario(
            seed=seed + i,
            name="+".join(statements),
            npc=npc,
            world=world,
            memories=_dedupe(memories),
            invariants=tuple(invariants),
        ))

    return scenarios


def _dedupe(memories: Sequence[MemoryRecord]) -> List[MemoryRecord]:
    seen: Dict[str, MemoryRecord] = {}
    for m in memories:
        seen[m.event_id] = m
    return list(seen.values())


# ------------------------------------------------------------------ retrieval
class FlatMemoryRetrieval:
    """Baseline: most-recent-k memories, no status filtering, no tiers.

    This is the naive stream the architecture argues against. Running the same
    invariants against it measures what contradiction tracking and tiering buy.
    """

    def __init__(self, top_k: int = 5) -> None:
        self.top_k = top_k

    def retrieve(self, memories: Sequence[MemoryRecord], *, npc_id: str,
                 current_day: int, **_: object) -> List[MemoryRecord]:
        candidates = [m for m in memories if m.npc_id == npc_id]
        candidates.sort(key=lambda m: (m.game_day, m.importance), reverse=True)
        return candidates[: self.top_k]


# ------------------------------------------------------------------ scoring
def evaluate(
    scenarios: Sequence[Scenario],
    *,
    retrieval: Optional[object] = None,
    top_k: int = 5,
) -> Dict[str, object]:
    """Run the invariant suite. Returns per-invariant and overall pass counts."""
    manager = HierarchicalMemoryManager()
    retriever = retrieval or manager
    engine = UtilityDecisionEngine()

    per_invariant: Dict[str, List[bool]] = {}
    failures: List[Dict[str, object]] = []
    actions: Dict[str, int] = {}

    for scenario in scenarios:
        retrieved = retriever.retrieve(
            scenario.memories, npc_id="mira", current_day=scenario.world.game_day, top_k=top_k
        )
        trace = engine.decide(scenario.npc, scenario.world, retrieved)
        action = trace.selected_action
        actions[action] = actions.get(action, 0) + 1

        for invariant in scenario.invariants:
            if invariant == "I1_exoneration_suppresses_punishment":
                ok = action not in PUNITIVE_ACTIONS
            elif invariant == "I2_accusation_suppresses_warmth":
                ok = action not in WARM_ACTIONS
            elif invariant == "I3_disputed_changes_nothing":
                # compare against the same scenario with the disputed record removed
                without = [m for m in scenario.memories if m.status != BeliefStatus.DISPUTED]
                baseline = engine.decide(
                    scenario.npc, scenario.world,
                    retriever.retrieve(without, npc_id="mira",
                                       current_day=scenario.world.game_day, top_k=top_k),
                )
                ok = baseline.selected_action == action
            else:
                ok = True

            per_invariant.setdefault(invariant, []).append(ok)
            if not ok:
                failures.append({
                    "seed": scenario.seed,
                    "scenario": scenario.name,
                    "invariant": invariant,
                    "action": action,
                    "retrieved": [m.event_type for m in retrieved],
                })

    total_checks = sum(len(v) for v in per_invariant.values())
    total_pass = sum(sum(1 for ok in v if ok) for v in per_invariant.values())
    return {
        "scenarios": len(scenarios),
        "checks": total_checks,
        "passed": total_pass,
        "pass_rate": (total_pass / total_checks) if total_checks else 1.0,
        "per_invariant": {
            name: {"checks": len(v), "passed": sum(1 for ok in v if ok)}
            for name, v in per_invariant.items()
        },
        "action_distribution": dict(sorted(actions.items(), key=lambda kv: -kv[1])),
        "failures": failures[:10],
    }
