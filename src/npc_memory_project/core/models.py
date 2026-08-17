from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List
import uuid

class MemoryTier(str, Enum):
    WORKING="working"
    EPISODIC="episodic"
    SEMANTIC="semantic"
    ARCHIVE="archive"

class BeliefStatus(str, Enum):
    ACTIVE="active"
    DISPUTED="disputed"
    RESOLVED="resolved"
    SUPERSEDED="superseded"
    CORROBORATED="corroborated"
    EXPIRED="expired"

@dataclass
class GameEvent:
    event_type:str
    actor:str
    target_npc:str
    description:str
    game_day:int
    location:str
    emotional_impact:float=0.0
    relationship_impact:float=0.0
    quest_relevance:float=0.0
    novelty:float=0.0
    source:str="direct"
    confidence:float=1.0
    metadata:Dict[str,str]=field(default_factory=dict)
    event_id:str=field(default_factory=lambda:str(uuid.uuid4()))

@dataclass
class MemoryRecord:
    event_id:str
    npc_id:str
    summary:str
    event_type:str
    game_day:int
    tier:MemoryTier
    importance:float
    confidence:float
    status:BeliefStatus=BeliefStatus.ACTIVE
    source:str="direct"
    tags:List[str]=field(default_factory=list)
    metadata:Dict[str,str]=field(default_factory=dict)

@dataclass
class NPCState:
    npc_id:str
    role:str
    trust:float=0.0
    personality:Dict[str,float]=field(default_factory=dict)
    inventory:Dict[str,int]=field(default_factory=dict)
    goals:List[str]=field(default_factory=list)
    hostile:bool=False

@dataclass
class WorldState:
    game_day:int
    location:str
    player_has_money:bool=True
    player_wanted:bool=False
    metadata:Dict[str,str]=field(default_factory=dict)

@dataclass
class ActionScore:
    action:str
    score:float
    factors:Dict[str,float]

@dataclass
class DecisionTrace:
    npc_id:str
    selected_action:str
    action_scores:List[ActionScore]
    retrieved_memory_ids:List[str]
    context:Dict[str,str]=field(default_factory=dict)

@dataclass
class ExplanationEvidence:
    factor_name:str
    original_action:str
    action_without_factor:str
    original_score:float
    score_without_factor:float
    changed_action:bool
    score_delta:float
