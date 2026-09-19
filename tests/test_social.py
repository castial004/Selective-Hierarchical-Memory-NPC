from npc_memory_project.core.models import MemoryRecord, MemoryTier, NPCState
from npc_memory_project.social.rumours import RumourDiffusion

def test_rumour_diffusion_attenuates_confidence():
    speaker = NPCState("arun", "vendor", trust=0.0)
    listener = NPCState("mira", "shopkeeper", trust=-10.0)

    original = MemoryRecord(
        "e_orig", "arun", "Player took gold from the square", "theft", 1,
        MemoryTier.EPISODIC, importance=0.8, confidence=0.90,
    )

    diffuser = RumourDiffusion(base_attenuation=0.85)
    event = diffuser.share_memory(original, speaker, listener, game_day=2, speaker_listener_trust=-20.0)

    assert event.target_npc == "mira"
    assert event.actor == "arun"
    # attenuated confidence should be lower than original (0.90 * 0.85 * (1 - 20/250) = 0.90 * 0.85 * 0.92 = ~0.70)
    assert event.confidence < 0.80
    assert "Arun told me" in event.description
    assert "source_chain" in event.metadata
