"""Blind export for independent annotation.

Purpose
-------
Produce a case file that reveals ONLY what an annotator needs to judge a
decision: NPC state, world state, the admissible action menu, the memories with
their tier/status/importance/confidence/provenance, and an anonymous case id.

Everything that could reveal the expected answer is removed:

* the author's expected action family, rationale and accepted alternatives
* the label source (author / human / llm)
* the original case id, which in this repository spells out the answer
  (for example no-stock-removes-trade, exoneration-restores-warmth,
  guard-without-warrant-cannot-arrest)
* any method name, retrieved set, action score, utility factor or weight
* engine-internal feature channels (metadata feature_key), which map one-to-one
  onto the utility weights and are not provenance information

An audit function is provided so the guarantee is testable rather than asserted:
audit_blind_payload returns a list of leaks, empty when the payload is clean.

What is deliberately KEPT
-------------------------
Memory provenance metadata that a rater legitimately needs: claim, conflict_key,
source_chain, derived_from, origin_event_id, semantic_group_id, target_actor,
interaction_count, obligation. Memory event ids are kept so a rater can cite
decisive_memory_ids; they are internal identifiers, not answers.

The status taxonomy (active / corroborated / disputed / superseded / expired) and
the tier names (working / episodic / semantic / archive) are kept because the
annotation protocol asks raters to interpret them. They are properties of the
state, not of the answer.

This module generates NO labels. It produces the blank instrument only.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from npc_memory_project.decision.valid_actions import valid_actions
from npc_memory_project.evaluation.labelled import author_labelled_cases

BLIND_SCHEMA = "shm-npc/blind-cases/1"

#: Keys that must never appear anywhere in a blind case file. Matched exactly on
#: dict keys, case-insensitively.
FORBIDDEN_KEYS = frozenset({
    "expected_family", "expected_actions", "expected_action",
    "acceptable_actions", "alternatives",
    "rationale", "author_label", "label_source", "adjudicated_family",
    "raters", "rater", "rater_view", "facilitator_key",
    "method", "methods", "selected_action", "action_scores", "factors",
    "weights", "score", "scores", "prediction", "predicted_action",
    "annotator_type", "blind", "bias_disclosure",
    "feature_key",
})

#: Substrings that must not appear in the serialized payload. These are method
#: names and engine vocabulary that would let a rater identify the system or
#: reverse-engineer the scoring.
FORBIDDEN_SUBSTRINGS = (
    "shm (this architecture)", "recency-only", "importance-only",
    "status-aware", "tiers, status-blind", "recency+importance",
    "utilitydecisionengine", "innocence_memory", "theft_memory",
    "low_trust", "high_trust", "cautious gate",
)

#: Metadata keys kept on memories because they are provenance, not answer.
KEPT_METADATA = frozenset({
    "claim", "conflict_key", "source_chain", "derived_from",
    "origin_event_id", "semantic_group_id", "target_actor",
    "interaction_count", "obligation", "is_summary",
})


def anonymise_case_id(index: int) -> str:
    """Stable, non-revealing case id: case-001, case-002, ..."""
    return f"case-{index + 1:03d}"


def _blind_metadata(metadata: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Keep provenance metadata; drop engine-internal channels."""
    if not metadata:
        return {}
    return {k: str(v) for k, v in metadata.items() if k in KEPT_METADATA}


def _blind_memory(memory) -> Dict[str, object]:
    tier = memory.tier.value if hasattr(memory.tier, "value") else str(memory.tier)
    status = memory.status.value if hasattr(memory.status, "value") else str(memory.status)
    return {
        "event_id": memory.event_id,
        "summary": memory.summary,
        "event_type": memory.event_type,
        "game_day": memory.game_day,
        "tier": tier,
        "status": status,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "source": memory.source,
        "metadata": _blind_metadata(memory.metadata),
    }


