# Architecture v0.1

This repository implements the research core before graphics or LLM dialogue.

## Modules
1. Structured game events
2. Decision-impact memory score
3. Working / episodic / semantic / archive memory
4. Contradiction-aware belief revision
5. Valid-action filtering
6. Utility-based action selection
7. Counterfactual explanation verification
8. SQLite persistence

## Faithfulness test
The system recomputes the NPC decision after removing each retrieved memory. If removing a memory changes the selected action, that memory is treated as strong evidence that it materially influenced the original decision.
