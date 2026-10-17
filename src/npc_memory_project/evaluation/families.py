"""Multi-role scenario families for generalisation testing.

Why this module exists
---------------------
evaluation/harness.py generates the *Mira theft* case for the *shopkeeper*
role only. docs/EVALUATION.md limitation 3 is explicit: "every case is drawn
from the bundled Mira theft scenario vocabulary, so 'passes the suite' cannot be
generalised to other worlds or roles. The guard role is covered by two cases; no
other role is."

This module generalises the instrument without touching the original harness.
It builds the same three mechanisms -- accusation, exoneration, disputed claim --
across all five roles in decision/valid_actions.py (shopkeeper, guard, vendor,
suspect, villager), each with role-appropriate action families and retrieval
pressure from ambient noise.

Invariants
----------
Each scenario carries the invariants that are *well-defined for its role*:

A1  admissibility      The selected action is in the role's valid-action menu.
                       (AGENTS.md: every NPC action must pass the valid-action
                       layer.)
E1  exoneration        An ACTIVE exoneration suppresses punitive actions.
                       (Roles that have punitive actions only.)
C1  accusation         An ACTIVE theft belief with trust <= 0 suppresses warm
                       actions. (Roles with warm actions that a theft belief
                       should push away from.)
D1  disputed           A DISPUTED belief must not change behaviour: the decision
                       with it present matches the decision with it removed.

These are necessary conditions, not a behavioural specification -- same honesty
caveat as the original harness. The value here is *coverage*: a policy that only
works for one role now has to work for five.
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
    NPCState,
    WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.decision.valid_actions import valid_actions
from npc_memory_project.memory.manager import HierarchicalMemoryManager

#: Punitive / warm action sets, kept local so this module has no import cycle.
PUNITIVE = {"refuse_trade", "warn_player", "call_guard", "arrest_player"}
WARM = {"trade", "offer_discount", "apologise", "help_player"}


@dataclass(frozen=True)
class RoleProfile:
    role: str
    npc_id: str
    personality: Dict[str, float]
    inventory: Dict[str, int]
    location: str
    #: whether an accusation should push the NPC *away* from warm actions
    has_warm: bool
    #: whether the role can take a punitive action at all
    has_punitive: bool


ROLE_PROFILES: Dict[str, RoleProfile] = {
    "shopkeeper": RoleProfile(
        "shopkeeper", "mira", {"fairness": 0.9, "cautious": 0.7},
        {"medicine": 5, "bandage": 10}, "pharmacy", has_warm=True, has_punitive=True,
    ),
    "guard": RoleProfile(
        "guard", "kael", {"fairness": 0.9, "cautious": 0.8, "aggressive": 0.5},
        {"sword": 1}, "town_square", has_warm=False, has_punitive=True,
    ),
    "vendor": RoleProfile(
        "vendor", "arun", {"cautious": 0.4, "fairness": 0.6},
        {"apple": 10, "bread": 5}, "market", has_warm=True, has_punitive=True,
    ),
    "suspect": RoleProfile(
        "suspect", "rohan", {"remorse": 0.7, "cautious": 0.6},
        {"stolen_medicine": 1}, "alley", has_warm=False, has_punitive=False,
    ),
    "villager": RoleProfile(
        "villager", "tomas", {"fairness": 0.6, "cautious": 0.5},
        {}, "town_square", has_warm=True, has_punitive=True,
    ),
}


@dataclass
class FamilyScenario:
    seed: int
    role: str
    name: str
    npc: NPCState
    world: WorldState
    memories: List[MemoryRecord]
    invariants: Tuple[str, ...] = ()
    metadata: Dict[str, str] = field(default_factory=dict)


def _memory_from_event(
    manager: HierarchicalMemoryManager,
    *,
    event_type: str,
    actor: str,
    target: str,
    summary: str,
    claim: str,
    confidence: float,
    day: int,
    location: str,
    source: Optional[str] = None,
    relationship_impact: float = -0.7,
    emotional_impact: float = 0.8,
    quest_relevance: float = 0.3,
    novelty: float = 0.8,
) -> MemoryRecord:
    return manager.event_to_memory(GameEvent(
        event_type=event_type,
        actor=actor,
        target_npc=target,
        description=summary,
        game_day=day,
        location=location,
        emotional_impact=emotional_impact,
        relationship_impact=relationship_impact,
        quest_relevance=quest_relevance,
        novelty=novelty,
        source=source or actor,
        confidence=confidence,
        metadata={"conflict_key": "theft", "claim": claim},
    ))


def _noise(manager: HierarchicalMemoryManager, target: str, count: int,
           location: str, current_day: int, rng: random.Random) -> List[MemoryRecord]:
    out: List[MemoryRecord] = []
    for n in range(count):
        day = max(1, current_day - rng.choice([0, 1, 1, 2, 3]))
        out.append(manager.event_to_memory(GameEvent(
            event_type=rng.choice(["smalltalk", "weather", "errand", "market_chatter"]),
            actor="villager",
            target_npc=target,
            description=f"Passing remark {n} in the square.",
            game_day=day,
            location=location,
            emotional_impact=0.02,
            relationship_impact=0.01,
            quest_relevance=0.0,
            novelty=0.05,
            source="ambient",
            confidence=0.5,
            metadata={},
        )))
    return out


def build_family_scenarios(
    n_per_role: int = 12,
    *,
    seed: int = 20260920,
    roles: Optional[Sequence[str]] = None,
    exoneration_probability: float = 0.6,
    disputed_probability: float = 0.3,
) -> List[FamilyScenario]:
    """Generate scenarios across every role, with role-valid invariants."""
    rng = random.Random(seed)
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()

    active_roles = list(roles or ROLE_PROFILES.keys())
    scenarios: List[FamilyScenario] = []

    for role in active_roles:
        profile = ROLE_PROFILES[role]
        for i in range(n_per_role):
            day = rng.choice([4, 5, 6, 9, 14])
            trust = rng.choice([-40.0, -30.0, -10.0, 0.0, 10.0, 25.0])
            npc = NPCState(
                profile.npc_id, profile.role, trust,
                dict(profile.personality), dict(profile.inventory),
            )
            world = WorldState(day, profile.location,
                               player_has_money=True, player_wanted=False)

            memories: List[MemoryRecord] = []
            tags: List[str] = []
            invariants: List[str] = ["A1_admissible_action"]

            accusation = _memory_from_event(
                manager, event_type="theft_accusation", actor="arun",
                target=profile.npc_id,
                summary="Arun accused the player of stealing medicine.",
                claim="player_stole",
                confidence=round(rng.uniform(0.45, 0.75), 2),
                day=1, location=profile.location,
            )
            memories.append(accusation)
            tags.append("accusation")

            for w in range(rng.choice([0, 0, 1, 2])):
                memories.append(_memory_from_event(
                    manager, event_type="theft_accusation",
                    actor=f"vendor_{w}", target=profile.npc_id,
                    summary=f"Vendor {w} also reported the player stealing medicine.",
                    claim="player_stole",
                    confidence=round(rng.uniform(0.45, 0.8), 2),
                    day=2, location=profile.location,
                ))

            has_exoneration = rng.random() < exoneration_probability
            if has_exoneration:
                exoneration = _memory_from_event(
                    manager, event_type="innocence_verified", actor="kael",
                    target=profile.npc_id,
                    summary="The guard proved that Rohan, not the player, stole the medicine.",
                    claim="rohan_stole",
                    confidence=round(rng.uniform(0.85, 1.0), 2),
                    day=3, location=profile.location, source="guard",
                    relationship_impact=0.8, emotional_impact=0.9,
                    quest_relevance=0.6, novelty=0.9,
                )
                revised, exoneration = updater.revise(memories, exoneration)
                memories = list(revised) + [exoneration]
                tags.append("exoneration")
                if (exoneration.status == BeliefStatus.ACTIVE
                        and profile.has_punitive):
                    invariants.append("E1_exoneration_suppresses_punishment")

            has_disputed = rng.random() < disputed_probability
            if has_disputed:
                rumour = _memory_from_event(
                    manager, event_type="rumour_theft_accusation",
                    actor="drunkard", target=profile.npc_id,
                    summary="A drunkard claimed the player was seen near the shelf.",
                    claim="player_stole",
                    confidence=0.30, day=max(1, day - 1),
                    location=profile.location, source="hearsay_drunkard",
                )
                revised, rumour = updater.revise(memories, rumour)
                memories = list(revised) + [rumour]
                tags.append("disputed")
                if rumour.status == BeliefStatus.DISPUTED:
                    invariants.append("D1_disputed_changes_nothing")

            # Retrieval pressure: without enough ambient noise the decisive
            # record always survives top-k and *every* policy ties. Measured in
            # this suite: at [0,2,4,6,9] the baselines tie the full architecture;
            # at [6,10,14,18] recency-only drops to 93/113 while the full
            # architecture stays at 113/113. The pressure regime is the default so
            # the instrument discriminates. (The other baselines still tie -- see
            # docs/EVALUATION.md: only recency-only is separated at this scale.)
            memories += _noise(manager, profile.npc_id,
                               rng.choice([6, 10, 14, 18]), profile.location, day, rng)

            if (not has_exoneration and trust <= 0 and profile.has_warm
                    and any(m.event_type == "theft_accusation"
                            and m.status != BeliefStatus.SUPERSEDED
                            for m in memories)):
                invariants.append("C1_accusation_suppresses_warmth")

            scenarios.append(FamilyScenario(
                seed=seed + i,
                role=role,
                name=f"{role}:" + "+".join(tags),
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


def _check_invariant(
    invariant: str,
    scenario: FamilyScenario,
    action: str,
    engine: UtilityDecisionEngine,
    retriever: object,
    top_k: int,
) -> bool:
    if invariant == "A1_admissible_action":
        return action in valid_actions(scenario.npc, scenario.world)
    if invariant == "E1_exoneration_suppresses_punishment":
        return action not in PUNITIVE
    if invariant == "C1_accusation_suppresses_warmth":
        return action not in WARM
    if invariant == "D1_disputed_changes_nothing":
        without = [m for m in scenario.memories if m.status != BeliefStatus.DISPUTED]
        baseline = engine.decide(
            scenario.npc, scenario.world,
            retriever.retrieve(without, npc_id=scenario.npc.npc_id,
                               current_day=scenario.world.game_day, top_k=top_k),
        )
        return baseline.selected_action == action
    return True


def evaluate_families(
    scenarios: Sequence[FamilyScenario],
    *,
    retrieval: Optional[object] = None,
    top_k: int = 5,
) -> Dict[str, object]:
    """Run the multi-role family suite. Returns per-role and per-invariant counts."""
    manager = HierarchicalMemoryManager()
    retriever = retrieval or manager
    engine = UtilityDecisionEngine()

    per_invariant: Dict[str, List[bool]] = {}
    per_role: Dict[str, List[bool]] = {}
    failures: List[Dict[str, object]] = []
    actions_by_role: Dict[str, Dict[str, int]] = {}

    for scenario in scenarios:
        retrieved = retriever.retrieve(
            scenario.memories, npc_id=scenario.npc.npc_id,
            current_day=scenario.world.game_day, top_k=top_k,
        )
        trace = engine.decide(scenario.npc, scenario.world, retrieved)
        action = trace.selected_action
        counts = actions_by_role.setdefault(scenario.role, {})
        counts[action] = counts.get(action, 0) + 1

        for invariant in scenario.invariants:
            ok = _check_invariant(invariant, scenario, action, engine, retriever, top_k)
            per_invariant.setdefault(invariant, []).append(ok)
            per_role.setdefault(scenario.role, []).append(ok)
            if not ok:
                failures.append({
                    "seed": scenario.seed,
                    "role": scenario.role,
                    "scenario": scenario.name,
                    "invariant": invariant,
                    "action": action,
                    "retrieved": [m.event_type for m in retrieved],
                })

    total_checks = sum(len(v) for v in per_invariant.values())
    total_pass = sum(sum(1 for ok in v if ok) for v in per_invariant.values())

    def _rate(v: Sequence[bool]) -> float:
        return sum(1 for ok in v if ok) / len(v) if v else 1.0

    return {
        "scenarios": len(scenarios),
        "checks": total_checks,
        "passed": total_pass,
        "pass_rate": (total_pass / total_checks) if total_checks else 1.0,
        "per_invariant": {
            name: {"checks": len(v), "passed": sum(1 for ok in v if ok)}
            for name, v in per_invariant.items()
        },
        "per_role": {
            role: {"checks": len(v), "passed": sum(1 for ok in v if ok),
                   "rate": _rate(v)}
            for role, v in sorted(per_role.items())
        },
        "action_distribution": {
            role: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
            for role, counts in sorted(actions_by_role.items())
        },
        "failures": failures[:10],
    }
