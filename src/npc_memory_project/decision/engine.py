from npc_memory_project.core.models import NPCState,WorldState,MemoryRecord,ActionScore,DecisionTrace
from npc_memory_project.decision.valid_actions import valid_actions

class UtilityDecisionEngine:
    def _features(self,memories):
        theft=max([m.importance*m.confidence for m in memories if 'theft' in m.event_type],default=0)
        innocence=max([m.importance*m.confidence for m in memories if 'innocence' in m.event_type],default=0)
        helpv=max([m.importance*m.confidence for m in memories if 'help' in m.event_type],default=0)
        return theft,innocence,helpv
    def score_actions(self,npc:NPCState,world:WorldState,memories):
        allowed=valid_actions(npc,world); theft,innocence,helpv=self._features(memories)
        low=max(0,-npc.trust/100); high=max(0,npc.trust/100); fair=npc.personality.get('fairness',.5); cautious=npc.personality.get('cautious',.5)
        scores={}
        def add(action,factors):
            if action in allowed: scores[action]=ActionScore(action,sum(factors.values()),factors)
        add('trade',{'base':.25,'high_trust':.45*high,'innocence_memory':.20*innocence})
        add('offer_discount',{'base':.10,'high_trust':.40*high,'help_memory':.30*helpv})
        add('refuse_trade',{'base':.05,'theft_memory':.45*theft,'low_trust':.35*low,'cautious':.15*cautious})
        add('warn_player',{'base':.10,'theft_memory':.25*theft,'low_trust':.20*low,'cautious':.20*cautious})
        add('call_guard',{'base':.05,'theft_memory':.35*theft,'low_trust':.20*low,'cautious':.20*cautious})
        add('apologise',{'base':.02,'innocence_memory':.55*innocence,'fairness':.15*fair})
        add('ignore',{'base':.05}); add('talk',{'base':.20}); add('help_player',{'base':.10,'high_trust':.40*high}); add('question_player',{'base':.10,'theft_memory':.25*theft}); add('arrest_player',{'base':.05,'theft_memory':.55*theft})
        return sorted(scores.values(),key=lambda x:x.score,reverse=True)
    def decide(self,npc,world,memories):
        s=self.score_actions(npc,world,memories); selected=s[0].action if s else 'ignore'
        return DecisionTrace(npc.npc_id,selected,s,[m.event_id for m in memories],{'role':npc.role,'location':world.location,'game_day':str(world.game_day)})
