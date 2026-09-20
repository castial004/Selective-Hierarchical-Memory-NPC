"""State-valid action filtering.

Every NPC action must pass this layer before utility scoring (see AGENTS.md).
The filter is deliberately conservative: it removes actions that are physically
or socially impossible in the current world state.

v0.2.1 fix
----------
The guard "arrest gate" was a no-op. v0.2 contained::

    if not world.player_wanted and world.metadata.get("suspect") != "player":
        if "arrest_player" in actions and world.metadata.get("permit_arrest") != "true":
            pass        # <-- comment promised enforcement, code did nothing

so a guard could arrest an unwarranted player purely on the strength of a
memory. Verified before the fix::

    valid_actions(guard, wanted=False, no permit) -> [... 'arrest_player' ...]
    decide(...)                                  -> 'arrest_player'

i.e. the paper's "Guaranteed Game-State Validity" claim was broken for the one
rule that encodes game law. The gate now actually prunes.
"""

from __future__ import annotations

from typing import Dict, List

from npc_memory_project.core.models import NPCState, WorldState

ROLE_ACTIONS: Dict[str, List[str]] = {
    "shopkeeper": ["trade", "offer_discount", "refuse_trade", "warn_player", "apologise", "call_guard"],
    "guard": ["warn_player", "question_player", "arrest_player", "apologise", "ignore", "report_findings"],
    "vendor": ["trade", "spread_rumour", "warn_player", "talk", "ignore"],
    "suspect": ["talk", "confess", "deny", "flee", "bribe"],
    "villager": ["talk", "help_player", "warn_player", "apologise", "ignore"],
}


def guard_may_arrest(world: WorldState) -> bool:
    """Game law: arrest requires a warrant, a wanted flag, or an active investigation."""
    if world.player_wanted:
        return True
    if world.metadata.get("suspect") == "player":
        return True
    return world.metadata.get("permit_arrest") == "true"


def valid_actions(npc: NPCState, world: WorldState) -> List[str]:
    """Filter a role's action menu down to what is currently admissible."""
    actions = list(ROLE_ACTIONS.get(npc.role, ["talk", "ignore"]))

    if npc.role == "shopkeeper":
        if npc.inventory.get("medicine", 0) <= 0 or not world.player_has_money:
            actions = [x for x in actions if x not in {"trade", "offer_discount"}]
        if npc.trust < -40:
            actions = [x for x in actions if x != "offer_discount"]

    if npc.role == "guard":
        if not guard_may_arrest(world):
            actions = [x for x in actions if x != "arrest_player"]
    else:
        actions = [x for x in actions if x != "arrest_player"]

    if npc.role == "suspect":
        if world.metadata.get("cornered") == "true":
            actions = [x for x in actions if x != "flee"]

    return actions
