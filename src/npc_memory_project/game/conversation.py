"""Conversation trees for the playable town.

The point of this layer is that NPC replies are not scripted flavour text: they
are generated from what that NPC actually remembers and from the decision the
utility engine actually made. Ask Mira why she is cold to you and she cites the
factor the counterfactual verifier certified; open her memory panel and you can
see the same record with its tier, status and confidence.

Pure logic -- no pygame -- so the whole dialogue graph is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import BeliefStatus, MemoryRecord, MemoryTier
from npc_memory_project.game.shop import ITEMS_BY_ID, Wallet
from npc_memory_project.simulation.town_simulation import TownSimulation

# --------------------------------------------------------------------- context


@dataclass
class GameContext:
    """Everything a dialogue node is allowed to look at."""

    sim: TownSimulation
    wallet: Wallet
    flags: Dict[str, object] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)

    # -- memory access ------------------------------------------------------
    def retrieved(self, npc_id: str) -> List[MemoryRecord]:
        """The memories this NPC would actually bring to mind right now."""
        held = self.sim.store.list_for_npc(npc_id)
        return self.sim.manager.retrieve(
            held, npc_id=npc_id, current_day=self.sim.world.game_day, top_k=5
        )

    def all_memories(self, npc_id: str) -> List[MemoryRecord]:
        return self.sim.store.list_for_npc(npc_id)

    def belief(self, npc_id: str, claim: str) -> Optional[MemoryRecord]:
        """The NPC's live belief asserting ``claim``, if it holds one."""
        for m in self.all_memories(npc_id):
            if m.metadata.get("claim") == claim and m.status in {
                BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED
            }:
                return m
        return None

    def holds_conflict(self, npc_id: str, key: str = "medicine_theft") -> List[MemoryRecord]:
        return [m for m in self.all_memories(npc_id) if m.metadata.get("conflict_key") == key]

    # -- decision access ----------------------------------------------------
    def top_action(self, npc_id: str) -> str:
        npc = self.sim.npcs[npc_id]
        trace = self.sim.engine.decide(npc, self.sim.world, self.retrieved(npc_id))
        return trace.selected_action

    def certified_reasons(self, npc_id: str) -> List[str]:
        """Factors the counterfactual verifier certified as changing the choice."""
        npc = self.sim.npcs[npc_id]
        memories = self.retrieved(npc_id)
        if not memories:
            return []
        evidence = self.sim.verifier.verify_memories(npc, self.sim.world, memories)
        return [e.factor_name for e in evidence if e.changed_action or abs(e.score_delta) >= 0.12]

    def trade_allowed(self, npc_id: str) -> bool:
        """Whether this vendor will actually serve the player right now.

        Deliberately not "is trade the top-scoring action": an NPC who has
        decided to apologise or chat is willing to serve, and only an actively
        hostile decision (refuse/warn/call the guard) closes the counter. Stock
        and the valid-action layer still have to agree.
        """
        from npc_memory_project.decision.valid_actions import valid_actions

        npc = self.sim.npcs[npc_id]
        allowed = valid_actions(npc, self.sim.world)
        has_goods = any(count > 0 for count in npc.inventory.values())
        # Only an outright refusal closes a counter. A vendor choosing
        # "warn_player" is being curt with you, not shutting up shop.
        willing = self.top_action(npc_id) not in {
            "refuse_trade", "call_guard", "arrest_player",
        }
        return ("trade" in allowed or "offer_discount" in allowed) and has_goods and willing

    def recall(self, npc_id: str, topic: str = "") -> str:
        """Public form of the in-character recall line, for the shop and UI."""
        return recall_line(self, npc_id, topic)

    def tell(self, text: str) -> None:
        self.log.append(f"Day {self.sim.world.game_day}: {text}")
        if len(self.log) > 60:
            self.log.pop(0)


# ---------------------------------------------------------------------- nodes


@dataclass
class Choice:
    """One selectable line in the dialogue box."""

    label: str
    kind: str = "goto"                 # goto | shop | effect | close
    target: str = ""                   # node id (goto) or effect key
    enabled: Callable[[GameContext], bool] = lambda ctx: True
    reason: Callable[[GameContext], str] = lambda ctx: ""


