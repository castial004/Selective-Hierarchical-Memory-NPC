# Audit changelog: v0.2 → v0.2.1

Independent code audit of `main` @ `393d116` (v0.2), the fixes applied on top, and
what each one implies for the paper draft in `docs/`.

Every "before" claim below was reproduced against the unmodified v0.2 code.
Every "after" claim is covered by a test in `tests/test_audit_fixes.py` or
`tests/test_web_server.py`.

**Test suite: 17 → 53 passing. Overall coverage held at ~81% while the codebase
grew from 605 to 1,208 statements; `web/server.py` went 0% → 72% covered, and the
modules that matter for correctness (`core/features.py`, `decision/engine.py`,
`explainability/counterfactual.py`, `evaluation/harness.py`) are at 98–100%.**

---

## 1. Directory traversal in the web server — 🔴 security

**Before.** `_serve_file` joined request input onto `STATIC_DIR` with no
containment check, so `..` survived:

```console
$ curl -s --path-as-is "http://127.0.0.1:8098/static/../../../../../../../etc/passwd"
root:x:0:0:root:/root:/usr/bin/bash      # HTTP 200, 1242 bytes
```

Local-only while bound to `127.0.0.1`, remote file disclosure the moment anyone
binds `0.0.0.0` for a demo box or container.

**After.** `_serve_static` resolves the candidate path and requires
`Path.relative_to(STATIC_DIR)`, returning 403 otherwise. Percent-encoding is
decoded before resolution. Traversal attempts now 403; `/`, `/static/*` and the
API are unaffected.

**Also hardened:** CORS is opt-in (`--cors` / `NPC_CORS=1`) instead of always
`Access-Control-Allow-Origin: *`. The bundled UI is same-origin and needs no CORS
headers; leaving them on let any web page the user visited drive the simulation
through their browser. The simulation is also no longer constructed at import
time, and host/port are configurable with a localhost default.

---

## 2. The LLM dialogue hook reported `faithful: True` unconditionally — 🔴 correctness of the central claim

**Before.** `FaithfulDialogueSynthesizer.synthesize()` hardcoded
`"faithful": True`, and `LLMDialogueHook.polish()` returned whatever the model
produced with no check. Probe with a deliberately non-compliant backend:

```
input:  certified reason "Officer Kael proved Rohan was the thief"
model:  "I saw you burn down the orphanage! And you owe me 500 gold!"
output: dialogue = that hallucination, faithful = True,
        grounded_factor = "Officer Kael proved Rohan was the thief"
```

The paper's "zero post-hoc rationalizations" guarantee held only for the
deterministic template path, and the API lied about it.

**After.** New `verify_dialogue_grounding()` requires every certified causal
factor to retain at least one distinctive content token in the candidate.
`polish_verified()` returns `(dialogue, source, faithful)` where source is
`deterministic` / `llm_verified` / `llm_rejected`; rejected output is discarded
and the grounded template is restored. The simulator and inspector UI surface the
source and withhold ungrounded text.

*Limits now documented in the code:* the check catches wholesale hallucination
and dropped factors; it does **not** catch an invented claim that reuses the same
vocabulary. Passing is necessary, not sufficient.

---

## 3. The evaluation could not fail — 🔴 research validity

**Before.** `evaluation/benchmark.py` asserted the program's own output:

```python
pass4 = (top_action == "apologise" and abs(top_score - 0.581) < 0.05)
pass5 = (flipped and abs(delta - 0.286) < 0.05)
```

and the headline footprint figure was arithmetic on literals — no tokenizer, no
store, no measurement:

```python
working_count, episodic_count, semantic_count = 5, 3, 1
flat_tokens, hierarchical_tokens = 25 * 45, 9 * 45
reduction_pct = 1 - (405 / 1125)          # 64.0%, always
```

**After.** Three replacements:

1. **Contract checks as properties.** "The exoneration is the certified cause and
   ablating its lineage changes the action" — not "the score is 0.581".
