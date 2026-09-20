import uuid
from typing import Dict, Optional
from npc_memory_project.core.models import GameEvent, MemoryRecord, NPCState

class RumourDiffusion:
    """
    Simulates verbal hearsay transmission between NPCs with confidence attenuation
    and social trust modulation.
    """

    def __init__(self, base_attenuation: float = 0.85):
        self.base_attenuation = base_attenuation

    def share_memory(
        self,
        memory: MemoryRecord,
        speaker: NPCState,
        listener: NPCState,
        game_day: int,
        speaker_listener_trust: float = 0.0,
        location: str = "town_square",
    ) -> GameEvent:
        """
        Creates a new GameEvent for the listener based on the memory shared by the speaker.
        Confidence is attenuated based on base loss and social trust.

        v0.2.1: ``location`` is now an explicit argument. v0.2 wrote
        ``location=listener.role``, putting a role name ("shopkeeper") into a
        spatial field, which then flowed into the memory's tags and retrieval
        keys.
        """
        # Trust scale: [-100, 100] -> multiplier in [0.5, 1.2]
        trust_mod = 1.0 + (speaker_listener_trust / 250.0)
        attenuated_confidence = min(
            1.0,
            max(0.1, memory.confidence * self.base_attenuation * trust_mod),
        )

        old_chain = memory.metadata.get("source_chain", memory.source)
        new_chain = f"{old_chain}->{speaker.npc_id}"

        event_desc = f"{speaker.npc_id.capitalize()} told me that: {memory.summary}"

        metadata: Dict[str, str] = dict(memory.metadata)
        metadata.update({
            "source_chain": new_chain,
            "origin_event_id": memory.event_id,
            "transmitter": speaker.npc_id,
        })

        return GameEvent(
            event_type=f"rumour_{memory.event_type}",
            actor=speaker.npc_id,
            target_npc=listener.npc_id,
            description=event_desc,
            game_day=game_day,
            location=location,
            emotional_impact=memory.importance * 0.7,
            relationship_impact=0.0,
            quest_relevance=0.8,
            novelty=0.6,
            source=f"hearsay_{speaker.npc_id}",
            confidence=attenuated_confidence,
            metadata=metadata,
            event_id=f"rumour-{uuid.uuid4().hex[:8]}",
        )
