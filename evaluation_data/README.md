# evaluation_data/ -- annotation datasets

This folder holds annotation datasets used to evaluate NPC decisions. **Human and
LLM labels are kept in separate files and are never merged.** That separation is
enforced in code (`evaluation/annotation.py:check_dataset_purity`), so a mixed
dataset raises instead of silently producing a file a reader could mistake for
human ground truth.

## The three evaluation instruments

The paper reports three independent evaluations. They answer different questions
and must not be conflated:

| instrument | file | what it is | what it is not |
|---|---|---|---|
| 1. Automated invariants | produced by `evaluation/report.py --invariants` | property checks over seeded scenarios (self-consistency) | not independent of the author |
| 2. LLM judge | `llm_labels.json` | a **disclosed, non-blind, repo-aware** LLM annotation set | **not** human ground truth |
| 3. Human raters | `human_labels.json` (not yet created) | independent human annotation per `docs/HUMAN_EVAL_PROTOCOL.md` | not yet collected |

If a reviewer asks "who annotated these cases?", the answer is precise: automated
invariants are instrument 1; `llm_labels.json` is instrument 2, an LLM judge that
has read the codebase and is therefore *not* blind; and instrument 3 — human
raters — has not been run yet.

## Files

* **`llm_judge_cases.json`** — ten fresh evaluator cases (clean state, active /
  disputed / superseded belief, a rumour echo chain, independent corroboration,
  guard warrant gating, stock gating, betrayal after trust). These are **not** the
  repository's author-labelled set; they were authored for the judge pilot.
* **`llm_labels.json`** — the LLM judge's annotations, with
  `annotator_type: "llm_repo_aware"` and `blind: false`. The `bias_disclosure`
  field states that this annotator has read the author labels and utility
  weights, so the blind protocol is violated. Use it as a pilot / sanity check,
  not as a result.

## Using them

```bash
python -m pytest tests/test_dataset_separation.py -q    # guard + validator
```

To add real human labels, run the protocol (`tools/annotate.html` →
`--merge-labels`) and save the result as `human_labels.json` with
`annotator_type: "human"`. Do **not** merge it with `llm_labels.json`; report the
two sets side by side.