2. **Invariant suite** (`evaluation/harness.py`) over 60 seeded scenarios with
   ambient noise memories, run against this architecture *and* a flat,
   status-blind stream:

   | invariant | SHM | flat baseline |
   |---|---|---|
   | I1 active exoneration suppresses punishment | 38/38 | 29/38 |
   | I2 active accusation + trust ≤ 0 suppresses warmth | 12/12 | 9/12 |
   | I3 disputed belief changes nothing | 13/13 | 12/13 |
   | **total** | **63/63 (100%)** | **50/63 (79.4%)** |

   The noise is what makes this discriminating: with few memories, top-k returns
   everything relevant and a status-blind stream scores as well as a selective
   one. A test asserts the suite separates the two, so it cannot silently stop
   measuring anything.
3. **Measured footprint and layered latency** instead of assumed constants:

   | measurement | v0.2 | v0.2.1 |
   |---|---|---|
   | footprint | 64.0%, from `1 - (405/1125)` | 48.6% per decision measured (19,109 → 9,828 chars over 60 scenarios), 13.7% in the 6-day live session; documented as a character/whitespace-proxy, not a tokenizer |
   | decision latency | 0.0143 ms, engine arithmetic only | 0.019 ms engine-only, 0.080 ms store+retrieve+decide, 0.248 ms full interaction |

   The suite now prints an explicit "what this does not establish" section.

---

## 4. The Semantic tier was inert — 🟠 architecture

**Before.** `_features()` substring-matched `event_type` for
`theft/innocence/help/rumour/confess`. Semantic beliefs are written as
`belief_player_falsely_accused` and `semantic_consensus` — neither matches, so
the whole tier had **zero** influence while consuming retrieval slots and a 1.1×
tier multiplier. Independently, `choose_tier()` gated SEMANTIC admission on
`metadata["is_summary"]`, and `grep -rn is_summary src/` showed nothing in the
repository ever set that key.

**After.** `core/features.py` introduces an explicit `metadata["feature_key"]`
channel, written by the belief updater and consolidator from the claim they
assert, with the legacy keyword scan retained as a fallback (existing records
behave identically; a test pins this). Consequence, on the Day-4 decision:

| | v0.2 | v0.2.1 |
|---|---|---|
| innocence feature from semantic memory | 0.000 | 0.950 |
| `apologise` vs `trade` | 0.581 vs 0.450 | **0.677 vs 0.485** |
| certified cause, ablated | guard proof | guard proof **+ its derived summary** |
| ΔU of the certified cause | 0.286 | **0.383** |

`choose_tier` now also admits `source in {consolidation, belief_revision}`.

---

## 5. Ablation had to follow derivation lineage — 🟠 correctness that the fix in §4 exposed

Turning the Semantic tier on revealed a latent flaw in the verifier. Removing a
source memory left its summary in place; the summary carries the same signal, so
no action flipped and the verifier reported the true cause as **causally inert**:

```
v0.2 verifier, semantic belief carrying the signal:
  ablate guard proof -> apologise  changed=False  delta=0.000     <-- wrong
lineage-aware verifier:
  ablate guard proof -> trade      changed=True   delta=0.383     removed 2 records
```

**After.** The updater and consolidator write `derived_from` / `origin_event_id`,
and `CounterfactualExplanationVerifier` ablates the memory *plus its transitive
descendants* (`follow_lineage=True`, disable with `follow_lineage=False`).
`ablation_group()` is public so the UI can show what a trial removed, and the
counterfactual endpoint reports `ablated_ids`.

This is the correct counterfactual: a world where the guard never proved Rohan's
innocence is also a world without the "player was falsely accused" summary.

---

## 6. `DISPUTED` memories drove decisions at full weight — 🟠 behaviour

**Before.** `retrieve()` filtered only `SUPERSEDED`/`EXPIRED`, so claims the
updater had explicitly declined to accept entered the feature vector at full
`importance × confidence`. A guard whose only memory was a disputed rumour chose
`arrest_player`:

```
MemoryRecord(event_type='rumour_theft_confession', status=DISPUTED, I=0.85, C=0.85)
-> valid: [... 'arrest_player' ...]      decision: arrest_player
```

Reachable through the rumour UI in multi-NPC configurations.

**After.** DISPUTED is excluded from retrieval by default
(`include_disputed=True` to inspect). The same memory now yields no punitive
action, and a test locks it down. Reachable end-to-end: after Mira is exonerated,
`arun → mira` rumour traffic lands as DISPUTED and her behaviour no longer moves.

