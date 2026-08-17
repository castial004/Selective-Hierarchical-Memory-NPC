from npc_memory_project.core.models import NPCState,WorldState,MemoryRecord,MemoryTier
from npc_memory_project.decision.engine import UtilityDecisionEngine
def test_verified_innocence_can_make_apology_best_action():
    npc=NPCState('mira','shopkeeper',10,{'fairness':.9,'cautious':.6},{'medicine':5}); world=WorldState(4,'shop',True); m=MemoryRecord('i','mira','Guard proved innocence.','innocence_verified',3,MemoryTier.SEMANTIC,1,.95)
    assert UtilityDecisionEngine().decide(npc,world,[m]).selected_action=='apologise'