@dataclass
class Node:
    speaker: str
    lines: Callable[[GameContext], List[str]]
    choices: Callable[[GameContext], List[Choice]]


def _always(ctx: GameContext) -> bool:
    return True


def _no_reason(ctx: GameContext) -> str:
    return ""


def _has_receipt(ctx: GameContext) -> bool:
    return ctx.wallet.has("receipt")


def _needs_receipt_reason(ctx: GameContext) -> str:
    return "You have no proof to show yet."


def _evidence_given(ctx: GameContext) -> bool:
    return bool(ctx.flags.get("evidence_presented"))


def _evidence_reason(ctx: GameContext) -> str:
    return "You have already shown the guard your proof."


# ------------------------------------------------------------------- phrases


def _confidence_phrase(confidence: float) -> str:
    if confidence >= 0.9:
        return "I am certain"
    if confidence >= 0.7:
        return "I am fairly sure"
    if confidence >= 0.5:
        return "I believe"
    return "I only heard it said"


def recall_line(ctx: GameContext, npc_id: str, topic: str = "") -> str:
    """The strongest thing this NPC remembers, hedged by its own confidence."""
    memories = ctx.retrieved(npc_id)
    if topic:
        matches = [m for m in memories if topic in m.event_type or topic in m.summary.lower()]
        memories = matches or memories
    if not memories:
        return "I have nothing to tell you about that."
    top = memories[0]
    return (
        f"{_confidence_phrase(top.confidence)} — {top.summary} "
        f"(day {top.game_day}, {top.confidence:.0%} sure)"
    )


def why_am_i_treated_this_way(ctx: GameContext, npc_id: str) -> str:
    """Surface the counterfactually certified cause as spoken dialogue.

    This is the research claim made playable: the NPC names the memory that
    actually swung the decision, not a plausible-sounding excuse.
    """
    reasons = ctx.certified_reasons(npc_id)
    if reasons:
        joined = " and ".join(reasons[:2])
        return f"Because it weighed on me: {joined}."

    action = ctx.top_action(npc_id)
    if action in {"trade", "offer_discount"}:
        return "Nothing against you — I simply weigh coin as carefully as I weigh words."
    if action in {"refuse_trade", "warn_player", "call_guard"}:
        return "I have my reasons, though I admit none of them are your doing."
    return "I decide as the day demands, not out of any grudge."


def _count(ctx: GameContext, npc_id: str, claim: str) -> int:
    return sum(1 for m in ctx.all_memories(npc_id) if m.metadata.get("claim") == claim)


# ---------------------------------------------------------------- NODES table
NODES: Dict[str, Node] = {}


def node(node_id: str):
    """Register a node factory. The factory is called once, at import time."""

    def wrap(fn):
        NODES[node_id] = fn()
        return fn
    return wrap


# ------------------------------------------------------------------ Mira ----
@node("mira.greet")
def _mira_greet() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        action = ctx.top_action("mira")
        reason = why_am_i_treated_this_way(ctx, "mira")
        if action == "apologise":
            return [
                "Mira sets down her pestle and folds both hands on the counter.",
                f"I owe you an apology, and I will not dress it up. {reason}",
                "My counter is open to you — and I'll hear no argument about the price of medicine.",
            ]
        if action in {"refuse_trade", "warn_player", "call_guard"}:
            return [
                "Mira does not look up from the mortar. Her voice is level and very cold.",
                f"State your business and keep your hands where I can see them. {reason}",
            ]
        return [
            "Mira looks up and offers a thin, professional smile.",
            f"Welcome to the apothecary. {reason}",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("What do you have for sale?", "shop", "mira",
                   enabled=lambda c: c.trade_allowed("mira"),
                   reason=lambda c: "She will not sell to you while she believes you a thief."),
            Choice("Ask about the missing medicine.", "goto", "mira.ask_theft"),
            Choice("Ask about Rohan.", "goto", "mira.ask_rohan",
                   enabled=lambda c: c.belief("mira", "rohan_stole") is not None,
                   reason=lambda c: "She does not yet know who really took it."),
            Choice("Why are you treating me like this?", "goto", "mira.why"),
            Choice("Show her the pharmacy receipts.", "effect", "present_evidence:mira",
                   enabled=lambda c: c.wallet.has("receipt") and not c.flags.get("mira_saw_receipt"),
                   reason=lambda c: ("You have no receipts to show."
                                     if not c.wallet.has("receipt")
                                     else "You have already shown her.")),
            Choice("Apologise for the trouble.", "effect", "mira.apologise",
                   enabled=lambda c: ctx.top_action("mira") != "apologise",
                   reason=lambda c: "She has already forgiven you."),
            Choice("Leave her to her work.", "close"),
        ]

    return Node("mira", lines, choices)


