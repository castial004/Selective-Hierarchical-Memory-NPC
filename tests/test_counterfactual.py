from npc_memory_project.core.models import NPCState,WorldState,MemoryRecord,MemoryTier
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import CounterfactualExplanationVerifier
def test_counterfactual_detects_causal_memory():
    npc=NPCState('mira','shopkeeper',10,{'fairness':.9,'cautious':.6},{'medicine':5}); world=WorldState(4,'shop',True); m=MemoryRecord('i','mira','Guard proved innocence.','innocence_verified',3,MemoryTier.SEMANTIC,1,.95); ev=CounterfactualExplanationVerifier(UtilityDecisionEngine()).verify_memories(npc,world,[m]); assert ev[0].changed_action is True
