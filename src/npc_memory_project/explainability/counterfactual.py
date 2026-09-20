"""Counterfactually verified explanation: leave-one-out memory ablation.

v0.2.1 changes
--------------
* **Lineage-aware ablation.** v0.2 removed exactly one memory per trial. Now that
  derived records carry lineage (``derived_from`` / ``origin_event_id``, set by
  :class:`~npc_memory_project.beliefs.updater.ContradictionAwareBeliefUpdater`
  and :class:`~npc_memory_project.memory.consolidation.SemanticConsolidator`),
  ablating only the source leaves its summaries in place -- the signal survives,
  no action flips, and the real cause is reported as causally inert. Ablation
  therefore removes the memory *and its transitive descendants*, which is the
  correct counterfactual: a world where the guard never proved Rohan's innocence
  is also a world without the "player was falsely accused" summary.
* ``ablation_group`` is public so the inspector UI can show what a trial
  actually removed.

SCOPE / INTERPRETATION
----------------------
Two things this verifier is NOT, both worth stating in the paper:

1. The intervention is "the NPC had *forgotten* m", not "m never happened".
   Removing a memory also removes its effect on retrieval ranking, so this is a
   deletion counterfactual rather than a causal counterfactual.
2. Ablation covers retrieved memories only. Trust, personality and world flags
   are never ablated, so the reported factors explain the *memory* contribution
   to the decision, not the decision.

Also note ``delta_u = U(a*) - U(a*_{\\m})`` uses top scores. Since removing a
memory can only lower feature values, ``delta_u >= 0`` in practice, so the
paper's ``|delta_u| >= theta_causal`` disjunct is one-sided here.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Set

from npc_memory_project.core.models import ExplanationEvidence, MemoryRecord
from npc_memory_project.decision.engine import UtilityDecisionEngine


def _direct_sources(memory: MemoryRecord) -> Set[str]:
    sources: Set[str] = set()
    raw = memory.metadata.get("derived_from")
    if raw:
        sources.update(part.strip() for part in str(raw).split(",") if part.strip())
    origin = memory.metadata.get("origin_event_id")
    if origin:
        sources.add(origin)
    return sources


def lineage_closure(memories: Sequence[MemoryRecord], root_ids: Iterable[str]) -> Set[str]:
    """Return ``root_ids`` plus every memory transitively derived from them."""
    by_id = {m.event_id: m for m in memories}
    closure: Set[str] = {rid for rid in root_ids if rid in by_id}
    changed = True
    while changed:
        changed = False
        for memory in memories:
            if memory.event_id in closure:
                continue
            if _direct_sources(memory) & closure:
                closure.add(memory.event_id)
                changed = True
    return closure


class CounterfactualExplanationVerifier:
    """Certify which retrieved memories materially caused the chosen action."""

    def __init__(self, engine: UtilityDecisionEngine, *, follow_lineage: bool = True) -> None:
        self.engine = engine
        self.follow_lineage = follow_lineage

    def ablation_group(
        self, memories: Sequence[MemoryRecord], memory: MemoryRecord
    ) -> Set[str]:
        """The set of memory ids removed when counterfactually ablating ``memory``."""
        if not self.follow_lineage:
            return {memory.event_id}
        return lineage_closure(memories, [memory.event_id])

    def verify_memories(self, npc, world, memories: Sequence[MemoryRecord]) -> List[ExplanationEvidence]:
        """Re-decide once per memory and report the ones that changed the outcome."""
        memories = list(memories)
        original = self.engine.decide(npc, world, memories)
        original_action = original.selected_action
        original_score = original.action_scores[0].score if original.action_scores else 0.0

        evidence: List[ExplanationEvidence] = []
        for memory in memories:
            removed = self.ablation_group(memories, memory)
            reduced = [m for m in memories if m.event_id not in removed]
            trial = self.engine.decide(npc, world, reduced)
            trial_action = trial.selected_action
            trial_score = trial.action_scores[0].score if trial.action_scores else 0.0

            evidence.append(
                ExplanationEvidence(
                    factor_name=memory.summary,
                    original_action=original_action,
                    action_without_factor=trial_action,
                    original_score=original_score,
                    score_without_factor=trial_score,
                    changed_action=trial_action != original_action,
                    score_delta=original_score - trial_score,
                    memory_id=memory.event_id,
                )
            )

        return sorted(
            evidence,
            key=lambda e: (e.changed_action, abs(e.score_delta)),
            reverse=True,
        )
