"""Explicit causal-feature channel for memory records.

Why this module exists
----------------------
v0.2 inferred the decision-relevant signal from ``event_type`` by substring match
against a fixed list (``"theft" in event_type``, ``"innocence" in event_type``,
...). Two consequences:

1. Semantic beliefs written by :class:`ContradictionAwareBeliefUpdater` and
   :class:`SemanticConsolidator` (``belief_player_falsely_accused``,
   ``semantic_consensus``) matched no keyword, so the entire Semantic tier had
   **zero** influence on any decision, while still consuming retrieval slots and
   a documented 1.1x tier multiplier.
2. A single event could silently trip several features at once
   (``rumour_theft_accusation`` set both ``theft`` and ``rumour``).

v0.2.1 adds ``metadata["feature_key"]``, written by the components that actually
know what a record means. The legacy keyword scan is preserved as a fallback so
records that predate the field behave exactly as before.

NOTE ON SCOPE: :data:`CLAIM_FEATURES` is scenario vocabulary (the bundled Mira
theft scenario). A production system should carry feature vocabulary in the
scenario definition rather than in library code -- see CHANGELOG-AUDIT.md.
"""

from __future__ import annotations

from typing import FrozenSet, Mapping, Optional

#: The causal feature channels the utility engine consumes, in fixed order.
FEATURE_KEYS = ("theft", "innocence", "help", "rumour", "confession")

#: Legacy v0.2 event_type substrings. Preserved verbatim for backwards
#: compatibility -- including its ability to trip several features at once.
LEGACY_ALIASES: Mapping[str, tuple] = {
    "theft": ("theft",),
    "innocence": ("innocence",),
    "help": ("help",),
    "rumour": ("rumour",),
    "confession": ("confess",),
}

#: Scenario-specific fallback: map a belief *claim* to the feature it evidences.
#: ``rohan_stole`` exonerates the player here, so it evidences innocence rather
#: than theft; this is why claim->feature cannot be derived mechanically.
CLAIM_FEATURES: Mapping[str, str] = {
    "player_stole": "theft",
    "player_falsely_accused": "innocence",
    "rohan_stole": "innocence",
}


def feature_key_for_claim(claim: Optional[str]) -> Optional[str]:
    """Return the feature channel implied by a belief claim, if known."""
    if not claim:
        return None
    return CLAIM_FEATURES.get(claim)


def features_of(memory) -> FrozenSet[str]:
    """Resolve the feature channels a memory contributes to.

    Precedence:
      1. explicit ``metadata["feature_key"]`` (validated against FEATURE_KEYS);
      2. legacy substring scan over ``event_type`` (may return several);
      3. empty set -- the record is context only and cannot move a decision.
    """
    meta = getattr(memory, "metadata", None) or {}
    explicit = meta.get("feature_key")
    if explicit in FEATURE_KEYS:
        return frozenset((explicit,))

    event_type = (getattr(memory, "event_type", "") or "").lower()
    matched = {
        key for key, needles in LEGACY_ALIASES.items()
        if any(needle in event_type for needle in needles)
    }
    if matched:
        return frozenset(matched)

    # Last resort for belief records: use the claim they assert.
    claim_feature = feature_key_for_claim(meta.get("claim"))
    return frozenset((claim_feature,)) if claim_feature else frozenset()
