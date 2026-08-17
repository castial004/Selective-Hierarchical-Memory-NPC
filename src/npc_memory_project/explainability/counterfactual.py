from npc_memory_project.core.models import ExplanationEvidence
from npc_memory_project.decision.engine import UtilityDecisionEngine

class CounterfactualExplanationVerifier:
    def __init__(self,engine:UtilityDecisionEngine): self.engine=engine
    def verify_memories(self,npc,world,memories):
        orig=self.engine.decide(npc,world,memories); oa=orig.selected_action; os=orig.action_scores[0].score if orig.action_scores else 0
        out=[]
        for m in memories:
            reduced=[x for x in memories if x.event_id!=m.event_id]; tr=self.engine.decide(npc,world,reduced); na=tr.selected_action; ns=tr.action_scores[0].score if tr.action_scores else 0
            out.append(ExplanationEvidence(m.summary,oa,na,os,ns,na!=oa,os-ns))
        return sorted(out,key=lambda e:(e.changed_action,abs(e.score_delta)),reverse=True)
