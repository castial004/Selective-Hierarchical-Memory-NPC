import pytest
from npc_memory_project.core.models import NPCState, ExplanationEvidence
from npc_memory_project.explainability.dialogue import (
    FaithfulDialogueSynthesizer,
    LLMDialogueHook,
    PERSONA_REGISTRY,
)
from npc_memory_project.simulation.town_simulation import TownSimulation


def test_persona_registry_completeness():
    assert "mira" in PERSONA_REGISTRY
    assert "arun" in PERSONA_REGISTRY
    assert "kael" in PERSONA_REGISTRY
    assert "rohan" in PERSONA_REGISTRY

    mira_p = PERSONA_REGISTRY["mira"]
    assert "remedy" in mira_p.keywords or "herbs" in mira_p.keywords
    assert "cautious" in mira_p.tone


def test_faithful_dialogue_with_causal_evidence():
    synthesizer = FaithfulDialogueSynthesizer()

    npc = NPCState(
        npc_id="mira",
        role="shopkeeper",
        trust=-20.0,
        personality={"fairness": 0.9},
    )

    evidence = [
        ExplanationEvidence(
            factor_name="Arun accused player of theft",
            original_action="refuse_trade",
            action_without_factor="trade",
            original_score=0.65,
            score_without_factor=0.20,
            changed_action=True,
            score_delta=-0.45,
        )
    ]

    res = synthesizer.synthesize(npc, "refuse_trade", evidence)

    assert res["faithful"] is True
    assert res["grounded_factor"] == "Arun accused player of theft"
    assert "Arun accused player of theft" in res["dialogue"]
    assert "cautious" in res["persona"]


def test_faithful_dialogue_apology():
    synthesizer = FaithfulDialogueSynthesizer()

    npc = NPCState(
        npc_id="mira",
        role="shopkeeper",
        trust=15.0,
        personality={"fairness": 0.9},
    )

    evidence = [
        ExplanationEvidence(
            factor_name="Officer Kael proved Rohan was the thief",
            original_action="apologise",
            action_without_factor="warn_player",
            original_score=0.80,
            score_without_factor=0.20,
            changed_action=True,
            score_delta=0.60,
        )
    ]

    res = synthesizer.synthesize(npc, "apologise", evidence)
    assert res["faithful"] is True
    assert "apology" in res["dialogue"].lower() or "apologize" in res["dialogue"].lower()
    assert "Officer Kael proved Rohan was the thief" in res["dialogue"]


def test_llm_hook_offline_fallback():
    # When no API key is provided, LLMDialogueHook must safely return base_dialogue untouched
    hook = LLMDialogueHook(api_key=None, endpoint=None)
    assert hook.is_configured is False

    npc = NPCState(npc_id="kael", role="guard", trust=0.0)
    persona = PERSONA_REGISTRY["kael"]

    base = "Halt in the name of the law! Drop your gear."
    polished = hook.polish(base, npc, persona, ["Theft reported in pharmacy"])
    assert polished == base


def test_town_simulation_dialogue_integration():
    sim = TownSimulation()

    # Day 1: Mira refuses trade or warns player based on accusation
    res1 = sim.interact_with_npc("mira")
    assert res1["selected_action"] in {"refuse_trade", "warn_player"}
    assert "dialogue" in res1
    assert "grounded_factor" in res1
    assert "persona" in res1

    # Advance to Day 3 where evidence exonerates player
    sim.advance_day() # Day 2
    sim.advance_day() # Day 3
    sim.advance_day() # Day 4

    res4 = sim.interact_with_npc("mira")
    assert res4["selected_action"] == "apologise"
    assert "apolog" in res4["dialogue"].lower()
