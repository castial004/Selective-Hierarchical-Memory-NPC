from npc_memory_project.simulation.town_simulation import TownSimulation

def test_town_simulation_lifecycle_and_interaction():
    sim = TownSimulation()
    assert sim.world.game_day == 1

    # Day 1: Mira should refuse trade or warn because of accusation
    res1 = sim.interact_with_npc("mira")
    assert res1["selected_action"] in {"warn_player", "refuse_trade"}

    # Advance to Day 2
    sim.advance_day()
    assert sim.world.game_day == 2

    # Advance to Day 3: Kael reveals Rohan was thief
    sim.advance_day()
    assert sim.world.game_day == 3

    # Advance to Day 4: Mira should now apologise
    sim.advance_day()
    assert sim.world.game_day == 4

    res4 = sim.interact_with_npc("mira")
    assert res4["selected_action"] == "apologise"
    dialogue_lower = res4["dialogue"].lower()
    assert any(word in dialogue_lower for word in ("sorry", "apologize", "apology", "apologise", "i was wrong")), \
        f"Expected apologetic dialogue, got: {res4['dialogue']}"
