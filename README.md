# Selective Hierarchical Memory for Faithful Explainable NPC Decision-Making

Version 0.1 — runnable research-core prototype.

## Included
- Structured game events
- Decision-impact memory admission
- Working / Episodic / Semantic / Archive memory tiers
- SQLite persistence
- Contradiction-aware belief revision
- Valid-action filtering
- Utility-based decision making
- Decision traces
- Counterfactual explanation verification
- Shopkeeper false-accusation demo
- Automated tests

The core works **without an LLM**. An LLM can later be added only for natural dialogue.

## Quick start
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m npc_memory_project.demo.shopkeeper_demo
pytest
```

## Research flow
```text
PLAYER / WORLD EVENT
        ↓
Decision-Impact Memory Filter
        ↓
Hierarchical Memory Manager
        ↓
Contradiction-Aware Belief Updater
        ↓
Relevant Memory Retrieval
        ↓
State-Valid Action Filter
        ↓
Utility Decision Engine
        ↓
Counterfactual Explanation Verifier
        ↓
NPC ACTION + TRACEABLE EXPLANATION
```
