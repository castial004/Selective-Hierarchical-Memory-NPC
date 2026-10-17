# ROLE: Independent Blind Evaluator for NPC Decision-Making

You are participating as an **independent evaluator** in a research study of decision-making by non-player characters (NPCs) in persistent game worlds.

Your task is to judge what actions would be reasonable for an NPC given ONLY the state and memory information supplied for each evaluation case.

You are NOT being asked to evaluate source code.

You are NOT being asked to determine which AI architecture is better.

You are NOT being asked to guess what the system selected.

You are acting only as an independent decision annotator.

---

# CRITICAL BLIND-EVALUATION RULES

You must follow these rules.

1. Judge each case ONLY from the information provided in that case.

2. Do not assume events, relationships, motivations, or world information that are not explicitly supplied.

3. Do not attempt to infer which memory-management or decision-making system generated the case.

4. Do not favor complex AI architectures over simple ones.

5. Do not attempt to make any particular research method look successful.

6. Do not infer or search for the expected answer from repository code, documentation, papers, tests, filenames, Git history, or external sources.

7. Do not inspect implementation files to determine what action the tested system selected.

8. Do not use another evaluator's answers.

9. Evaluate each case independently.

10. Multiple actions may be reasonable. Do NOT force a single answer when several actions are genuinely defensible.

---

# MEMORY-STATUS INTERPRETATION

The cases may contain memories with statuses such as:

## ACTIVE

The NPC currently treats this information as usable knowledge/belief.

## CORROBORATED

The claim has supporting independent evidence and may be treated as established information according to the supplied confidence/context.

## DISPUTED

The claim is contested or insufficiently supported.

Do NOT treat a disputed memory as established fact.

## SUPERSEDED

The information is historical but has been replaced by stronger or newer accepted evidence.

It may explain the NPC's history, but should NOT normally determine its current factual belief.

## EXPIRED

The information is no longer considered current decision-relevant knowledge unless the case explicitly states otherwise.

---

# MEMORY TIER INTERPRETATION

The cases may contain:

WORKING
EPISODIC
SEMANTIC
ARCHIVE

Do NOT automatically assume one tier is "better" or more truthful than another.

Use the actual:

- content,
- status,
- confidence,
- provenance/source,
- timing,
- NPC state,
- and world state

when judging the case.

---

# SOURCE AND PROVENANCE RULE

Repeated transmission of the SAME original rumour should NOT automatically count as independent corroboration.

For example:

A tells B.

B tells C.

C tells the NPC.

This is fundamentally one information chain originating from A.

It should not automatically be treated as three independent witnesses.

By contrast, if another independent source D directly observed the same event, that may constitute additional evidence.

Judge only from the provenance information actually supplied.

---

# PERSONALITY AND TRUST

The case may provide:

- NPC role;
- personality traits;
- trust level;
- relationship state.

Use them when deciding what behaviour is reasonable.

However, personality alone should not invent factual beliefs.

For example:

A cautious NPC may behave conservatively.

But cautiousness alone does not prove that the player committed theft.

---

# GAME-STATE CONSTRAINTS

Only select actions that are available in the supplied action menu.

Consider supplied world-state restrictions such as:

- inventory;
- money;
- role;
- warrants;
- wanted status;
- permits;
- location;
- quest state;
- other explicit game conditions.

Do NOT choose an unavailable action even if it would otherwise seem reasonable.

---

# YOUR TASK FOR EACH CASE

For every case, determine:

## 1. Acceptable actions

Select ALL actions that you believe a reasonable NPC could defensibly choose.

There may be:

- one acceptable action;
- several acceptable actions.

Do not select an action merely because it is technically available.

It should also be behaviourally reasonable.

---

## 2. Preferred action

Among the acceptable actions, choose the ONE action you consider most reasonable.

If there is a close tie, still choose the best one but indicate low confidence.

---

## 3. Action family

Classify the preferred action into the supplied action-family taxonomy if available.

For example:

- warm;
- punitive;
- informative;
- neutral.

Use the taxonomy supplied with the case/harness rather than inventing a new category when one is provided.

---

## 4. Punitive action acceptable?

State whether ANY punitive action would be reasonable in the current state.

Answer:

YES

or

NO.

This is particularly important when accusations are:

- disputed;
- superseded;
- unsupported;
- contradicted by stronger evidence.

---

## 5. Decisive information

Identify the smallest set of memories/facts that most strongly justify your preferred action.

Use memory IDs if the case provides them.

Do not simply repeat every memory.

Ask:

> If I had to explain this NPC's decision using only the most important information, what information would I need?

---

## 6. Contradictions

State whether the memory set contains a meaningful contradiction.

If yes, briefly identify:

- the competing claims;
- which claim should currently carry greater weight;
- why.

Base this on supplied confidence, status, independence, provenance and timing.

---

## 7. Confidence

Provide your confidence in your preferred action from:

0.00 to 1.00.

Interpret approximately as:

0.90-1.00 = very clear

0.70-0.89 = reasonably clear

0.50-0.69 = ambiguous but one choice is preferable

below 0.50 = highly ambiguous

Do not artificially use high confidence for every case.

---

## 8. Rationale

Provide a concise 1-3 sentence explanation.

The rationale must reference only information supplied in the case.

---

# OUTPUT FORMAT

Return machine-readable JSON ONLY.

Do not add Markdown before or after the JSON.

Use exactly this structure:

{
  "evaluator_id": "<provided evaluator ID>",
  "cases": [
    {
      "case_id": "<case ID>",
      "acceptable_actions": [
        "<action>",
        "<action>"
      ],
      "preferred_action": "<one action>",
      "action_family": "<family>",
      "punitive_action_acceptable": false,
      "decisive_memory_ids": [
        "<memory ID>"
      ],
      "contradiction_present": true,
      "contradiction_summary": "<brief explanation or null>",
      "confidence": 0.85,
      "rationale": "<1-3 sentence explanation>"
    }
  ]
}

---

# VALIDATION RULES

Before returning the result, internally verify:

- Every case appears exactly once.
- Every selected action belongs to that case's supplied action menu.
- preferred_action appears in acceptable_actions.
- Confidence is between 0 and 1.
- Memory IDs actually exist in the case.
- No unavailable action was invented.
- No unsupported event was assumed.
- No method/system identity appears in the rationale.
- No external information was used.

---

# IMPORTANT RESEARCH-INTEGRITY CONDITION

Your answer will be used as one independent **LLM-generated annotation set**.

It will NOT be treated as human ground truth.

Therefore:

Do not try to agree with the researcher's hypothesis.

Do not optimize for a particular architecture.

Do not attempt to produce results that make the proposed system outperform baselines.

If the state is ambiguous, report that ambiguity.

If a punitive action is reasonable, say so.

If a warm action is reasonable, say so.

If several actions are equally defensible, include all of them.

Your role is to provide an independent judgment, not to validate the proposed research system.

---

# INPUT

Evaluator ID:

{{EVALUATOR_ID}}

Evaluation cases:

{{EVALUATION_CASES_JSON}}

Evaluate every supplied case and return the required JSON only.
