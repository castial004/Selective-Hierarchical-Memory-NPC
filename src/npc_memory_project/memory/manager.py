from dataclasses import replace
from typing import List, Tuple
from npc_memory_project.core.models import GameEvent, MemoryRecord, MemoryTier, BeliefStatus
from npc_memory_project.memory.importance import decision_impact_score

#: Statuses a decision may never use: SUPERSEDED and EXPIRED are history, and
#: DISPUTED is a claim the updater explicitly declined to accept as knowledge.
EXCLUDED_STATUSES = frozenset(
    {BeliefStatus.SUPERSEDED, BeliefStatus.EXPIRED, BeliefStatus.DISPUTED}
)

#: Tiers a decision may never use. Note this is a *subset* of EXCLUDED_STATUSES in
#: practice -- the lifecycle only ever archives records it has already superseded
#: or expired -- which is the redundancy reported in docs/EVALUATION.md. It is kept
#: as a separate filter because the index and the manager must agree exactly, not
#: approximately.
EXCLUDED_TIERS = frozenset({MemoryTier.ARCHIVE})


def is_retrievable(record: MemoryRecord, include_disputed: bool = False) -> bool:
    """The single definition of "a decision may see this record".

    Used by both :meth:`HierarchicalMemoryManager.retrieve` and
    :class:`npc_memory_project.memory.index.RetrievalIndex`, so an index lookup and
    a brute-force scan cannot disagree.
    """
    if record.tier in EXCLUDED_TIERS:
        return False
    if record.status in EXCLUDED_STATUSES:
        return include_disputed and record.status == BeliefStatus.DISPUTED
    return True


class HierarchicalMemoryManager:
    def __init__(
        self,
        episodic_threshold: float = 0.45,
        semantic_threshold: float = 0.78,
        working_memory_capacity: int = 5,
        archive_horizon: int = 3,
        decay_lambda: float = 0.1,
    ):
        self.episodic_threshold = episodic_threshold
        self.semantic_threshold = semantic_threshold
        self.working_memory_capacity = working_memory_capacity
        self.archive_horizon = archive_horizon
        self.decay_lambda = decay_lambda

    #: Event sources whose output is by definition a derived belief, not raw
    #: experience. v0.2 gated SEMANTIC admission on metadata["is_summary"] only,
    #: and nothing in the repository ever set that key -- so choose_tier could
    #: never return SEMANTIC for a real event.
    SEMANTIC_SOURCES = frozenset({"consolidation", "belief_revision"})

    def choose_tier(self, event: GameEvent) -> MemoryTier:
        s = decision_impact_score(event)
        is_summary = (
            event.metadata.get("is_summary") == "true"
            or event.source in self.SEMANTIC_SOURCES
        )
        if s >= self.semantic_threshold and is_summary:
            return MemoryTier.SEMANTIC
        if s >= self.episodic_threshold:
            return MemoryTier.EPISODIC
        return MemoryTier.WORKING

    def event_to_memory(self, event: GameEvent) -> MemoryRecord:
        s = decision_impact_score(event)
        return MemoryRecord(
            event.event_id,
            event.target_npc,
            event.description,
            event.event_type,
            event.game_day,
            self.choose_tier(event),
            s,
            event.confidence,
            source=event.source,
            tags=[event.event_type, event.actor, event.target_npc, event.location],
            metadata=dict(event.metadata),
        )

    def retrieve(
        self,
        memories: List[MemoryRecord],
        *,
        npc_id: str,
        current_day: int,
        event_type: str | None = None,
        top_k: int = 5,
        include_disputed: bool = False,
    ) -> List[MemoryRecord]:
        """Select the memories that may enter a decision.

        v0.2 filtered only SUPERSEDED and EXPIRED, so DISPUTED records -- claims
        the updater explicitly declined to accept as knowledge -- passed straight
        through into the utility feature vector at full weight (importance x
        confidence). A single disputed theft rumour was therefore sufficient to
        make a guard choose ``arrest_player``. DISPUTED records are now excluded
        by default; pass ``include_disputed=True`` to inspect them.
        """
        # One shared predicate with memory/index.py -- see is_retrievable().
        cand = [
            m
            for m in memories
            if m.npc_id == npc_id and is_retrievable(m, include_disputed=include_disputed)
        ]
        scored = []
        for m in cand:
            rel = 1.0 if event_type and m.event_type == event_type else 0.45
            rec = 1 / (1 + self.decay_lambda * max(0, current_day - m.game_day))
            bonus = 0.20 if m.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED} else 0
            tier_mult = 1.1 if m.tier == MemoryTier.SEMANTIC else 1.0
            score = (0.45 * rel + 0.30 * m.importance + 0.20 * rec + 0.05 * m.confidence + bonus) * tier_mult
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    def manage_lifecycle(
        self,
        memories: List[MemoryRecord],
        current_day: int,
        npc_id: str,
    ) -> List[MemoryRecord]:
        """
        Enforces working memory capacity constraints, decays old low-importance items,
        and transitions superseded or stale records into the Archive tier.
        """
        npc_mems = [m for m in memories if m.npc_id == npc_id]
        other_mems = [m for m in memories if m.npc_id != npc_id]

        updated: List[MemoryRecord] = []
        working_mems: List[MemoryRecord] = []

        for m in npc_mems:
            age = current_day - m.game_day
            # 1. Archive superseded memories older than archive horizon
            if m.status == BeliefStatus.SUPERSEDED and age >= 1:
                updated.append(replace(m, tier=MemoryTier.ARCHIVE))
            # 2. Archive low-importance memories past archive horizon
            elif m.tier == MemoryTier.WORKING and age >= self.archive_horizon and m.importance < 0.35:
                updated.append(replace(m, tier=MemoryTier.ARCHIVE, status=BeliefStatus.EXPIRED))
            elif m.tier == MemoryTier.WORKING:
                working_mems.append(m)
            else:
                updated.append(m)

        # 3. Enforce working memory capacity (evict excess to archive)
        if len(working_mems) > self.working_memory_capacity:
            # Sort by importance * recency descending
            working_mems.sort(
                key=lambda m: m.importance / (1 + max(0, current_day - m.game_day)),
                reverse=True,
            )
            retained = working_mems[: self.working_memory_capacity]
            evicted = [
                replace(m, tier=MemoryTier.ARCHIVE, status=BeliefStatus.EXPIRED)
                for m in working_mems[self.working_memory_capacity :]
            ]
            updated.extend(retained)
            updated.extend(evicted)
        else:
            updated.extend(working_mems)

        return other_mems + updated
