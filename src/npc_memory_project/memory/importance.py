from npc_memory_project.core.models import GameEvent

def decision_impact_score(event:GameEvent)->float:
    score=(0.30*abs(event.relationship_impact)+0.25*event.emotional_impact+0.20*event.quest_relevance+0.15*event.novelty+0.10*event.confidence)
    return max(0.0,min(1.0,score))
