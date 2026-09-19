from npc_memory_project.core.models import NPCState, WorldState
from npc_memory_project.decision.valid_actions import valid_actions

def test_shopkeeper_cannot_trade_without_stock():
    npc = NPCState("mira", "shopkeeper", trust=10, inventory={"medicine": 0})
    world = WorldState(1, "shop", player_has_money=True)
    actions = valid_actions(npc, world)
    assert "trade" not in actions
    assert "offer_discount" not in actions

def test_non_guard_cannot_arrest():
    npc = NPCState("arun", "vendor", trust=0)
    world = WorldState(1, "market", player_has_money=True, player_wanted=True)
    actions = valid_actions(npc, world)
    assert "arrest_player" not in actions
