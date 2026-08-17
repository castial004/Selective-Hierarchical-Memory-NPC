from pathlib import Path
import tempfile
from npc_memory_project.core.models import GameEvent,NPCState,WorldState
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import CounterfactualExplanationVerifier
from npc_memory_project.explainability.generator import generate_explanation
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore

def main():
    manager=HierarchicalMemoryManager(); updater=ContradictionAwareBeliefUpdater(); engine=UtilityDecisionEngine(); verifier=CounterfactualExplanationVerifier(engine)
    with tempfile.TemporaryDirectory() as td:
        store=SQLiteMemoryStore(Path(td)/'demo.db')
        mira=NPCState('mira','shopkeeper',-30,{'fairness':.9,'cautious':.7},{'medicine':5})
        e1=GameEvent('theft_accusation','arun','mira',"Arun accused the player of stealing Mira's medicine.",1,'pharmacy',.8,-.7,.3,.8,'arun',.60,{'conflict_key':'medicine_theft','claim':'player_stole'})
        store.upsert(manager.event_to_memory(e1))
        e2=GameEvent('innocence_verified','guard','mira',"The guard proved that Rohan, not the player, stole the medicine.",3,'pharmacy',.9,.8,.6,.9,'guard',.95,{'conflict_key':'medicine_theft','claim':'rohan_stole'})
        incoming=manager.event_to_memory(e2); revised,incoming=updater.revise(store.list_for_npc('mira'),incoming)
        for m in revised: store.upsert(m)
        store.upsert(incoming)
        semantic=updater.build_semantic_belief(npc_id='mira',event_id='semantic-false-accusation',summary="The player was falsely accused of stealing Mira's medicine.",event_type='belief_player_falsely_accused',game_day=3,confidence=.95,metadata={'conflict_key':'medicine_theft','claim':'player_falsely_accused'})
        store.upsert(semantic); mira.trust=10
        memories=store.list_for_npc('mira')
        print('\nStored memories after belief revision')
        for m in memories: print(f"Day {m.game_day}: {m.summary} | {m.tier.value} | {m.status.value}")
        world=WorldState(4,'pharmacy',True,False); retrieved=manager.retrieve(memories,npc_id='mira',current_day=4,top_k=5); trace=engine.decide(mira,world,retrieved)
        print('\nAction scores')
        for x in trace.action_scores: print(f"{x.action:16s} {x.score:.3f} {x.factors}")
        print(f"\nSelected action: {trace.selected_action}")
        ev=verifier.verify_memories(mira,world,retrieved); print('\nCounterfactual checks')
        for x in ev: print(f"Remove: {x.factor_name} -> {x.action_without_factor} | changed={x.changed_action} | delta={x.score_delta:.3f}")
        print('\nExplanation')
        print(generate_explanation(trace.selected_action,ev))
if __name__=='__main__': main()
