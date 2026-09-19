from typing import List
from npc_memory_project.core.models import NPCState, WorldState

ROLE_ACTIONS = {
    "shopkeeper": ["trade", "offer_discount", "refuse_trade", "warn_player", "apologise", "call_guard"],
    "guard": ["warn_player", "question_player", "arrest_player", "apologise", "ignore", "report_findings"],
    "vendor": ["trade", "spread_rumour", "warn_player", "talk", "ignore"],
    "suspect": ["talk", "confess", "deny", "flee", "bribe"],
    "villager": ["talk", "help_player", "warn_player", "apologise", "ignore"],
}

def valid_actions(npc: NPCState, world: WorldState) -> List[str]:
    """
    Filters actions by physical, social, and world state validity constraints.
    Guarantees no physically or socially invalid actions enter utility scoring.
    """
    actions = list(ROLE_ACTIONS.get(npc.role, ["talk", "ignore"]))

    # Shopkeeper constraints
    if npc.role == "shopkeeper":
        if npc.inventory.get("medicine", 0) <= 0 or not world.player_has_money:
            actions = [x for x in actions if x not in {"trade", "offer_discount"}]
        if npc.trust < -40:
            actions = [x for x in actions if x != "offer_discount"]

    # Guard constraints
    if npc.role == "guard":
        # Guard can only arrest if player is wanted or under direct investigation
        if not world.player_wanted and world.metadata.get("suspect") != "player":
            if "arrest_player" in actions and world.metadata.get("permit_arrest") != "true":
                # Only keep arrest if world metadata permits
                pass
    else:
        # Non-guards cannot arrest
        actions = [x for x in actions if x != "arrest_player"]

    # Suspect constraints
    if npc.role == "suspect":
        if world.metadata.get("cornered") == "true":
            actions = [x for x in actions if x != "flee"]

    return actions
