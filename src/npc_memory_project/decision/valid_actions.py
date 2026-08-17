from npc_memory_project.core.models import NPCState,WorldState
ROLE_ACTIONS={
'shopkeeper':['trade','offer_discount','refuse_trade','warn_player','apologise','call_guard'],
'guard':['warn_player','question_player','arrest_player','apologise','ignore'],
'villager':['talk','help_player','warn_player','apologise','ignore']}

def valid_actions(npc:NPCState,world:WorldState):
    a=list(ROLE_ACTIONS.get(npc.role,['talk','ignore']))
    if npc.role=='shopkeeper' and (npc.inventory.get('medicine',0)<=0 or not world.player_has_money):
        a=[x for x in a if x not in {'trade','offer_discount'}]
    if npc.role!='guard': a=[x for x in a if x!='arrest_player']
    return a
