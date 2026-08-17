from typing import List
from npc_memory_project.core.models import GameEvent,MemoryRecord,MemoryTier,BeliefStatus
from npc_memory_project.memory.importance import decision_impact_score

class HierarchicalMemoryManager:
    def __init__(self,episodic_threshold:float=0.45,semantic_threshold:float=0.78):
        self.episodic_threshold=episodic_threshold
        self.semantic_threshold=semantic_threshold
    def choose_tier(self,event:GameEvent)->MemoryTier:
        s=decision_impact_score(event)
        if s>=self.semantic_threshold and event.metadata.get('is_summary')=='true': return MemoryTier.SEMANTIC
        if s>=self.episodic_threshold: return MemoryTier.EPISODIC
        return MemoryTier.WORKING
    def event_to_memory(self,event:GameEvent)->MemoryRecord:
        s=decision_impact_score(event)
        return MemoryRecord(event.event_id,event.target_npc,event.description,event.event_type,event.game_day,self.choose_tier(event),s,event.confidence,source=event.source,tags=[event.event_type,event.actor,event.target_npc,event.location],metadata=dict(event.metadata))
    def retrieve(self,memories:List[MemoryRecord],*,npc_id:str,current_day:int,event_type:str|None=None,top_k:int=5)->List[MemoryRecord]:
        cand=[m for m in memories if m.npc_id==npc_id and m.status not in {BeliefStatus.SUPERSEDED,BeliefStatus.EXPIRED}]
        scored=[]
        for m in cand:
            rel=1.0 if event_type and m.event_type==event_type else 0.45
            rec=1/(1+max(0,current_day-m.game_day))
            bonus=0.20 if m.status in {BeliefStatus.ACTIVE,BeliefStatus.CORROBORATED} else 0
            scored.append((0.45*rel+0.30*m.importance+0.20*rec+0.05*m.confidence+bonus,m))
        scored.sort(key=lambda x:x[0],reverse=True)
        return [m for _,m in scored[:top_k]]