@node("mira.ask_theft")
def _mira_theft() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        out = ["Mira's jaw tightens."]
        out.append(recall_line(ctx, "mira", "theft"))
        if ctx.belief("mira", "player_falsely_accused"):
            out.append("And I have since learned how badly I misjudged you. The ledger is corrected.")
        elif _count(ctx, "mira", "player_stole"):
            out.append("A tincture jar, gone from that shelf. Twenty-four gold of it, and no coin in the till.")
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Who told you it was me?", "goto", "mira.who_told"),
            Choice("Ask something else.", "goto", "mira.greet"),
            Choice("Leave her to her work.", "close"),
        ]

    return Node("mira", lines, choices)


@node("mira.who_told")
def _mira_who_told() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        claims = ctx.holds_conflict("mira")
        if not claims:
            return ["I would rather not repeat it."]
        sources = []
        for m in claims:
            tag = m.source or "someone"
            status = m.status.value
            sources.append(f"{tag} ({status}, {m.confidence:.0%})")
        return [
            "She counts them off on her fingers, the way she counts doses.",
            "Everything I hold about that morning: " + "; ".join(sources) + ".",
            "I keep the contradictory ones too. An apothecary who forgets a mistake "
            "repeats it.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Thank her for the honesty.", "goto", "mira.greet"),
            Choice("Leave her to her work.", "close"),
        ]

    return Node("mira", lines, choices)


@node("mira.ask_rohan")
def _mira_rohan() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        belief = ctx.belief("mira", "rohan_stole")
        out = ["Mira lowers her voice, though the shop is empty."]
        out.append(recall_line(ctx, "mira", "innocence"))
        if belief:
            out.append(
                f"That is what I hold now — day {belief.game_day}, {belief.confidence:.0%} "
                "certain, and the accusation against you struck out of the ledger."
            )
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask something else.", "goto", "mira.greet"),
            Choice("Leave her to her work.", "close"),
        ]

    return Node("mira", lines, choices)


@node("mira.why")
def _mira_why() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        lines_out = ["She sets the mortar down. This, at least, she will answer directly."]
        lines_out.append(why_am_i_treated_this_way(ctx, "mira"))
        reasons = ctx.certified_reasons("mira")
        if reasons:
            lines_out.append(
                "Strike that memory from me and I would serve you without a second "
                "thought. I have run the ledger both ways."
            )
        return lines_out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask something else.", "goto", "mira.greet"),
            Choice("Leave her to her work.", "close"),
        ]

    return Node("mira", lines, choices)


# ------------------------------------------------------------------ Kael ----
@node("kael.greet")
def _kael_greet() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        action = ctx.top_action("kael")
        out = ["Officer Kael squares his shoulders, hand resting on the pommel at his belt."]
        if action == "report_findings":
            out.append(
                "The apothecary matter is recorded and closed — the guard's word is "
                "good in this town, and it is good for you."
            )
        elif action == "question_player":
            out.append(f"Hold a moment, citizen. You are named in an open complaint. "
                       f"{why_am_i_treated_this_way(ctx, 'kael')}")
        else:
            out.append("State your business. Briefly.")
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask what he knows about the theft.", "goto", "kael.investigation"),
            Choice("Show him the pharmacy receipts.", "effect", "present_evidence:kael",
                   enabled=lambda c: c.wallet.has("receipt") and not c.flags.get("kael_saw_receipt"),
                   reason=lambda c: ("You carry no proof yet."
                                     if not c.wallet.has("receipt")
                                     else "You have already given him the receipts.")),
            Choice("Ask where a traveller finds proof.", "goto", "kael.how_to_prove"),
            Choice("Ask what he remembers.", "goto", "kael.memory"),
            Choice("Leave the guard to his patrol.", "close"),
        ]

    return Node("kael", lines, choices)


