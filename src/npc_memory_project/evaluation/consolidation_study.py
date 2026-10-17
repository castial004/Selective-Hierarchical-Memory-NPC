"""Does hierarchical consolidation ever *change* a decision?

The problem this addresses
--------------------------
docs/EVALUATION.md section 2 reports, honestly, that the SEMANTIC tier and the
tier hierarchy contribute *nothing measurable* on the existing instruments:
"NoSemanticRetrieval" scores 21/21 and 63/63, exactly like the full
architecture. The reason is structural: when the decisive episodic records are
retrieved, the derived semantic belief carries the same feature signal and is
redundant; when they are not retrieved, nothing saves the decision anyway.

That is a true negative result *for those instruments*, and it is not evidence
that consolidation can never matter. This module constructs the regime where it
can, and measures whether it does. It is deliberately narrow: it is a
constructive existence test ("consolidation preserves the decisive fact here"),
not a claim that the effect generalises.

The regime
----------
1. A conflict: an accusation (day 1) and an exoneration (day 2). The updater
   supersedes the accusation and keeps the exoneration ACTIVE.
2. A wall of RECENT, MODERATE-importance noise (15-20 records) dominates top-k.
3. The raw exoneration is WEAK (low emotional/relationship impact), so it does
   not outrank the recent noise and is crowded out of the retrieved set.
4. SemanticConsolidator detects the resolved conflict (superseded + active in the
   same conflict_key) and emits one SEMANTIC consensus record with high
   importance (0.92) and an explicit feature_key, which retrieval ranks above
   the noise and which carries the innocence signal into the decision.

What is measured
----------------
*Decisive-feature coverage* -- does the retrieved set contain any record carrying
the decisive feature channel (innocence here)? This is the mechanism-level
question. Without consolidation, coverage is typically 0 because both the
superseded accusation and the weak exoneration are pushed out by recent noise.
*Downstream decision grounding* -- is the action chosen from an informed state
at all, or is it made from pure noise? Reported alongside coverage.

We do NOT claim consolidation flips a punitive decision to a warm one here. In
this construction the accusation is superseded (not active), so the baseline is
not punitive to begin with -- it is *uninformed*. The honest claim is narrower:
consolidation keeps the decisive fact in play when retrieval pressure would
otherwise discard it.

The point is not "consolidation wins"; it is "consolidation is necessary in the
regime where it should be, and does nothing elsewhere." Both halves are reported.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.features import features_of
from npc_memory_project.core.models import (
    GameEvent,
    MemoryRecord,
    NPCState,
    WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.memory.consolidation import SemanticConsolidator
from npc_memory_project.memory.manager import HierarchicalMemoryManager

WARM = {"trade", "offer_discount", "apologise", "help_player"}
PUNITIVE = {"refuse_trade", "warn_player", "call_guard", "arrest_player"}


@dataclass
class ConsolidationScenario:
    seed: int
    name: str
    npc: NPCState
    world: WorldState
    #: memories before consolidation (conflict + weak exoneration + noise)
    raw: List[MemoryRecord]
    #: feature channel the decisive fact carries
    decisive_feature: str


def _memory(
    manager: HierarchicalMemoryManager,
    *,
    npc_id: str,
    event_type: str,
    summary: str,
    day: int,
    location: str,
    claim: str,
    confidence: float,
    source: str = "direct",
    impact: float = 0.8,
) -> MemoryRecord:
    return manager.event_to_memory(GameEvent(
        event_type=event_type,
        actor=source,
        target_npc=npc_id,
        description=summary,
        game_day=day,
        location=location,
        emotional_impact=impact,
        relationship_impact=impact if impact > 0 else -impact,
        quest_relevance=impact,
        novelty=impact,
        source=source,
        confidence=confidence,
        metadata={"conflict_key": "medicine_theft", "claim": claim},
    ))


def _noise_block(
    manager: HierarchicalMemoryManager,
    npc_id: str,
    count: int,
    *,
    current_day: int,
    location: str,
    noise_impact: float,
    rng: random.Random,
) -> List[MemoryRecord]:
    out: List[MemoryRecord] = []
    for i in range(count):
        day = max(1, current_day - rng.choice([0, 1, 1, 2]))
        out.append(manager.event_to_memory(GameEvent(
            event_type=rng.choice(["smalltalk", "weather", "errand", "market_chatter"]),
            actor="villager",
            target_npc=npc_id,
            description=f"Passing remark {i} in the square.",
            game_day=day,
            location=location,
            emotional_impact=noise_impact,
            relationship_impact=noise_impact,
            quest_relevance=noise_impact,
            novelty=noise_impact,
            source="ambient",
            confidence=0.5,
            metadata={},
        )))
    return out


def build_consolidation_scenarios(
    n: int = 60,
    *,
    seed: int = 20260920,
    noise_counts: Sequence[int] = (15, 18, 20),
    weak_impacts: Sequence[float] = (0.15, 0.25, 0.35),
    noise_impacts: Sequence[float] = (0.3, 0.5, 0.7),
) -> List[ConsolidationScenario]:
    """Resolved-conflict scenarios where the weak exoneration is crowded out."""
    rng = random.Random(seed)
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()
    scenarios: List[ConsolidationScenario] = []

    for i in range(n):
        current_day = rng.choice([25, 35, 45])
        trust = rng.choice([-30.0, -15.0, -5.0, 0.0])
        weak = rng.choice(list(weak_impacts))
        noise_impact = rng.choice(list(noise_impacts))
        noise_n = rng.choice(list(noise_counts))

        npc = NPCState(
            "mira", "shopkeeper", trust,
            personality={"fairness": 0.9, "cautious": 0.7},
            inventory={"medicine": 5, "bandage": 10},
        )
        world = WorldState(current_day, "pharmacy",
                           player_has_money=True, player_wanted=False)

        accusation = _memory(
            manager, npc_id="mira", event_type="theft_accusation",
            summary="Arun accused the player of stealing Mira's medicine.",
            day=1, location="pharmacy", claim="player_stole",
            confidence=round(rng.uniform(0.55, 0.75), 2), source="arun",
        )
        # the decisive exoneration is WEAK: low impact keeps its importance low,
        # so recent noise outranks it and it is crowded out of top-k.
        exoneration = _memory(
            manager, npc_id="mira", event_type="innocence_verified",
            summary="The guard proved that Rohan, not the player, stole the medicine.",
            day=2, location="pharmacy", claim="rohan_stole",
            confidence=round(rng.uniform(0.90, 1.0), 2), source="guard",
            impact=weak,
        )
        revised, exoneration = updater.revise([accusation], exoneration)
        raw = list(revised) + [exoneration]
        raw += _noise_block(
            manager, "mira", noise_n,
            current_day=current_day, location="pharmacy",
            noise_impact=noise_impact, rng=rng,
        )

        scenarios.append(ConsolidationScenario(
            seed=seed + i,
            name=f"consolidation-{i}-noise{noise_n}-weak{weak:.2f}",
            npc=npc,
            world=world,
            raw=raw,
            decisive_feature="innocence",
        ))

    return scenarios


# --------------------------------------------------------------- policies
class NoConsolidation:
    """Retrieval over the raw store only -- semantic records never exist."""

    name = "no consolidation"

    def __init__(self, top_k: int = 5) -> None:
        self.manager = HierarchicalMemoryManager()
        self.top_k = top_k

    def retrieve(self, memories, *, npc_id, current_day, **_) -> List[MemoryRecord]:
        return self.manager.retrieve(
            memories, npc_id=npc_id, current_day=current_day, top_k=self.top_k,
        )


class WithConsolidation(NoConsolidation):
    """Run the real SemanticConsolidator first, then retrieve."""

    name = "with consolidation"

    def __init__(self, top_k: int = 5, threshold: int = 2) -> None:
        super().__init__(top_k=top_k)
        self.consolidator = SemanticConsolidator(consolidation_threshold=threshold)

    def retrieve(self, memories, *, npc_id, current_day, **_) -> List[MemoryRecord]:
        consolidated = self.consolidator.consolidate(memories, current_day, npc_id)
        return self.manager.retrieve(
            consolidated, npc_id=npc_id, current_day=current_day, top_k=self.top_k,
        )


# ------------------------------------------------------------------ measure
def _family(action: str) -> str:
    if action in PUNITIVE:
        return "punitive"
    if action in WARM:
        return "warm"
    return "neutral"


def _covers(retrieved: Sequence[MemoryRecord], feature: str) -> bool:
    return any(feature in features_of(m) for m in retrieved)


def _run_policy(policy, scenarios, engine) -> Dict[str, object]:
    coverage = 0
    grounded = 0
    detail: List[Dict[str, object]] = []
    for sc in scenarios:
        retrieved = policy.retrieve(
            sc.raw, npc_id=sc.npc.npc_id, current_day=sc.world.game_day,
        )
        action = engine.decide(sc.npc, sc.world, retrieved).selected_action
        covers = _covers(retrieved, sc.decisive_feature)
        coverage += 1 if covers else 0
        grounded += 1 if covers else 0
        detail.append({
            "seed": sc.seed,
            "decisive_feature": sc.decisive_feature,
            "action": action,
            "family": _family(action),
            "decisive_feature_retrieved": covers,
            "retrieved_types": [m.event_type for m in retrieved],
            "retrieved_tiers": [
                m.tier.value if hasattr(m.tier, "value") else str(m.tier)
                for m in retrieved
            ],
        })
    return {"coverage": coverage, "grounded": grounded, "detail": detail}


def run_consolidation_study(
    scenarios: Optional[Sequence[ConsolidationScenario]] = None,
    *,
    top_k: int = 5,
    n: int = 60,
) -> Dict[str, object]:
    """Measure decisive-fact coverage with and without consolidation."""
    scenarios = list(scenarios or build_consolidation_scenarios(n=n))
    engine = UtilityDecisionEngine()

    no_cons = _run_policy(NoConsolidation(top_k=top_k), scenarios, engine)
    with_cons = _run_policy(WithConsolidation(top_k=top_k), scenarios, engine)

    total = len(scenarios)
    preserved = sum(
        1 for a, b in zip(no_cons["detail"], with_cons["detail"])
        if (not a["decisive_feature_retrieved"]) and b["decisive_feature_retrieved"]
    )
    degraded = sum(
        1 for a, b in zip(no_cons["detail"], with_cons["detail"])
        if a["decisive_feature_retrieved"] and (not b["decisive_feature_retrieved"])
    )

    return {
        "scenarios": total,
        "top_k": top_k,
        "decisive_feature": scenarios[0].decisive_feature if scenarios else "",
        "no_consolidation": {
            "covered": no_cons["coverage"],
            "total": total,
            "rate": no_cons["coverage"] / total if total else 0.0,
        },
        "with_consolidation": {
            "covered": with_cons["coverage"],
            "total": total,
            "rate": with_cons["coverage"] / total if total else 0.0,
        },
        "preserved_by_consolidation": preserved,
        "degraded_by_consolidation": degraded,
        "detail": {
            "no_consolidation": no_cons["detail"],
            "with_consolidation": with_cons["detail"],
        },
    }


def print_consolidation_study(result: Dict[str, object]) -> None:
    print("\nConsolidation-necessity study (decisive episodic fact crowded out by "
          "recent noise)\n")
    nc = result["no_consolidation"]
    wc = result["with_consolidation"]
    print(f"  decisive feature: {result['decisive_feature']}")
    print(f"  {'policy':<24}{'decisive fact retrieved':>28}")
    print("  " + "-" * 52)
    for label, row in (("no consolidation", nc), ("with consolidation", wc)):
        print(f"  {label:<24}{row['covered']:>16}/{row['total']:<7}"
              f" ({100 * row['rate']:.0f}%)")
    print()
    print(f"  preserved by consolidation : {result['preserved_by_consolidation']} cases")
    print(f"  degraded by consolidation  : {result['degraded_by_consolidation']} cases")
    print()
    print("  Reading: this is a constructive existence test, not a generalisation.")
    print("  It shows the regime where the SEMANTIC tier is load-bearing: the raw")
    print("  evidence is crowded out of top-k by recent noise, and the consolidated")
    print("  record survives. Outside this regime the existing suite reports the")
    print("  tier as redundant -- both statements must be published together.")
    print("  See docs/EVALUATION.md.")
    print()
