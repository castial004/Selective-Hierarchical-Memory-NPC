from npc_memory_project.core.models import GameEvent,MemoryTier
from npc_memory_project.memory.manager import HierarchicalMemoryManager
def test_high_impact_event_becomes_episodic():
    e=GameEvent('theft','player','mira','Player stole medicine.',1,'shop',.9,-1,.5,.9,confidence=1)
    m=HierarchicalMemoryManager().event_to_memory(e); assert m.tier==MemoryTier.EPISODIC; assert m.importance>.6
def test_low_impact_event_remains_working():
    e=GameEvent('greeting','player','mira','Player said hello.',1,'shop',.05,.05,0,.05,confidence=1)
    assert HierarchicalMemoryManager().event_to_memory(e).tier==MemoryTier.WORKING