---

## 7. The guard's arrest gate was `pass` — 🟠 the one rule encoding game law

**Before.**

```python
if not world.player_wanted and world.metadata.get("suspect") != "player":
    if "arrest_player" in actions and world.metadata.get("permit_arrest") != "true":
        pass        # comment: "only keep arrest if world metadata permits"
```

```
valid_actions(guard, wanted=False, no permit) -> [... 'arrest_player' ...]
decide(...)                                   -> 'arrest_player'
```

**After.** `guard_may_arrest()` implements the rule (wanted, `suspect == player`,
or `permit_arrest`). Verified both ways: arrest is pruned when unwarranted and
still available when a warrant exists.

---

## 8. `":memory:"` SQLite store was not thread-safe — 🟠 availability

**Before.** One shared connection created on the importing thread with
`check_same_thread=True`, so the first request from any other thread died:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in
that same thread. (created 140009174782848, this 140009144854208)
```

Reproduced by swapping `HTTPServer` → `ThreadingHTTPServer`, i.e. the shipped
simulator crashed as soon as it was made concurrent.

**After.** `check_same_thread=False` plus an `RLock` around every operation, a
`close()` method, five new indexes, and the duplicated row-mapping block in
`list_for_npc`/`list_by_tier` collapsed into `_row_to_memory`. Eight concurrent
threads now write, read and record traces without error; the server runs threaded
by default.

---

## 9. Rumour subsystem — 🟠 feature was dead in the shipped flow

**Before.** `share_rumour` selected the speaker's strongest ACTIVE memory, and
Arun — the NPC the UI's rumour button posts as speaker — never owned a memory.
The button always failed: `Day 1 → None`, `Day 4 → None`. Two more defects:
`location=listener.role` wrote a role name into a spatial field (which then
flowed into tags and retrieval keys), and corroboration never accumulated
confidence, so ten witnesses were worth one.

**After.**

* The preset records Arun's own first-person claim on Day 1, so the button works
  (`status: "shared"`) — and it is a more realistic model of an accuser who
  believes what he spreads.
* `share_memory(..., location=...)` is explicit; the caller passes the world
  location.
* Independent corroboration raises confidence
  (`C ← C + gain·(1 − C)`, default gain 0.05); hearsay echo does **not** —
  a bump requires a different source, a non-matching `origin_event_id`, and the
  speaker absent from the `source_chain`. Tests cover both directions.
* `share_rumour` now reports what the listener actually concluded
  (`listener_belief_status`, `listener_usable_in_decisions`).

---

## 10. Smaller fixes

* `revise()` no longer mutates the caller's `incoming` record in place.
* `present_evidence` / `persuade_rohan` / `reset` moved out of the HTTP handler
  into `TownSimulation`, so the scenario is testable without a socket.
* The apology trust bump is now `TownSimulation.apology_trust_gain` and is
  reported as `trust_delta` instead of being a magic `+15.0`.
* `ExplanationEvidence` carries `memory_id`, removing summary-string matching in
  the UI/API layers.
* Inspector shows `dialogue_source` and withholds ungrounded text.
* `pyproject.toml`: version, description, licence, classifiers, keywords, three
  console entry points (`npc-memory-demo`, `npc-memory-benchmark`,
  `npc-memory-simulator`), `coverage` in dev extras.
* `LICENSE` (MIT) added — **decision for the author**: v0.2 shipped no licence,
  which blocks clean reuse and citation clarity. Replace or delete if MIT is not
  your intent.
* README rewritten around the simulator, the evaluation suite, the LLM
  environment variables and the honest limitations.

---

## Open items (deliberately not "fixed")

These need design decisions, not patches, and are documented rather than papered
over:

1. **Retrieval relevance is a constant.** `retrieve()` computes
   `rel = 1.0 if event_type == m.event_type else 0.45`, and no production caller
   ever passes `event_type`, so `Rel(m) ≡ 0.45` and the paper's α·Rel term is
   inert. Fixing this means deciding what the retrieval *query* is for an
   interaction — a design question.
2. **Recency drift.** The paper writes `1/(1 + (τ_curr − τ_m))`; the code uses a
   decay constant λ = 0.1. One of the two should change.
3. **Scripted inputs sit outside the audit loop.** The Day-3 exoneration is
   hardcoded in `_apply_scripted_events`, and it sets Mira's trust by fiat. The
   apology is genuinely memory-driven (sweeping trust from −30 to +60 leaves the
   action unchanged), but the audit covers memories only — trust, personality and
   world flags are never ablated.
4. **ΔU is one-sided.** Removing a memory can only lower feature values, so
   `ΔU ≥ 0` in practice and the paper's `|ΔU| ≥ θ_causal` disjunct never fires.
5. **`CLAIM_FEATURES` is scenario vocabulary** living in library code; it belongs
   in scenario data.
6. **Coverage gaps that remain:** `dialogue.py` 53% (unreached template
   branches, e.g. the guard `patrol` line, which no role can select),
   `benchmark.py` 52%, `town_simulation.py` 68%.
7. **Weaker echoes of a held claim are still stored as extra ACTIVE records.**
   Same `conflict_key` and claim with lower confidence neither supersedes nor is
   marked DISPUTED, so `arun → mira` rumour traffic adds duplicate records. The
   decision impact is bounded because features take the maximum, but note that
   the maximum is over `importance × confidence` — and a rumour can carry higher
   *importance* (quest relevance 0.8) than the statement it echoes, so a
   low-confidence echo can still raise a feature value. Gating feature
   aggregation on confidence, or excluding echoes entirely, is a model decision
   rather than a bug fix.
8. **No scenario-level ground truth.** The invariants are hand-authored necessary
   conditions. Real validation needs human-annotated expected behaviour, and an
   LLM-memory baseline (e.g. a Generative-Agents-style flat stream with
   reflection) rather than only a recency baseline.
9. **No CI.** A GitHub Actions workflow running `pytest` on 3.10–3.12 would make
   all of the above durable.

---

## What to change in the paper

| Claim in `docs/Selective_Hierarchical_Memory_NPC_IEEE_Paper.tex` | Status |
|---|---|
| Abstract: "100% test pass rate (5/5)" | Unfalsifiable as written (the checks asserted their own outputs). Replace with the invariant suite and its baseline: 63/63 vs 50/63, and describe the baseline. |
| Abstract / §V: "provable counterfactual explanation faithfulness (ΔS = 0.286)" | Now ΔU = 0.383, because the ablation removes the exoneration *and* its derived summary. State that the verifier is lineage-aware, and that the intervention is a forgetting counterfactual over memories only. |
| §V: "`apologise` dominates (0.581 vs 0.450)" | Now 0.677 vs 0.485, because semantic beliefs finally influence the decision. |
| §V: "Context footprint reduction 64.0%" | Not a measurement. Report the measured 48.6% per decision (chars, whitespace-token proxy) or run a real tokenizer. |
| §V: "Average decision latency 0.0143 ms (target < 1 ms)" | Report per-layer: 0.019 ms engine-only, 0.080 ms store+retrieve+decide, 0.248 ms full interaction. |
| Abstract: "preventing hallucinated rationalizations" | True for the deterministic path; for the LLM path it is now a *checked* property with stated limits (token-overlap grounding, necessary not sufficient). Describe the check honestly. |
| §IV: "Guaranteed Game-State Validity" | Now actually true for the arrest rule; still limited to the enumerated rules. |
| §V: "Semantic-Belief tier" as a decision influence | Was false in v0.2 (ΔU = 0.000), true in v0.2.1. Either fix the paper or drop the claim. |
| §V: one scenario, N = 1, hardcoded Day-3 beat | Keep as a case study, but label it as such and add the seeded suite. |
| References `ssrn2026hierarchical`, `personalityPatent`, `portablePatent`, `budgetPatent` | Unverified in this audit; verify before submission — reviewers check these first. |
| Missing: no ablation study, no baseline, no human evaluation, no limitations on retrieval | §"Discussion and Limitations" currently mentions only parameter calibration. |

---

## Reproducing

```bash
pip install -e ".[dev]"
pytest -q                                        # 53 passed
python -m npc_memory_project.demo.shopkeeper_demo
python -m npc_memory_project.evaluation.benchmark
python -m npc_memory_project.web.server --port 8080
```
