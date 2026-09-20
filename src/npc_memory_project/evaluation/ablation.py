"""Component and feature ablation.

The paper claims four mechanisms do work. This module removes them one at a time
and measures what breaks:

* **status filter** -- what if DISPUTED/SUPERSEDED memories were retrievable?
* **tiers** -- what if there were no Working/Episodic/Semantic/Archive structure?
* **semantic tier** -- what if derived beliefs were never admitted or retrieved?
* **lineage-aware explanation** -- what if ablation ignored derived summaries?
* **feature channels** -- which of theft/innocence/help/rumour/confession
  actually carry the decisions?

Everything is measured on the same two instruments as the main table: the
author-labelled case set (accuracy) and the seeded invariant suite (property
compliance), so the ablation numbers are directly comparable to the headline
ones.

Result of note, reported as found: the tier hierarchy and the semantic tier
contribute **nothing measurable** on these instruments once status filtering is
present, while the status filter is load-bearing. See ``docs/EVALUATION.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from npc_memory_project.core.models import BeliefStatus, MemoryRecord, MemoryTier
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.evaluation.baselines import (
    RecencyOnly, StatusAwareNoTiers, TierAwareNoStatus,
)
from npc_memory_project.evaluation.harness import build_scenarios, evaluate
from npc_memory_project.evaluation.labelled import author_labelled_cases, run_labelled_suite
from npc_memory_project.memory.manager import HierarchicalMemoryManager


# --------------------------------------------------------------- tier ablation
class NoSemanticRetrieval(HierarchicalMemoryManager):
    """Full policy, except derived (SEMANTIC) beliefs are never retrieved.

    Isolates "does consolidating experience into beliefs change any decision?"
    from "does admission place records correctly?"
    """

    name = "no semantic tier"

    def retrieve(self, memories, *, npc_id, current_day, event_type=None, top_k=5,
                 include_disputed=False):
        without_semantic = [m for m in memories if m.tier != MemoryTier.SEMANTIC]
        return super().retrieve(
            without_semantic, npc_id=npc_id, current_day=current_day,
            event_type=event_type, top_k=top_k, include_disputed=include_disputed,
        )


class NoStatusFilter(HierarchicalMemoryManager):
    """Full policy, except SUPERSEDED/DISPUTED/EXPIRED records stay retrievable."""

    name = "no status filter"

    def retrieve(self, memories, *, npc_id, current_day, event_type=None, top_k=5,
                 include_disputed=False):
        # Neutralise status by rewriting it before the parent filter runs. This
        # is deliberately a heavy-handed ablation: it models a system that keeps
        # no belief status at all.
        relaxed = [
            m if m.status == BeliefStatus.ACTIVE
            else MemoryRecord(
                event_id=m.event_id, npc_id=m.npc_id, summary=m.summary,
                event_type=m.event_type, game_day=m.game_day, tier=m.tier,
                importance=m.importance, confidence=m.confidence,
                status=BeliefStatus.ACTIVE, source=m.source, tags=m.tags,
                metadata=m.metadata,
            )
            for m in memories
        ]
        return super().retrieve(relaxed, npc_id=npc_id, current_day=current_day,
                                event_type=event_type, top_k=top_k,
                                include_disputed=include_disputed)


# ----------------------------------------------------------- feature ablation
class FeatureMaskedEngine(UtilityDecisionEngine):
    """Zeroes one causal feature channel, to see which channels matter."""

    def __init__(self, masked: str) -> None:
        super().__init__()
        self.masked = masked
        self.name = f"feature off: {masked}"

    def _features(self, memories):
        from npc_memory_project.core.features import FEATURE_KEYS

        values = list(super()._features(memories))
        values[FEATURE_KEYS.index(self.masked)] = 0.0
        return tuple(values)


# ------------------------------------------------------------------ runner
@dataclass
class AblationResult:
    name: str
    labelled_correct: int
    labelled_total: int
    invariants_passed: int
    invariants_checked: int
    notes: str = ""

    @property
    def accuracy(self) -> float:
        return self.labelled_correct / self.labelled_total if self.labelled_total else 0.0

    @property
    def invariant_rate(self) -> float:
        return (self.invariants_passed / self.invariants_checked
                if self.invariants_checked else 1.0)


def _score_labelled(retrieval, engine: UtilityDecisionEngine) -> tuple:
    """Run the labelled set with a custom engine (run_labelled_suite fixes the engine)."""
    correct = total = 0
    for case in author_labelled_cases():
        retrieved = retrieval.retrieve(case.memories, npc_id=case.npc.npc_id,
                                      current_day=case.world.game_day, top_k=5)
        action = engine.decide(case.npc, case.world, retrieved).selected_action
        total += 1
        correct += 1 if case.is_correct(action) else 0
    return correct, total


def _score_invariants(retrieval) -> tuple:
    result = evaluate(build_scenarios(60), retrieval=retrieval)
    return result["passed"], result["checks"]


def run_ablation_suite() -> List[AblationResult]:
    """Every ablation, measured on both instruments."""
    from npc_memory_project.core.features import FEATURE_KEYS
    from npc_memory_project.evaluation.baselines import (
        RecencyImportanceStatusBlind,
    )

    engine = UtilityDecisionEngine()
    results: List[AblationResult] = []

    variants: List[tuple] = [
        ("full architecture", HierarchicalMemoryManager(), engine,
         "status filter + tiers + semantic tier + lineage"),
        ("no status filter", NoStatusFilter(), engine,
         "superseded/disputed/expired records stay retrievable"),
        ("no tiers (status kept)", StatusAwareNoTiers(), engine,
         "flat store, belief status still enforced"),
        ("tiers, no status", TierAwareNoStatus(), engine,
         "tier structure without belief status"),
        ("no semantic tier", NoSemanticRetrieval(), engine,
         "derived beliefs never retrieved"),
        ("recency only (naive stream)", RecencyOnly(), engine,
         "most recent k, no status, no tiers"),
        ("recency + importance, status-blind", RecencyImportanceStatusBlind(), engine,
         "Generative-Agents-style blend without relevance"),
    ]
    for masked in FEATURE_KEYS:
        variants.append((
            f"feature off: {masked}", HierarchicalMemoryManager(),
            FeatureMaskedEngine(masked), "one causal channel zeroed",
        ))

    for name, retrieval, active_engine, notes in variants:
        correct, total = _score_labelled(retrieval, active_engine)
        passed, checked = _score_invariants(retrieval)
        results.append(AblationResult(name, correct, total, passed, checked, notes))

    return results
