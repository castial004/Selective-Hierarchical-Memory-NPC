"""Long-horizon experiment: does the memory architecture retain what it learned?

The ablation in ``evaluation/ablation.py`` showed that removing the tier hierarchy
and the semantic tier changed **no decision**. But that instrument never ran the
memory *lifecycle*: every case was a handful of records on a single day, so no
record had ever decayed, been superseded, archived or consolidated. Tiers and
semantic beliefs exist to do their work over *time*, so testing them on frozen
state is testing them where they cannot possibly matter.

This module runs the clock. A store is built through the real pipeline --
``event_to_memory`` -> ``ContradictionAwareBeliefUpdater.revise`` ->
``manage_lifecycle`` -> ``SemanticConsolidator.consolidate`` -- over many
simulated days of noise, and a decision is probed at increasing horizons.

Design, fixed before the first run (so the result can falsify it):

* **Timeline A -- exonerated.** Day 1: Arun accuses the player of stealing Mira's
  medicine. Day 3: Kael verifies that Rohan, not the player, stole it. Days after:
  ambient chatter. Probes expect the *warm* family: an exoneration that has been
  verified does not decay back into suspicion.
* **Timeline B -- accused.** Same accusation, no exoneration. Probes expect the
  *punitive* family: an accusation never retracted does not decay into forgiveness.

Hypotheses:

* **H1 retention.** The full architecture answers both probes correctly at every
  horizon up to 120 days.
* **H2 tier redundancy.** Removing the tier hierarchy costs nothing on retention
  either, because every ARCHIVE record is *also* SUPERSEDED or EXPIRED, so the
  archive filter excludes a strict subset of what the status filter already
  excludes. Measured directly as
  ``|ARCHIVE ∩ (SUPERSEDED ∪ EXPIRED)| / |ARCHIVE|``.
* **H3 semantic redundancy.** Removing derived semantic beliefs costs nothing,
  because the episodic records behind them never expire.

If H2 and H3 hold, the tier hierarchy as implemented is decorative on every
instrument this repository has, and that is what gets reported -- along with the
retention number, which is the one claim the architecture does make and had never
been tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus, GameEvent, MemoryRecord, MemoryTier, NPCState, WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.labelled import FAMILY
from npc_memory_project.memory.consolidation import SemanticConsolidator
from npc_memory_project.memory.manager import HierarchicalMemoryManager

PROBE_DAYS: Sequence[int] = (5, 10, 20, 40, 80, 120)

WARM = {"warm"}
PUNITIVE = {"punitive"}


@dataclass
class ProbeResult:
    policy: str
    timeline: str
    day: int
    action: str
    family: str
    expected: str
    correct: bool
    decisive_retrieved: bool
    retrieved: int


@dataclass
class StoreSnapshot:
    day: int
    records: int
    by_tier: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    archived_also_status_excluded: int = 0
    archived_total: int = 0

    @property
    def tier_redundancy(self) -> float:
        """Share of ARCHIVE records the belief-status filter would exclude anyway."""
        if not self.archived_total:
            return 1.0
        return self.archived_also_status_excluded / self.archived_total


def _chatter(npc_id: str, day: int, rng_index: int) -> GameEvent:
    """One piece of ambient life: low-stakes, working tier, forgettable."""
    topics = [
        "The player asked after the price of bandages.",
        "A cart of turnips arrived from the south road.",
        "The player waited quietly while others were served.",
        "A neighbour mentioned rain coming in off the hills.",
        "The player returned a dropped coin to the stall.",
        "Someone swept the steps outside the shop.",
    ]
    return GameEvent(
        event_type="smalltalk",
        actor="player",
        target_npc=npc_id,
        description=topics[rng_index % len(topics)],
        game_day=day,
        location="pharmacy",
        emotional_impact=0.05,
        relationship_impact=0.0,
        quest_relevance=0.0,
        novelty=0.3,
        source="ambient",
        confidence=0.5,
    )


def _accusation(npc_id: str, day: int) -> GameEvent:
    return GameEvent(
        event_type="theft_accusation",
        actor="arun",
        target_npc=npc_id,
        description="Arun accused the player of stealing Mira's medicine.",
        game_day=day,
        location="market",
        emotional_impact=0.8,
        relationship_impact=-0.6,
        quest_relevance=0.9,
        novelty=0.8,
        source="arun",
        confidence=0.60,
        metadata={"conflict_key": "medicine_theft", "claim": "player_stole"},
    )


def _exoneration(npc_id: str, day: int) -> GameEvent:
    return GameEvent(
        event_type="innocence_verified",
        actor="kael",
        target_npc=npc_id,
        description="The guard proved that Rohan, not the player, stole the medicine.",
        game_day=day,
        location="guardhouse",
        emotional_impact=0.7,
        relationship_impact=0.5,
        quest_relevance=0.9,
        novelty=0.7,
        source="guard",
        confidence=0.95,
        metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
    )


@dataclass
class Timeline:
    """One seeded run of the real memory pipeline over ``horizon`` days."""

    name: str
    horizon: int
    npc_id: str = "mira"
    chatter_per_day: int = 2

    store: List[MemoryRecord] = field(default_factory=list)
    snapshots: List[StoreSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.manager = HierarchicalMemoryManager()
        self.updater = ContradictionAwareBeliefUpdater()
        self.consolidator = SemanticConsolidator()

    # ------------------------------------------------------------- pipeline
    def admit(self, event: GameEvent) -> None:
        memory = self.manager.event_to_memory(event)
        existing = [m for m in self.store if m.npc_id == event.target_npc]
        revised, incoming = self.updater.revise(existing, memory)
        others = [m for m in self.store if m.npc_id != event.target_npc]
        self.store = others + revised + [incoming]

    def run_day(self, day: int) -> None:
        held = [m for m in self.store if m.npc_id == self.npc_id]
        managed = self.manager.manage_lifecycle(held, day, self.npc_id)
        others = [m for m in self.store if m.npc_id != self.npc_id]
        self.store = others + managed
        self.store = others + self.consolidator.consolidate(managed, day, self.npc_id)
        self.snapshots.append(self.snapshot(day))

    def snapshot(self, day: int) -> StoreSnapshot:
        held = [m for m in self.store if m.npc_id == self.npc_id]
        by_tier: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        archived = [m for m in held if m.tier == MemoryTier.ARCHIVE]
        redundant = [
            m for m in archived
            if m.status in {BeliefStatus.SUPERSEDED, BeliefStatus.EXPIRED}
        ]
        for m in held:
            by_tier[m.tier.value] = by_tier.get(m.tier.value, 0) + 1
            by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
        return StoreSnapshot(day, len(held), by_tier, by_status,
                             archived_also_status_excluded=len(redundant),
                             archived_total=len(archived))

    # ------------------------------------------------------------ scenarios
    def build(self) -> None:
        self.admit(_accusation(self.npc_id, 1))
        for day in range(1, self.horizon + 1):
            if self.name == "exonerated" and day == 3:
                self.admit(_exoneration(self.npc_id, day))
            for i in range(self.chatter_per_day):
                self.admit(_chatter(self.npc_id, day, day * 7 + i))
            self.run_day(day)


def probe_npc() -> Tuple[NPCState, WorldState]:
    """The state probed at every horizon: a cautious shopkeeper, neutral trust."""
    return (
        NPCState("mira", "shopkeeper", 0.0, {"fairness": 0.9, "cautious": 0.7},
                 {"medicine": 24, "bandage": 6}),
        WorldState(1, "pharmacy", True, False),
    )


EXPECTED = {"exonerated": "warm", "accused": "punitive"}
DECISIVE_EVENT = {"exonerated": "innocence_verified", "accused": "theft_accusation"}


def _policies() -> List[Tuple[str, object]]:
    """The full architecture plus the three ablations this experiment is about."""
    from npc_memory_project.evaluation.ablation import NoSemanticRetrieval
    from npc_memory_project.evaluation.baselines import (
        RecencyOnly, StatusAwareNoTiers, TierAwareNoStatus,
    )

    return [
        ("SHM (this architecture)", HierarchicalMemoryManager()),
        ("no semantic tier", NoSemanticRetrieval()),
        ("status-aware, no tiers", StatusAwareNoTiers()),
        ("tiers, status-blind", TierAwareNoStatus()),
        ("recency only", RecencyOnly()),
    ]


def run_longitudinal_experiment(
    probe_days: Sequence[int] = PROBE_DAYS,
    *,
    top_k: int = 5,
) -> Dict[str, object]:
    """Build both timelines once, then probe every policy at every horizon."""
    engine = UtilityDecisionEngine()
    npc, world = probe_npc()

    timelines: Dict[str, Timeline] = {}
    for name in ("exonerated", "accused"):
        timeline = Timeline(name=name, horizon=max(probe_days))
        timeline.build()
        timelines[name] = timeline

    results: List[ProbeResult] = []
    for name, timeline in timelines.items():
        for policy_name, retrieval in _policies():
            for day in probe_days:
                world.game_day = day
                retrieved = retrieval.retrieve(
                    timeline.store, npc_id=npc.npc_id, current_day=day, top_k=top_k,
                )
                trace = engine.decide(npc, world, retrieved)
                family = FAMILY.get(trace.selected_action, "neutral")
                expected = EXPECTED[name]
                results.append(ProbeResult(
                    policy=policy_name,
                    timeline=name,
                    day=day,
                    action=trace.selected_action,
                    family=family,
                    expected=expected,
                    correct=family == expected,
                    decisive_retrieved=any(
                        m.event_type == DECISIVE_EVENT[name] for m in retrieved
                    ),
                    retrieved=len(retrieved),
                ))

    retention: Dict[str, Dict[str, float]] = {}
    for policy_name, _ in _policies():
        retention[policy_name] = {}
        for name in timelines:
            hits = [
                r for r in results
                if r.policy == policy_name and r.timeline == name
            ]
            retention[policy_name][f"{name}_accuracy"] = (
                sum(1 for r in hits if r.correct) / len(hits) if hits else 0.0
            )
            retention[policy_name][f"{name}_decisive_in_k"] = (
                sum(1 for r in hits if r.decisive_retrieved) / len(hits) if hits else 0.0
            )

    return {
        "probe_days": list(probe_days),
        "top_k": top_k,
        "results": results,
        "retention": retention,
        "snapshots": {name: t.snapshots for name, t in timelines.items()},
    }


def print_longitudinal_report(report: Dict[str, object]) -> None:
    print("\nLong-horizon knowledge retention "
          f"(probe days {report['probe_days']}, top_k={report['top_k']})")
    print("  'A' = exoneration timeline (expect warm), 'B' = accused timeline "
          "(expect punitive)\n")
    print(f"  {'policy':<26}{'A acc':>8}{'A dec':>8}{'B acc':>8}{'B dec':>8}")
    print("  " + "-" * 58)
    for policy, scores in report["retention"].items():      # type: ignore[union-attr]
        print(f"  {policy:<26}"
              f"{100 * scores['exonerated_accuracy']:>7.0f}%"
              f"{100 * scores['exonerated_decisive_in_k']:>7.0f}%"
              f"{100 * scores['accused_accuracy']:>7.0f}%"
              f"{100 * scores['accused_decisive_in_k']:>7.0f}%")

    snaps = report["snapshots"]["exonerated"]              # type: ignore[index]
    last = snaps[-1]
    print(f"\n  store at day {last.day}: {last.records} records "
          f"{last.by_tier}")
    print(f"  ARCHIVE records: {last.archived_total}, of which "
          f"{last.archived_also_status_excluded} are also SUPERSEDED/EXPIRED "
          f"({100 * last.tier_redundancy:.0f}% redundant with the status filter)")
    print()
