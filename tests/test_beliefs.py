from npc_memory_project.core.models import MemoryRecord,MemoryTier,BeliefStatus
from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
def test_stronger_conflicting_belief_supersedes_old():
    old=MemoryRecord('old','mira','Player stole.','theft_accusation',1,MemoryTier.EPISODIC,.8,.6,metadata={'conflict_key':'x','claim':'player'})
    new=MemoryRecord('new','mira','Rohan stole.','innocence_verified',3,MemoryTier.EPISODIC,.9,.95,metadata={'conflict_key':'x','claim':'rohan'})
    updated,incoming=ContradictionAwareBeliefUpdater().revise([old],new); assert updated[0].status==BeliefStatus.SUPERSEDED; assert incoming.status==BeliefStatus.ACTIVE
