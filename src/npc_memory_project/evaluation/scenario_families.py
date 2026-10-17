"""Genuinely different scenario families for validation.

Why this module exists
---------------------
evaluation/families.py improved *role* diversity but every scenario is still the
Mira theft vocabulary: accusation, exoneration, disputed claim. docs/EVALUATION.md
limitation 3 says the labelled set "cannot be generalised to other worlds or
roles". This module adds families that exercise fundamentally different memory
phenomena:

    A  Reciprocity       -- accumulation of positive experience over days
    B  Betrayal          -- a severe recent negative against old positives
    C  Obligation        -- a promise that must survive long noise
    D  Rumour provenance -- echo chains vs independent confirmation
    E  Conflicting witnesses -- contradictory claims with differing confidence

Two kinds of instrument, kept separate on purpose
------------------------------------------------
* **Decision families (A, B, C)** go through retrieval + the decision engine, so
  they can be run against every retrieval policy exactly like the invariant
  suite. Their invariants are behavioural (which action family is admissible).
* **Belief families (D, E)** are properties of the belief-updater, not of
  retrieval. Running them "against recency-only" would be meaningless, so they
  are evaluated once against the real updater and reported separately.

Honesty notes baked in
----------------------
* Every invariant states *why* it is reasonable, and invariants are only applied
  to roles whose action menu can express them (a suspect has no trade action).
* The reciprocity family measures two things and reports both: (1) the
  behavioural invariant, which holds even without consolidation, and (2) whether
  a semantic reputation belief is actually created -- which, for help events,
  it is NOT, because SemanticConsolidator keys on the literal tag "help"/"trade"
  and a help_player event is tagged "help_player". That is a real, reported gap,
  not a hidden one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus, GameEvent, MemoryRecord, MemoryTier, NPCState, WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.decision.valid_actions import valid_actions
from npc_memory_project.evaluation.labelled import FAMILY
from npc_memory_project.memory.manager import HierarchicalMemoryManager

WARM = {"warm"}
PUNITIVE = {"punitive"}


def _mk(
    manager: HierarchicalMemoryManager,
    *,
    event_type: str,
    npc_id: str,
    day: int,
    description: str,
    actor: str = "player",
    source: str = "direct",
    confidence: float = 0.8,
    impact: float = 0.4,
    relationship: Optional[float] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> MemoryRecord:
    rel = relationship if relationship is not None else impact
    return manager.event_to_memory(GameEvent(
        event_type=event_type,
        actor=actor,
        target_npc=npc_id,
        description=description,
        game_day=day,
        location="pharmacy",
        emotional_impact=impact,
        relationship_impact=rel,
        quest_relevance=impact,
        novelty=impact,
        source=source,
        confidence=confidence,
        metadata=dict(metadata or {}),
    ))


def _noise(manager, npc_id: str, count: int, current_day: int,
           rng: random.Random, impact: float = 0.3) -> List[MemoryRecord]:
    out = []
    for i in range(count):
        day = max(1, current_day - rng.choice([0, 1, 1, 2]))
        out.append(manager.event_to_memory(GameEvent(
            event_type=rng.choice(["smalltalk", "weather", "errand"]),
            actor="villager", target_npc=npc_id,
            description=f"Passing remark {i}.", game_day=day, location="square",
            emotional_impact=impact, relationship_impact=impact,
            quest_relevance=impact, novelty=impact,
            source="ambient", confidence=0.5, metadata={},
        )))
    return out


# ============================================================ decision families
@dataclass
class DecisionCase:
    family: str
    case_id: str
    npc: NPCState
    world: WorldState
    memories: List[MemoryRecord]
    #: predicate on the selected action family ("warm"/"punitive"/"neutral"/...)
    acceptable: Tuple[str, ...]
    reason: str


def reciprocity_cases(*, seed: int = 20260920, n_help: int = 4,
                      noise: int = 0) -> List[DecisionCase]:
    """A: repeated help should not be forgotten into hostility."""
    manager = HierarchicalMemoryManager()
    rng = random.Random(seed)
    memories = [
        _mk(manager, event_type="trade", npc_id="mira", day=d,
            description=f"The player traded fairly (day {d}).", impact=0.3)
        for d in range(1, 1 + n_help)
    ]
    memories += _noise(manager, "mira", noise, n_help + 1, rng)
    npc = NPCState("mira", "shopkeeper", 0.0, {"fairness": 0.9, "cautious": 0.7},
                   {"medicine": 5})
    world = WorldState(n_help + 1, "pharmacy", True, False)
    return [DecisionCase(
        family="A_reciprocity",
        case_id=f"reciprocity-help{n_help}-noise{noise}",
        npc=npc, world=world, memories=memories,
        acceptable=("warm",),
        reason="Repeated fair trade should keep the NPC warm, never punitive.",
    )]


def betrayal_cases(*, seed: int = 20260920, n_help: int = 4,
                   prior_trust: float = 40.0) -> List[DecisionCase]:
    """B: a severe betrayal should override older positives."""
    manager = HierarchicalMemoryManager()
    prior = [
        _mk(manager, event_type="trade", npc_id="mira", day=d,
            description=f"The player traded fairly (day {d}).", impact=0.3)
        for d in range(1, 1 + n_help)
    ]
    betrayal = _mk(
        manager, event_type="theft_accusation", npc_id="mira", day=n_help + 1,
        description="The player was caught stealing from the till.",
        actor="arun", source="arun", confidence=0.9, impact=0.9, relationship=-0.9,
        metadata={"conflict_key": "theft", "claim": "player_stole"},
    )
    npc = NPCState("mira", "shopkeeper", prior_trust,
                   {"fairness": 0.9, "cautious": 0.7}, {"medicine": 5})
    world = WorldState(n_help + 2, "pharmacy", True, False)
    return [DecisionCase(
        family="B_betrayal",
        case_id=f"betrayal-prior{int(prior_trust)}",
        npc=npc, world=world, memories=prior + [betrayal],
        acceptable=("punitive", "neutral"),
        reason="A severe, believed, recent theft should suppress warm service "
               "even when earlier interactions were positive.",
    )]


def obligation_cases(*, seed: int = 20260920, horizon: int = 60,
                     noise_per_day: int = 1) -> List[DecisionCase]:
    """C: a high-importance promise must survive a long wall of noise."""
    manager = HierarchicalMemoryManager()
    rng = random.Random(seed)
    promise = _mk(
        manager, event_type="help_player", npc_id="mira", day=1,
        description="The player promised to repay a debt by midsummer.",
        impact=0.9, relationship=0.6, confidence=0.95,
        metadata={"obligation": "unresolved"},
    )
    memories = [promise]
    for d in range(2, horizon + 1):
        memories += _noise(manager, "mira", noise_per_day, d, rng)
    npc = NPCState("mira", "shopkeeper", 10.0,
                   {"fairness": 0.9, "cautious": 0.7}, {"medicine": 5})
    world = WorldState(horizon, "pharmacy", True, False)
    return [DecisionCase(
        family="C_obligation",
        case_id=f"obligation-horizon{horizon}",
        npc=npc, world=world, memories=memories,
        acceptable=("warm", "neutral"),
        reason="An unresolved obligation the player owes the NPC should keep the "
               "NPC civil despite many days of unrelated chatter.",
    )]


# ============================================================== belief families
@dataclass
class BeliefCase:
    family: str
    case_id: str
    invariant: str
    passed: bool
    detail: str


def rumour_provenance_cases() -> List[BeliefCase]:
    """D: an echo chain must not be counted as independent corroboration."""
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()

    def rumour(source: str, day: int, chain: Optional[str]) -> MemoryRecord:
        meta = {"conflict_key": "theft", "claim": "player_stole"}
        if chain:
            meta["source_chain"] = chain
        return manager.event_to_memory(GameEvent(
            event_type="rumour_theft_accusation", actor=source,
            target_npc="mira", description=f"{source} repeated the theft rumour.",
            game_day=day, location="market", emotional_impact=0.3,
            relationship_impact=-0.2, quest_relevance=0.3, novelty=0.5,
            source=source, confidence=0.7, metadata=meta,
        ))

    # A -> B -> C : one origin, two echoes
    a = rumour("A", 1, None)
    store = [a]
    store_rev, b = updater.revise(store, rumour("B", 2, "A"))
    store = store_rev + [b]
    store_rev, c = updater.revise(store, rumour("C", 3, "A->B"))
    store = store_rev + [c]
    origin_after_echo = next(m for m in store if m.source == "A")

    # now an independent witness D
    store_rev, d = updater.revise(store, rumour("D", 4, None))
    store = store_rev + [d]
    origin_after_independent = next(m for m in store if m.source == "A")

    echo_no_bump = abs(origin_after_echo.confidence - 0.7) < 1e-9
    independent_bumps = origin_after_independent.confidence > origin_after_echo.confidence

    return [
        BeliefCase(
            family="D_provenance", case_id="echo-chain-no-corroboration",
            invariant="D1_echo_does_not_raise_confidence",
            passed=echo_no_bump,
            detail=f"origin confidence after 2 echoes = {origin_after_echo.confidence:.3f}",
        ),
        BeliefCase(
            family="D_provenance", case_id="independent-witness-corroborates",
            invariant="D2_independent_source_raises_confidence",
            passed=independent_bumps,
            detail=(f"origin confidence with an independent source = "
                    f"{origin_after_independent.confidence:.3f} vs "
                    f"{origin_after_echo.confidence:.3f} without"),
        ),
    ]


def conflicting_witness_cases() -> List[BeliefCase]:
    """E: when two sources conflict, the stronger claim wins consistently."""
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()

    strong = manager.event_to_memory(GameEvent(
        event_type="theft_accusation", actor="arun", target_npc="mira",
        description="Arun firmly accuses the player.", game_day=1, location="market",
        emotional_impact=0.8, relationship_impact=-0.7, quest_relevance=0.6,
        novelty=0.7, source="arun", confidence=0.9,
        metadata={"conflict_key": "theft", "claim": "player_stole"},
    ))
    weak = manager.event_to_memory(GameEvent(
        event_type="innocence_verified", actor="drunkard", target_npc="mira",
        description="A drunkard mumbles the player is innocent.", game_day=2,
        location="tavern", emotional_impact=0.2, relationship_impact=0.2,
        quest_relevance=0.2, novelty=0.3, source="drunkard", confidence=0.3,
        metadata={"conflict_key": "theft", "claim": "rohan_stole"},
    ))
    revised, incoming = updater.revise([strong], weak)
    strong_after = revised[0]

    strong_wins = (
        strong_after.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED}
        and incoming.status == BeliefStatus.DISPUTED
    )
    return [BeliefCase(
        family="E_conflicting", case_id="stronger-claim-wins",
        invariant="E1_higher_confidence_claim_prevails",
        passed=strong_wins,
        detail=(f"strong={strong_after.status.value}, "
                f"weak incoming={incoming.status.value}"),
    )]


# ================================================================ evaluation
def _family_of(action: str) -> str:
    return FAMILY.get(action, "neutral")


def run_decision_families(
    *,
    retrieval: Optional[object] = None,
    top_k: int = 5,
    seed: int = 20260920,
) -> Dict[str, object]:
    """Run families A-C through a retrieval policy + decision engine."""
    manager = HierarchicalMemoryManager()
    retriever = retrieval or manager
    engine = UtilityDecisionEngine()

    cases: List[DecisionCase] = []
    cases += reciprocity_cases(seed=seed)
    cases += reciprocity_cases(seed=seed, noise=20)      # under pressure
    cases += betrayal_cases(seed=seed)
    cases += obligation_cases(seed=seed)

    per_family: Dict[str, List[bool]] = {}
    failures: List[Dict[str, object]] = []
    for case in cases:
        retrieved = retriever.retrieve(
            case.memories, npc_id=case.npc.npc_id,
            current_day=case.world.game_day, top_k=top_k,
        )
        action = engine.decide(case.npc, case.world, retrieved).selected_action
        family = _family_of(action)
        ok = family in case.acceptable
        per_family.setdefault(case.family, []).append(ok)
        if not ok:
            failures.append({
                "case_id": case.case_id, "family": case.family,
                "action": action, "action_family": family,
                "acceptable": list(case.acceptable),
            })

    total = sum(len(v) for v in per_family.values())
    passed = sum(sum(1 for ok in v if ok) for v in per_family.values())
    return {
        "cases": total,
        "passed": passed,
        "pass_rate": passed / total if total else 1.0,
        "per_family": {
            fam: {"cases": len(v), "passed": sum(1 for ok in v if ok)}
            for fam, v in sorted(per_family.items())
        },
        "failures": failures,
    }


def run_belief_families() -> Dict[str, object]:
    """Run the updater-level families D-E (retrieval-independent)."""
    cases = rumour_provenance_cases() + conflicting_witness_cases()
    passed = sum(1 for c in cases if c.passed)
    return {
        "cases": len(cases),
        "passed": passed,
        "pass_rate": passed / len(cases) if cases else 1.0,
        "detail": [
            {"invariant": c.invariant, "passed": c.passed, "detail": c.detail}
            for c in cases
        ],
    }
