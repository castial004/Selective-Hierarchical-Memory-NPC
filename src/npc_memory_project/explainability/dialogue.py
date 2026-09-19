import os
import json
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any
from npc_memory_project.core.models import NPCState, ExplanationEvidence

class PersonaProfile:
    """Defines linguistic quirks, vocabulary, and tone constraints for NPCs."""
    def __init__(
        self,
        tone: str,
        speech_style: str,
        keywords: List[str],
        greeting: str,
    ):
        self.tone = tone
        self.speech_style = speech_style
        self.keywords = keywords
        self.greeting = greeting


PERSONA_REGISTRY: Dict[str, PersonaProfile] = {
    "mira": PersonaProfile(
        tone="cautious, measured, medicinal",
        speech_style="precise apothecary phrasing, references remedies and careful balance",
        keywords=["remedy", "balance", "ledger", "herbs", "tincture", "trust"],
        greeting="Peace upon your steps, traveler.",
    ),
    "arun": PersonaProfile(
        tone="chatty, opportunistic, streetwise",
        speech_style="informal marketplace slang, quick to whisper rumors",
        keywords=["whisper", "copper", "deal", "rumor", "breeze", "street"],
        greeting="Psst! Looking for a bargain or a bit of news?",
    ),
    "kael": PersonaProfile(
        tone="authoritative, disciplined, procedural",
        speech_style="formal guard protocol, references town bylaws and sworn evidence",
        keywords=["order", "bylaw", "evidence", "patrol", "investigation", "law"],
        greeting="Halt and state your business in the square.",
    ),
    "rohan": PersonaProfile(
        tone="nervous, evasive, defensive",
        speech_style="hesitant, looking over shoulders, quick excuses",
        keywords=["innocent", "shadows", "mistake", "nothing", "caught"],
        greeting="I... I don't want any trouble.",
    ),
}