@node("kael.investigation")
def _kael_investigation() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        out = ["He unhooks a small wax tablet and reads from it without expression."]
        out.append(recall_line(ctx, "kael"))
        if ctx.belief("kael", "rohan_stole"):
            out.append("And I have since put it on record: Rohan took the medicine. Not you.")
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask where a traveller finds proof.", "goto", "kael.how_to_prove"),
            Choice("Ask what he remembers.", "goto", "kael.memory"),
            Choice("Ask something else.", "goto", "kael.greet"),
            Choice("Leave the guard to his patrol.", "close"),
        ]

    return Node("kael", lines, choices)


@node("kael.how_to_prove")
def _kael_how_to_prove() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        if ctx.wallet.has("receipt"):
            return [
                "You already carry what I would have sent you for.",
                "Stamped receipts, dated before the theft. Present them, or present "
                "Rohan — a confession is cleaner.",
            ]
        return [
            "He taps the tablet with one finger.",
            "A stamp carries more weight than a story. Every apothecary sale is "
            "entered twice — the seller keeps the roll, the market keeps the copy.",
            "The stall-keeper Arun holds the market copies. Ask him politely. He does "
            "not respond to the other kind of asking.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Note that, and go.", "effect", "ask_arun_hint"),
            Choice("Ask something else.", "goto", "kael.greet"),
            Choice("Leave the guard to his patrol.", "close"),
        ]

    return Node("kael", lines, choices)


@node("kael.memory")
def _kael_memory() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        held = ctx.retrieved("kael")
        if not held:
            return ["He shrugs. 'Nothing about you worth writing down.'"]
        rows = [f"  · {m.summary} [{m.tier.value}/{m.status.value}, {m.importance:.2f}]"
                for m in held]
        return ["He reads out his tablet, entry by entry."] + rows

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask something else.", "goto", "kael.greet"),
            Choice("Leave the guard to his patrol.", "close"),
        ]

    return Node("kael", lines, choices)


# ------------------------------------------------------------------ Arun ----
@node("arun.greet")
def _arun_greet() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        action = ctx.top_action("arun")
        out = ["Arun leans over his barrels with the grin of a man who sells news by the pound."]
        if action == "spread_rumour":
            out.append("Psst — everything worth hearing passes this stall first. Everything.")
        elif action == "warn_player":
            out.append(
                "He keeps both hands flat on the counter and watches you the way a man "
                "watches a stranger near his till."
            )
            out.append(
                "I'll sell you apples. Doesn't mean I've forgotten whose name I put "
                "about this square."
            )
        else:
            out.append("Apples, bread, and word on the breeze. What'll it be?")
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Buy something from the stall.", "shop", "arun",
                   enabled=lambda c: c.trade_allowed("arun"),
                   reason=lambda c: "He has nothing to sell you, or will not."),
            Choice("What are the stalls saying about me?", "goto", "arun.gossip"),
            Choice("Ask to see the market ledgers.", "goto", "arun.ledgers",
                   enabled=lambda c: bool(c.flags.get("arun_hint")) and not c.wallet.has("receipt"),
                   reason=lambda c: ("You need a reason to ask — a guard's word carries."
                                     if not c.flags.get("arun_hint")
                                     else "He has already given you the copies.")),
            Choice("Ask why he spread the rumour.", "goto", "arun.why"),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


@node("arun.gossip")
def _arun_gossip() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        out = ["He wipes his hands on his apron and lowers his voice, delighted to be asked."]
        out.append(recall_line(ctx, "arun"))
        held = ctx.holds_conflict("arun")
        if held:
            out.append(
                f"That's the whole of it — {len(held)} telling(s) in the matter, and I'd "
                "repeat every one of them for the price of an apple."
            )
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        if ctx.belief("arun", "rohan_stole"):
            return [
                Choice("Ask about Rohan's confession.", "goto", "arun.confession"),
                Choice("Ask something else.", "goto", "arun.greet"),
                Choice("Leave the stall.", "close"),
            ]
        return [
            Choice("Ask why he spread the rumour.", "goto", "arun.why"),
            Choice("Ask something else.", "goto", "arun.greet"),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


@node("arun.confession")
def _arun_confession() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "Arun's grin falters, and for a moment he looks like a man doing sums.",
            recall_line(ctx, "arun", "confess"),
            "I only repeat what the wind carries. But that wind, I'll grant you, "
            "was blowing the right way for once.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask something else.", "goto", "arun.greet"),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


