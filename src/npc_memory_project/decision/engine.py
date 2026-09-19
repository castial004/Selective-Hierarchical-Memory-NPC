from typing import List, Dict, Tuple
from npc_memory_project.core.models import (
    NPCState,
    WorldState,
    MemoryRecord,
    ActionScore,
    DecisionTrace,
)
from npc_memory_project.decision.valid_actions import valid_actions

class UtilityDecisionEngine:
    """
    State-valid, multi-factor utility scoring engine.
    Calculates expected utility over pruned candidate actions based on
    personality traits, player trust, and active memory feature vectors.
    """

    def _features(self, memories: List[MemoryRecord]) -> Tuple[float, float, float, float, float]:
        theft = max(
            [m.importance * m.confidence for m in memories if "theft" in m.event_type],
            default=0.0,
        )
        innocence = max(
            [m.importance * m.confidence for m in memories if "innocence" in m.event_type],
            default=0.0,
        )
        helpv = max(
            [m.importance * m.confidence for m in memories if "help" in m.event_type],
            default=0.0,
        )
        rumour = max(
            [m.importance * m.confidence for m in memories if "rumour" in m.event_type],
            default=0.0,
        )
        confession = max(
            [m.importance * m.confidence for m in memories if "confess" in m.event_type],
            default=0.0,
        )
        return theft, innocence, helpv, rumour, confession

    def score_actions(
        self,
        npc: NPCState,
        world: WorldState,
        memories: List[MemoryRecord],
    ) -> List[ActionScore]:
        allowed = valid_actions(npc, world)
        theft, innocence, helpv, rumour, confession = self._features(memories)

        low = max(0.0, -npc.trust / 100.0)
        high = max(0.0, npc.trust / 100.0)
        fair = npc.personality.get("fairness", 0.5)
        cautious = npc.personality.get("cautious", 0.5)
        aggressive = npc.personality.get("aggressive", 0.3)
        remorse = npc.personality.get("remorse", 0.5)

        scores: Dict[str, ActionScore] = {}

        def add(action: str, factors: Dict[str, float]) -> None:
            if action in allowed:
                total = sum(factors.values())
                scores[action] = ActionScore(action, round(total, 4), factors)

        # Shopkeeper actions (strictly matches IEEE paper calibrated weights)
        add("trade", {"base": 0.25, "high_trust": 0.45 * high, "innocence_memory": 0.20 * innocence})
        add("offer_discount", {"base": 0.10, "high_trust": 0.40 * high, "help_memory": 0.30 * helpv})
        add("refuse_trade", {"base": 0.05, "theft_memory": 0.45 * theft, "low_trust": 0.35 * low, "cautious": 0.15 * cautious})
        add("warn_player", {"base": 0.10, "theft_memory": 0.25 * theft, "low_trust": 0.20 * low, "cautious": 0.20 * cautious})
        add("call_guard", {"base": 0.05, "theft_memory": 0.35 * theft, "low_trust": 0.20 * low, "cautious": 0.20 * cautious})
        add("apologise", {"base": 0.02, "innocence_memory": 0.55 * innocence, "fairness": 0.15 * fair})

        # Guard & General actions
        add("ignore", {"base": 0.05})
        add("talk", {"base": 0.20, "high_trust": 0.15 * high})
        add("help_player", {"base": 0.10, "high_trust": 0.40 * high})
        add("question_player", {"base": 0.10, "theft_memory": 0.35 * theft, "cautious": 0.20 * cautious})
        add("arrest_player", {"base": 0.05, "theft_memory": 0.55 * theft, "aggressive": 0.20 * aggressive})
        add("report_findings", {"base": 0.15, "innocence_memory": 0.40 * innocence, "fairness": 0.20 * fair})

        # Vendor & Gossip actions
        add("spread_rumour", {"base": 0.15, "rumour_memory": 0.45 * rumour, "cautious": -0.10 * cautious})

        # Suspect actions
        add("confess", {"base": 0.05, "innocence_memory": 0.40 * innocence, "remorse": 0.35 * remorse})
        add("deny", {"base": 0.20, "theft_memory": 0.30 * theft, "cautious": 0.20 * cautious})
        add("flee", {"base": 0.05, "theft_memory": 0.40 * theft, "cautious": 0.30 * cautious})
        add("bribe", {"base": 0.05, "low_trust": 0.30 * low})

        return sorted(scores.values(), key=lambda x: x.score, reverse=True)

    def decide(
        self,
        npc: NPCState,
        world: WorldState,
        memories: List[MemoryRecord],
    ) -> DecisionTrace:
        s = self.score_actions(npc, world, memories)
        selected = s[0].action if s else "ignore"
        return DecisionTrace(
            npc.npc_id,
            selected,
            s,
            [m.event_id for m in memories],
            {
                "role": npc.role,
                "location": world.location,
                "game_day": str(world.game_day),
                "trust": str(npc.trust),
            },
        )