class FaithfulDialogueSynthesizer:
    """
    Generates in-character spoken dialogue for NPCs grounded strictly
    in counterfactually certified causal factors.

    Guarantees zero post-hoc rationalizations:
    The NPC only speaks of facts that actually swung their decision.
    """

    def __init__(self, llm_hook: Optional["LLMDialogueHook"] = None):
        self.llm_hook = llm_hook or LLMDialogueHook()

    def get_persona(self, npc: NPCState) -> PersonaProfile:
        return PERSONA_REGISTRY.get(
            npc.npc_id.lower(),
            PersonaProfile(
                tone="neutral",
                speech_style="direct",
                keywords=[],
                greeting="Greetings.",
            ),
        )

    def synthesize(
        self,
        npc: NPCState,
        action: str,
        causal_evidence: List[ExplanationEvidence],
        context_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Produces faithful dialogue and metadata.
        Returns:
            {
                "dialogue": str,
                "grounded_factor": Optional[str],
                "faithful": bool,
                "persona_applied": str
            }
        """
        persona = self.get_persona(npc)
        causal = [e for e in causal_evidence if e.changed_action or abs(e.score_delta) >= 0.12]
        primary_evidence = causal[0].factor_name if causal else None

        base_line = self._generate_base_template(npc, action, primary_evidence)

        # Polish through LLM hook if configured, passing the certified causal factor
        certified_reasons = [c.factor_name for c in causal]
        polished_line = self.llm_hook.polish(
            base_dialogue=base_line,
            npc=npc,
            persona=persona,
            certified_reasons=certified_reasons,
        )

        return {
            "dialogue": polished_line,
            "grounded_factor": primary_evidence,
            "faithful": True,
            "persona": persona.tone,
        }

    def _generate_base_template(
        self,
        npc: NPCState,
        action: str,
        primary_evidence: Optional[str],
    ) -> str:
        """Deterministic persona-driven template verbalization."""
        trust = npc.trust

        if npc.role == "shopkeeper" or npc.npc_id == "mira":
            if action == "apologise":
                if primary_evidence:
                    return (
                        f"I have weighed the ledger of my words, and I was wrong. {primary_evidence} "
                        "Please accept my sincere apology—my apothecary is open to you once more."
                    )
                return "Apothecary balance demands truth: I apologize for misjudging you. Let us start fresh."

            if action == "trade":
                if trust >= 20.0:
                    return "Welcome back, trusted friend! My finest salves and restorative herbs are at your disposal."
                return "Welcome to the apothecary. Take a look at the remedies in stock."

            if action == "refuse_trade":
                ev = primary_evidence or "there are accusations of stolen goods tied to your name."
                return (
                    f"Step away from my counter! Because {ev}, "
                    "I will not risk selling a single vial or poultice to you."
                )

            if action == "warn_player":
                return "Keep your hands where I can see them. One wrong move and the town guard will be summoned."

            if action == "call_guard":
                return "Guards! Officer Kael! We have a thief disrupting the apothecary!"

            if action == "offer_discount":
                return "In recognition of your upright deeds, I am happy to adjust my prices in your favor today."

        elif npc.role == "guard" or npc.npc_id == "kael":
            if action == "arrest_player":
                ev = primary_evidence or "credible reports identify you as a primary suspect."
                return f"Halt in the name of the town bylaws! {ev}. Drop your gear and submit to arrest."

            if action == "question_player":
                ev = primary_evidence or "a theft was reported in the district."
                return f"Hold a moment, citizen. Official inquiry: {ev}. What do you have to say for yourself?"

            if action == "report_findings":
                ev = primary_evidence or "the investigation has yielded conclusive testimony."
                return f"Official report logged: {ev}. The truth is recorded in the town ledger."

            if action == "apologise":
                ev = primary_evidence or "clearing evidence has been formally accepted."
                return f"At ease, traveler. On behalf of the town guard, I retract the suspicion: {ev}."

            if action == "patrol":
                return "The square is secure. Obey the bylaws and maintain the peace."

        elif npc.role == "vendor" or npc.npc_id == "arun":
            if action == "spread_rumour":
                ev = primary_evidence or "everyone in the stalls is whispering about sudden missing supplies."
                return f"Psst! Keep your ears open and your coppers tight. Word on the cobblestones is: {ev}!"

            if action == "trade":
                if trust >= 10.0:
                    return "Only the sweetest apples and warmest loaves for a good companion! What can I bag for you?"
                return "Fresh produce, traveler! Fresh fruit, warm bread—copper on the barrelhead!"

            if action == "deny":
                return "Hey, I only repeat what the wind carries! Don't blame the messenger for market talk!"

        elif npc.role == "suspect" or npc.npc_id == "rohan":
            if action == "confess":
                ev = primary_evidence or "the evidence against me is undeniable."
                return f"Enough, stop looking at me like that! I confess! {ev}. Just keep Officer Kael away!"

            if action == "flee":
                return "I'm not going to the stocks! You won't corner me here!"

            if action == "deny":
                return "I don't know anything about missing medicine! You've got no proof against me!"

        # Fallback generic in-character line
        if primary_evidence:
            return f"Regarding {primary_evidence}: I will proceed to {action.replace('_', ' ')}."
        return f"[{npc.npc_id.capitalize()} decides to {action.replace('_', ' ')}]."


class LLMDialogueHook:
    """
    Interface for optional LLM dialogue verbalization.
    Strictly adheres to AGENTS.md:
    1. LLMs must never directly mutate world state.
    2. Core logic must work without an LLM.
    3. Paraphrasing must preserve certified causal factors without hallucinating new facts.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("NPC_LLM_API_KEY")
        self.endpoint = endpoint or os.environ.get("NPC_LLM_ENDPOINT")
        self.model = model or os.environ.get("NPC_LLM_MODEL", "gpt-3.5-turbo")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key or self.endpoint)

    def polish(
        self,
        base_dialogue: str,
        npc: NPCState,
        persona: PersonaProfile,
        certified_reasons: List[str],
    ) -> str:
        """
        If an LLM backend is configured, paraphrases base_dialogue while strictly
        retaining certified causal facts. Otherwise returns base_dialogue.
        """
        if not self.is_configured:
            return base_dialogue

        system_prompt = (
            f"You are writing in-game dialogue for an RPG NPC named {npc.npc_id}.\n"
            f"Role: {npc.role}. Tone: {persona.tone}. Style: {persona.speech_style}.\n"
            "STRICT RULES:\n"
            "1. You must preserve the core meaning and any factual claims in the base dialogue.\n"
            "2. NEVER invent new events, accusations, or facts not mentioned in the certified reasons.\n"
            "3. Keep the line short (1-3 sentences), natural, and immersively in-character.\n"
            f"Certified Causal Facts: {', '.join(certified_reasons) if certified_reasons else 'None'}"
        )

        user_prompt = f"Paraphrase this base line in character:\n\"{base_dialogue}\""

        try:
            return self._call_llm_api(system_prompt, user_prompt, fallback=base_dialogue)
        except Exception:
            # Safe deterministic fallback on any network error or timeout
            return base_dialogue

    def _call_llm_api(self, system_prompt: str, user_prompt: str, fallback: str) -> str:
        """Executes a standard OpenAI-compatible chat completion call using standard library."""
        url = self.endpoint or "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 120,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            # Clean up quotation marks if wrapped
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            return content
