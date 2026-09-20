"""Contradiction-aware belief revision.

Tracks competing claims about the same contested fact (``conflict_key``) without
destructive erasure: superseded claims are preserved for historical
accountability but excluded from decision retrieval.

v0.2.1 changes
--------------
* **No in-place mutation.** v0.2 did ``incoming.status = DISPUTED`` -- mutating a
  caller-owned ``MemoryRecord`` while returning a new list for the other
  records. It now returns a replaced copy, consistently.
* **Corroboration actually accumulates -- but only from independent sources.**
  v0.2 left confidence untouched on corroboration, so ten independent witnesses
  were worth exactly as much as one. Naively aggregating would be worse,
  however: rumour echo would then inflate confidence without evidence. The bump
  is therefore gated on source independence (a different source, and neither the
  origin event nor the speaker already in the incoming ``source_chain``).
* **Feature channel is attached at revision time**, so belief records can
  influence decisions (see ``core/features.py``).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.core.features import feature_key_for_claim, features_of
from npc_memory_project.core.models import BeliefStatus, MemoryRecord, MemoryTier


class ContradictionAwareBeliefUpdater:
    """Resolve contested claims and emit derived beliefs."""

    def __init__(self, corroboration_gain: float = 0.05) -> None:
        #: Fraction of the remaining distance to certainty added when an
        #: *independent* source asserts the same claim. 0.0 disables aggregation.
        self.corroboration_gain = corroboration_gain

    # ------------------------------------------------------------- internals
    @staticmethod
    def _is_independent(old: MemoryRecord, incoming: MemoryRecord) -> bool:
        """True when ``incoming`` is not just an echo of ``old``'s own source."""
        if incoming.source == old.source:
            return False
        if incoming.metadata.get("origin_event_id") == old.event_id:
            return False          # hearsay about this very memory
        chain = [part.strip() for part in (incoming.metadata.get("source_chain") or "").split("->")]
        if old.source in chain:
            return False
        return True

    @staticmethod
    def _with_feature_key(memory: MemoryRecord) -> MemoryRecord:
        """Attach the feature channel implied by the asserted claim."""
        if features_of(memory):
            return memory          # legacy keyword match already covers it
        key = feature_key_for_claim(memory.metadata.get("claim"))
        if not key:
            return memory
        metadata = dict(memory.metadata)
        metadata["feature_key"] = key
        return replace(memory, metadata=metadata)

    # ------------------------------------------------------------------- API
    def revise(
        self, existing: Sequence[MemoryRecord], incoming: MemoryRecord
    ) -> Tuple[List[MemoryRecord], MemoryRecord]:
        """Reconcile ``incoming`` against ``existing``. Returns (revised, incoming)."""
        key = incoming.metadata.get("conflict_key")
        claim = incoming.metadata.get("claim")
        if not key or not claim:
            return list(existing), incoming

        incoming = self._with_feature_key(incoming)

        revised: List[MemoryRecord] = []
        for old in existing:
            same_key = old.metadata.get("conflict_key") == key
            old_claim = old.metadata.get("claim")

            if same_key and old_claim and old_claim != claim:
                if incoming.confidence > old.confidence:
                    old = replace(old, status=BeliefStatus.SUPERSEDED)
                else:
                    incoming = replace(incoming, status=BeliefStatus.DISPUTED)
            elif same_key and old_claim == claim and incoming.confidence >= old.confidence:
                if self._is_independent(old, incoming):
                    old = replace(
                        old,
                        status=BeliefStatus.CORROBORATED,
                        confidence=min(
                            1.0, old.confidence + self.corroboration_gain * (1.0 - old.confidence)
                        ),
                    )
                else:
                    old = replace(old, status=BeliefStatus.CORROBORATED)
            revised.append(old)

        return revised, incoming

    def build_semantic_belief(
        self,
        *,
        npc_id: str,
        event_id: str,
        summary: str,
        event_type: str,
        game_day: int,
        confidence: float,
        metadata: Optional[Dict[str, str]] = None,
        derived_from: Optional[Sequence[str]] = None,
    ) -> MemoryRecord:
        """Construct a SEMANTIC record, linked to the evidence it summarises.

        ``derived_from`` is what makes lineage-aware ablation possible: without
        it a summary survives the ablation of its own source and the verifier
        wrongly reports that the source had no causal effect.
        """
        meta: Dict[str, str] = dict(metadata or {})
        if derived_from:
            meta["derived_from"] = ",".join(str(x) for x in derived_from)
        key = feature_key_for_claim(meta.get("claim"))
        if key:
            meta["feature_key"] = key
        return MemoryRecord(
            event_id=event_id,
            npc_id=npc_id,
            summary=summary,
            event_type=event_type,
            game_day=game_day,
            tier=MemoryTier.SEMANTIC,
            importance=1.0,
            confidence=confidence,
            source="belief_revision",
            tags=["semantic", "belief"],
            metadata=meta,
        )