@node("arun.ledgers")
def _arun_ledgers() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "He taps a battered box under the counter and looks at you sideways.",
            "The market copies? I keep 'em. Doesn't mean I hand 'em out for free — "
            "paper costs, and so does my silence.",
            "Five gold, and the apothecary roll goes with you, stamped and dated.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Pay him five gold.", "effect", "arun.buy_ledgers",
                   enabled=lambda c: c.wallet.gold >= 5,
                   reason=lambda c: "You cannot afford five gold."),
            Choice("Try to talk him down.", "goto", "arun.haggle"),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


@node("arun.haggle")
def _arun_haggle() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "He laughs, genuinely pleased.",
            "Hah! I like you better for trying. Four gold, and that is me being "
            "sentimental, which is bad for business.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Pay him four gold.", "effect", "arun.buy_ledgers_haggled",
                   enabled=lambda c: c.wallet.gold >= 4,
                   reason=lambda c: "You cannot afford four gold."),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


@node("arun.why")
def _arun_why() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "He has the decency to look uncomfortable, which is rarer than you would think.",
            "Mira's medicine went missing and you'd been at her counter that morning. "
            "That is all I said. I said it loudly, I'll allow.",
            why_am_i_treated_this_way(ctx, "arun"),
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Ask to see the market ledgers.", "goto", "arun.ledgers",
                   enabled=lambda c: bool(c.flags.get("arun_hint")) and not c.wallet.has("receipt"),
                   reason=lambda c: "You need a reason to ask first — a guard's word carries."),
            Choice("Ask something else.", "goto", "arun.greet"),
            Choice("Leave the stall.", "close"),
        ]

    return Node("arun", lines, choices)


# ----------------------------------------------------------------- Rohan ----
@node("rohan.greet")
def _rohan_greet() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        action = ctx.top_action("rohan")
        out = ["Rohan is pressed into the corner of the alley as if the wall might take his side."]
        if action in {"deny", "flee"}:
            out.append("I had nothing to do with it. Nothing. You've no proof and neither has anyone else.")
        elif action == "confess":
            out.append("You've heard it by now, I expect. It was me. I won't say it twice.")
        return out

    def choices(ctx: GameContext) -> List[Choice]:
        confessed = ctx.belief("rohan", "rohan_stole") is not None or bool(ctx.flags.get("confessed"))
        return [
            Choice("Ask why he is hiding in the alley.", "goto", "rohan.alley"),
            Choice("Confront him about the medicine.", "effect", "confront_rohan",
                   enabled=lambda c: not c.flags.get("confessed"),
                   reason=lambda c: "He has already confessed."),
            Choice("Ask why he did it.", "goto", "rohan.motive",
                   enabled=lambda c: confessed,
                   reason=lambda c: "He has not admitted anything yet."),
            Choice("Leave him be.", "close"),
        ]

    return Node("rohan", lines, choices)


@node("rohan.alley")
def _rohan_alley() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "He flinches at the sound of boots somewhere in the square, though there are none.",
            "It's quiet here. That's all. A man's allowed to want quiet.",
            recall_line(ctx, "rohan") if ctx.retrieved("rohan") else "I don't know anything about any medicine.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Confront him about the medicine.", "effect", "confront_rohan",
                   enabled=lambda c: not c.flags.get("confessed"),
                   reason=lambda c: "He has already confessed."),
            Choice("Ask something else.", "goto", "rohan.greet"),
            Choice("Leave him be.", "close"),
        ]

    return Node("rohan", lines, choices)


@node("rohan.motive")
def _rohan_motive() -> Node:
    def lines(ctx: GameContext) -> List[str]:
        return [
            "He slides down the wall until he is sitting on the cobbles.",
            "My sister took the coughing sickness in the winter. The tincture is "
            "twenty-four gold and I have never in my life held twenty-four gold.",
            "I am not asking you to forgive it. I am telling you why the jar's empty.",
        ]

    def choices(ctx: GameContext) -> List[Choice]:
        return [
            Choice("Tell him the guard will hear it kindly.", "goto", "rohan.greet"),
            Choice("Leave him be.", "close"),
        ]

    return Node("rohan", lines, choices)