def build_blind_payload(*, shuffle_seed: Optional[int] = 20261017) -> Dict[str, object]:
    """Build the blind case instrument from the repository's labelled cases.

    Cases are shuffled with a fixed seed before ids are assigned, so the order of
    the blind file does not correspond to the order of the source cases. Without
    this, case-001 would always be the first author case and someone who has seen
    the repository could map blind ids back by position. The seed is fixed so the
    file is reproducible.
    """
    source_cases = list(author_labelled_cases())
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(source_cases)

    cases: List[Dict[str, object]] = []
    for index, case in enumerate(source_cases):
        npc = case.npc
        world = case.world
        cases.append({
            "case_id": anonymise_case_id(index),
            "npc": {
                "npc_id": npc.npc_id,
                "role": npc.role,
                "trust": npc.trust,
                "personality": dict(npc.personality),
                "inventory": dict(npc.inventory or {}),
                "hostile": npc.hostile,
            },
            "world": {
                "game_day": world.game_day,
                "location": world.location,
                "player_has_money": world.player_has_money,
                "player_wanted": world.player_wanted,
                "metadata": dict(world.metadata or {}),
            },
            "action_menu": valid_actions(npc, world),
            "memories": [_blind_memory(m) for m in case.memories],
        })

    return {
        "schema": BLIND_SCHEMA,
        "instructions": (
            "Judge only from the state shown. Select every action a reasonable NPC "
            "could defensibly take, choose one preferred action, and cite the "
            "decisive memory ids. Only actions in this case's action_menu may be "
            "chosen. No expected answer is supplied and none exists in this file."
        ),
        "action_family_taxonomy": {
            "trade": "warm", "offer_discount": "warm", "apologise": "warm",
            "help_player": "warm",
            "refuse_trade": "punitive", "warn_player": "punitive",
            "call_guard": "punitive", "arrest_player": "punitive",
            "question_player": "informative", "report_findings": "informative",
            "talk": "neutral", "ignore": "neutral", "deny": "neutral",
            "flee": "neutral", "bribe": "neutral", "spread_rumour": "neutral",
            "confess": "neutral",
        },
        "cases": cases,
    }


def export_blind_cases(path: Path) -> Dict[str, object]:
    payload = build_blind_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


# ------------------------------------------------------------------- audit
def _walk_keys(node, trail: str = "") -> List[str]:
    """Yield every dict key path in the structure."""
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(f"{trail}.{key}" if trail else str(key))
            found.extend(_walk_keys(value, f"{trail}.{key}" if trail else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_walk_keys(value, f"{trail}[{i}]"))
    return found


def audit_blind_payload(payload: Dict[str, object]) -> List[str]:
    """Return a list of leaks. Empty list means the payload is blind-clean."""
    leaks: List[str] = []

    # 1. forbidden keys anywhere
    for path in _walk_keys(payload):
        leaf = path.split(".")[-1].split("[")[0].lower()
        if leaf in FORBIDDEN_KEYS:
            leaks.append(f"forbidden key present: {path}")

    text = json.dumps(payload, ensure_ascii=False).lower()

    # 2. method names / engine vocabulary in the serialized text
    for needle in FORBIDDEN_SUBSTRINGS:
        if needle in text:
            leaks.append(f"forbidden substring present: {needle!r}")

    # 3. original case ids (which spell out the expected action)
    for case in author_labelled_cases():
        if case.case_id.lower() in text:
            leaks.append(f"original case id leaked: {case.case_id}")

    # 4. author rationale / alternative text
    for case in author_labelled_cases():
        probe = case.rationale.strip()[:40].lower()
        if probe and probe in text:
            leaks.append(f"author rationale leaked for {case.case_id}")

    # 5. case ids must be anonymous
    for entry in payload.get("cases", []):
        cid = str(entry.get("case_id", ""))
        if not re.fullmatch(r"case-\d{3}", cid):
            leaks.append(f"non-anonymous case id: {cid!r}")

    # 5b. the blind order must not mirror the source order
    originals = [c.case_id for c in author_labelled_cases()]
    if len(originals) >= 3:
        blind_worlds = [
            (e.get("world", {}).get("game_day"), e.get("world", {}).get("location"),
             e.get("npc", {}).get("role"), len(e.get("memories", [])))
            for e in payload.get("cases", [])
        ]
        source_worlds = [
            (c.world.game_day, c.world.location, c.npc.role, len(c.memories))
            for c in author_labelled_cases()
        ]
        if blind_worlds == source_worlds:
            leaks.append(
                "blind case order matches the source order -- shuffle before "
                "assigning ids so position does not reveal the source case"
            )

    # 6. every case must expose the fields a rater needs
    for entry in payload.get("cases", []):
        cid = entry.get("case_id")
        for field in ("npc", "world", "action_menu", "memories"):
            if field not in entry:
                leaks.append(f"{cid}: missing required field {field}")
        if not entry.get("action_menu"):
            leaks.append(f"{cid}: empty action_menu")

    # 7. decisive-memory citation must be possible: ids must exist and be unique
    for entry in payload.get("cases", []):
        ids = [m.get("event_id") for m in entry.get("memories", [])]
        if len(ids) != len(set(ids)):
            leaks.append(f"{entry.get('case_id')}: duplicate memory event_id")

    return leaks
