# Architecture v0.2.1

The research core runs before graphics or LLM dialogue, and works with no LLM at
all. Every module below has tests.

## Pipeline

```
GameEvent
  -> Decision-Impact admission filter        memory/importance.py
  -> Tier routing (working/episodic/semantic/archive)
                                             memory/manager.py
  -> Contradiction-aware belief revision     beliefs/updater.py
  -> Retrieval (relevance, importance, recency, confidence, status)
                                             memory/manager.py
  -> State-valid action pruning              decision/valid_actions.py
  -> Utility action selection                decision/engine.py
  -> Counterfactual explanation verification explainability/counterfactual.py
  -> Action + certified explanation          explainability/dialogue.py
```

## Modules

1. **Structured game events** — `core/models.py`.
2. **Decision-impact memory score** — multi-criteria admission with calibrated
   weights.
3. **Hierarchical memory** — Working / Episodic / Semantic / Archive, with
   capacity limits, decay and archival.
4. **Explicit causal feature channel** — `core/features.py`. Memories declare the
   decision channel they evidence (`metadata["feature_key"]`) instead of relying
   on substring matches against `event_type`. This is what lets semantic beliefs
   influence decisions; the legacy keyword scan remains as a fallback.
5. **Contradiction-aware belief revision** — `conflict_key` groups competing
   claims; higher-confidence claims supersede, equal claims corroborate
   (confidence rises only on *independent* corroboration, never on hearsay
   echo), lower-confidence claims are recorded as DISPUTED.
6. **Retrieval** — excludes SUPERSEDED, EXPIRED, ARCHIVE and DISPUTED records by
   default, so contested claims cannot drive behaviour.
7. **Valid-action filtering** — role menus pruned by inventory, money, trust and
   game law (a guard needs a warrant, a wanted flag, or a permit to arrest).
8. **Utility engine** — `argmax` over valid actions; features are the strongest
   activated memory per channel, combined with personality and trust.
9. **Counterfactual verification** — leave-one-out ablation over retrieved
   memories, following derivation lineage, so ablating a source memory also
   removes the summaries derived from it.
10. **SQLite persistence** — memories and decision traces; thread-safe
    (`check_same_thread=False` + lock) for threaded servers.
11. **Rumour diffusion** — confidence attenuation with provenance chains
    (`source_chain`, `origin_event_id`), which also feed lineage-aware ablation.

## Playable front end (v0.3.0)

`game/` is a pygame layer over the same core — no research logic lives there:

```
world_map.py    tiles, BLOCKING set, collision, Camera
      │
pixel_art.py ─► assets.py ─► renderer.py ─► app.py  (Game loop, scenes)
                                   ▲
shop.py ──────► conversation.py ───┘   GameContext reads the live store
                 (dialogue graph)      and the utility engine's choice
```

`conversation.GameContext` is the only bridge: it calls
`HierarchicalMemoryManager.retrieve()`, `UtilityDecisionEngine.decide()` and
`CounterfactualExplanationVerifier.verify_memories()` to build each line and each
availability gate. A reply is never scripted speech about memory — it *is* the
memory. Dialogue and shop layers import no pygame, so the whole game graph is
unit-testable headlessly.

## Faithfulness test

The system recomputes the NPC decision after removing each retrieved memory *and
everything transitively derived from it*. If the selected action changes, or the
score moves by at least the causal threshold, that memory is certified as
material to the decision.

Two caveats stated in the code and in the paper draft:

* the intervention is "the NPC had forgotten this", not "this never happened";
* ablation covers retrieved memories only — trust, personality and world flags
  are not ablated.