ENTRY_NODES: Dict[str, str] = {
    "mira": "mira.greet",
    "kael": "kael.greet",
    "arun": "arun.greet",
    "rohan": "rohan.greet",
}


def entry_node(npc_id: str) -> str:
    return ENTRY_NODES.get(npc_id, "mira.greet")


def get_node(node_id: str) -> Node:
    return NODES[node_id]


def available_choices(ctx: GameContext, node_id: str) -> List[Choice]:
    return get_node(node_id).choices(ctx)


# ------------------------------------------------------------------- effects
EFFECT_GOLD_COSTS = {"arun.buy_ledgers": 5, "arun.buy_ledgers_haggled": 4}


def apply_effect(ctx: GameContext, effect: str) -> str:
    """Run a choice's side effect. Returns a one-line result for the UI."""
    sim = ctx.sim

    if effect.startswith("present_evidence:"):
        target = effect.split(":", 1)[1]
        sim.present_evidence(target)
        ctx.flags[f"{target}_saw_receipt"] = True
        ctx.flags["evidence_presented"] = True
        # the guard's confirmation propagates to Mira through her own beliefs
        ctx.flags["confessed"] = ctx.flags.get("confessed", False) or (
            ctx.belief("mira", "rohan_stole") is not None
        )
        ctx.tell(f"Presented the receipts to {target.capitalize()}.")
        if target == "kael":
            return ("Kael reads the receipts twice, then stamps the tablet. The "
                    "apothecary will hear it from the guard herself.")
        return ("Mira turns the receipts over, checks the date against her own roll, "
                "and goes very still.")

    if effect == "confront_rohan":
        sim.persuade_rohan()
        ctx.flags["confessed"] = True
        ctx.tell("Rohan confessed to Officer Kael.")
        return "Rohan's shoulders come down all at once. He does not argue."

    if effect == "ask_arun_hint":
        ctx.flags["arun_hint"] = True
        ctx.tell("Kael mentioned the market keeps copies of apothecary sales.")
        return "You make a note: the market stall keeps the apothecary's copies."

    if effect in EFFECT_GOLD_COSTS:
        cost = EFFECT_GOLD_COSTS[effect]
        if ctx.wallet.gold < cost:
            return "You cannot afford that."
        ctx.wallet.gold -= cost
        ctx.wallet.add("receipt")
        ctx.flags["arun_hint"] = False
        ctx.tell(f"Bought the market ledgers from Arun for {cost} gold.")
        return (f"Arun pockets the coin and slides a stamped roll across the counter. "
                f"'{ITEMS_BY_ID['receipt'].name}. Dated, sealed, and worth more than you paid.'")

    if effect == "mira.apologise":
        sim.npcs["mira"].trust = min(40.0, sim.npcs["mira"].trust + 8.0)
        ctx.tell("You apologised to Mira.")
        return "She inclines her head, the way she does over a well-measured dose."

    return "Nothing happens."


# ------------------------------------------------------------------ journal
def memory_rows(ctx: GameContext, npc_id: str) -> List[Dict[str, str]]:
    """Rows for the in-game memory panel (tier / status / importance)."""
    rows: List[Dict[str, str]] = []
    for m in ctx.all_memories(npc_id):
        rows.append({
            "summary": m.summary,
            "tier": m.tier.value,
            "status": m.status.value,
            "importance": f"{m.importance:.2f}",
            "confidence": f"{m.confidence:.0%}",
            "day": str(m.game_day),
            "source": m.source,
        })
    return rows


def quest_hint(ctx: GameContext) -> str:
    """A single line telling the player what is plausibly worth doing next."""
    if ctx.flags.get("confessed") or ctx.belief("mira", "rohan_stole"):
        return "Mira knows the truth now — speak with her."
    if ctx.wallet.has("receipt"):
        return "You carry the receipts. Show them to Officer Kael, or to Mira herself."
    if ctx.flags.get("arun_hint"):
        return "Arun keeps the market's copies of the apothecary roll. Ask him for them."
    return "Ask Officer Kael how a traveller proves their innocence."
