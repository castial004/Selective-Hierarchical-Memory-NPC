from dataclasses import replace
from typing import List,Tuple
from npc_memory_project.core.models import MemoryRecord,BeliefStatus,MemoryTier

class ContradictionAwareBeliefUpdater:
    def revise(self,existing:List[MemoryRecord],incoming:MemoryRecord)->Tuple[List[MemoryRecord],MemoryRecord]:
        key=incoming.metadata.get('conflict_key'); claim=incoming.metadata.get('claim')
        if not key or not claim: return existing,incoming
        out=[]
        for old in existing:
            same=old.metadata.get('conflict_key')==key; old_claim=old.metadata.get('claim')
            if same and old_claim and old_claim!=claim:
                if incoming.confidence>old.confidence: old=replace(old,status=BeliefStatus.SUPERSEDED)
                else: incoming.status=BeliefStatus.DISPUTED
            elif same and old_claim==claim and incoming.confidence>=old.confidence:
                old=replace(old,status=BeliefStatus.CORROBORATED)
            out.append(old)
        return out,incoming
    def build_semantic_belief(self,*,npc_id,event_id,summary,event_type,game_day,confidence,metadata):
        return MemoryRecord(event_id,npc_id,summary,event_type,game_day,MemoryTier.SEMANTIC,1.0,confidence,source='belief_revision',tags=['semantic','belief'],metadata=metadata)
