from typing import List, Dict, Tuple
from npc_memory_project.core.models import (
    NPCState,
    WorldState,
    MemoryRecord,
    ActionScore,
    DecisionTrace,
)
from npc_memory_project.core.features import FEATURE_KEYS, features_of
from npc_memory_project.decision.valid_actions import valid_actions

class UtilityDecisionEngine:
    """
    State-valid, multi-factor utility scoring engine.
    Calculates expected utility over pruned candidate actions based on
    personality traits, player trust, and active memory feature vectors.
    """

    def _features(self, memories: List[MemoryRecord]) -> Tuple[float, float, float, float, float]:
        """Aggregate activated memories into the causal feature vector.

        Resolution is delegated to :func:`npc_memory_project.core.features.features_of`,
        which prefers an explicit ``metadata["feature_key"]`` and falls back to
        the legacy ``event_type`` keyword scan. Each feature takes the strongest
        activated memory on that channel::

            f_k = max over m in M_ret where k in features_of(m) of  I(m) * C(m)

        Because SEMANTIC beliefs only became addressable once they carried an
        explicit feature key, this is also what finally gives the Semantic tier
        influence over decisions instead of it being a retrieval-only passenger.
        """
        strongest: Dict[str, float] = {key: 0.0 for key in FEATURE_KEYS}
        for m in memories:
            activated = m.importance * m.confidence
            for key in features_of(m):
                if activated > strongest[key]:
                    strongest[key] = activated
        return tuple(strongest[key] for key in FEATURE_KEYS)  # type: ignore[return-value]

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

        # Shopkeeper actions (IEEE paper calibrated weights; cautiousness gated, see below)
        add("trade", {"base": 0.25, "high_trust": 0.45 * high, "innocence_memory": 0.20 * innocence})
        add("offer_discount", {"base": 0.10, "high_trust": 0.40 * high, "help_memory": 0.30 * helpv})
        threat = 1.0 if (theft > 0.0 or rumour > 0.0) else 0.0
        add("refuse_trade", {"base": 0.05, "theft_memory": 0.45 * theft, "low_trust": 0.35 * low, "cautious": 0.15 * cautious * threat})
        # v0.3.0 fix: cautiousness is an impulse *towards a perceived threat*, so
        # it is gated on one being present. Ungated it added a flat +0.14 to the
        # punitive actions of any cautious NPC, so `warn_player`/`refuse_trade`
        # outranked `talk` even with nothing on file -- an empty shop and an
        # unblemished customer still produced a warning (caught by the
        # author-labelled cases no-stock-removes-trade / no-money-removes-trade).
        #
        # The gate is on *presence*, not magnitude: any retrievable accusation or
        # rumour (theft/rumour > 0) restores the original paper weights exactly,
        # so scenarios that were already correct are bit-for-bit unchanged.
        # A graded gate was tried first and was too weak -- it halved the push in
        # the accusation+noise scenario and dropped invariant I2 from 63/63 to
        # 62/63, which is why presence is the right variable.
        add("warn_player", {"base": 0.10, "theft_memory": 0.25 * theft, "low_trust": 0.20 * low, "cautious": 0.20 * cautious * threat})
        add("call_guard", {"base": 0.05, "theft_memory": 0.35 * theft, "low_trust": 0.20 * low, "cautious": 0.20 * cautious * threat})
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
