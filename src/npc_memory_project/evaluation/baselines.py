"""Retrieval baselines to compare the architecture against.

Every baseline implements the same interface as
:class:`~npc_memory_project.memory.manager.HierarchicalMemoryManager`
(``retrieve(memories, *, npc_id, current_day, top_k)``), so the scenario harness
can run them unchanged. The decision engine, valid-action filter and world state
are held constant across all methods -- only memory selection differs, which is
the variable under test.

These are *retrieval* baselines, not full agent baselines: none of them has an
LLM, so they are not a reproduction of Generative Agents. What they isolate is
the contribution of the specific mechanisms this repository adds -- status
tracking, tiering, decision-impact admission -- which is the claim the paper
actually makes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence

from npc_memory_project.core.models import BeliefStatus, MemoryRecord, MemoryTier


class RetrievalPolicy(ABC):
    """Selects which memories an NPC brings to a decision."""

    name: str = "policy"

    @abstractmethod
    def retrieve(
        self,
        memories: Sequence[MemoryRecord],
        *,
        npc_id: str,
        current_day: int,
        top_k: int = 5,
        **_: object,
    ) -> List[MemoryRecord]:
        ...

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _held(memories: Sequence[MemoryRecord], npc_id: str) -> List[MemoryRecord]:
        return [m for m in memories if m.npc_id == npc_id]

    @staticmethod
    def _decay(memory: MemoryRecord, current_day: int, lam: float = 0.1) -> float:
        return 1 / (1 + lam * max(0, current_day - memory.game_day))


class RecencyOnly(RetrievalPolicy):
    """The naive stream: most recent k memories, no status, no tiers, no decay.

    This is the baseline the paper argues against -- an unbounded log retrieved
    by recency alone.
    """

    name = "recency-only"

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = self._held(memories, npc_id)
        held.sort(key=lambda m: (m.game_day, m.importance), reverse=True)
        return held[:top_k]


class ImportanceOnly(RetrievalPolicy):
    """Rank by decision-impact score, ignoring belief status and tiers."""

    name = "importance-only"

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = self._held(memories, npc_id)
        held.sort(key=lambda m: (m.importance, m.confidence), reverse=True)
        return held[:top_k]


class RecencyImportanceStatusBlind(RetrievalPolicy):
    """A Generative-Agents-style recency+importance blend, minus relevance.

    Park et al. score retrieval as a weighted sum of recency, importance and
    relevance. There is no embedding model here, so relevance is omitted -- this
    is the closest honest analogue, and it deliberately does *not* filter on
    belief status, which is the mechanism under test.
    """

    name = "recency+importance (status-blind)"

    def __init__(self, w_recency: float = 0.5, w_importance: float = 0.5) -> None:
        self.w_recency = w_recency
        self.w_importance = w_importance

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = self._held(memories, npc_id)
        scored = [
            (
                self.w_recency * self._decay(m, current_day)
                + self.w_importance * m.importance,
                m,
            )
            for m in held
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored[:top_k]]


class StatusAwareNoTiers(RetrievalPolicy):
    """Ablation: correct status filtering, but no tier structure.

    Separates the two mechanisms. If this matches the full architecture on the
    invariants, then the tier hierarchy -- not the belief-status filter -- is
    what is doing the work.
    """

    name = "status-aware, no tiers"

    def __init__(self, decay_lambda: float = 0.1) -> None:
        self.decay_lambda = decay_lambda

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = [
            m for m in self._held(memories, npc_id)
            if m.status not in {BeliefStatus.SUPERSEDED, BeliefStatus.EXPIRED,
                                BeliefStatus.DISPUTED}
        ]
        scored = [
            (
                0.60 * m.importance
                + 0.30 * self._decay(m, current_day, self.decay_lambda)
                + 0.10 * m.confidence,
                m,
            )
            for m in held
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored[:top_k]]


class TierAwareNoStatus(RetrievalPolicy):
    """Ablation: tier structure and decay, but no belief-status filtering."""

    name = "tiers, status-blind"

    def retrieve(self, memories, *, npc_id, current_day, top_k=5, **_):
        held = [
            m for m in self._held(memories, npc_id) if m.tier != MemoryTier.ARCHIVE
        ]
        scored = [
            (
                (1.1 if m.tier == MemoryTier.SEMANTIC else 1.0)
                * (0.45 + 0.30 * m.importance + 0.20 * self._decay(m, current_day)
                   + 0.05 * m.confidence),
                m,
            )
            for m in held
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored[:top_k]]


def default_suite() -> List[RetrievalPolicy]:
    """The comparison set reported in the evaluation."""
    return [
        RecencyOnly(),
        ImportanceOnly(),
        RecencyImportanceStatusBlind(),
        StatusAwareNoTiers(),
        TierAwareNoStatus(),
    ]
