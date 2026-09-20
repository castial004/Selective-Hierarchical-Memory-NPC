# Evaluation Results — v0.5.0

Every number in this file is produced by one command and can be regenerated in
about three seconds:

```bash
python -m npc_memory_project.evaluation.report --all --json results.json
```

Instrument: **21 author-labelled cases** (`label_source="author"`) and the
**60-scenario invariant suite** (63 checks), both run against the same six
retrieval policies through the same decision engine.

> **These labels are not human ground truth.** They were written by the system's
> author, so they are a regression instrument, not evidence of correctness. The
> protocol that replaces them with independently collected labels is
> `docs/HUMAN_EVAL_PROTOCOL.md`; it has **not** been executed. Any claim of the
> form "human-validated" is unsupported until it is.

## 1. Retrieval comparison

| method | author-labelled | 95% Wilson | invariants | full − method (bootstrap) |
|---|---|---|---|---|
| **SHM (this architecture)** | **21/21** | 100.0%, 84.5–100.0% | **63/63** | reference |
| recency-only | 19/21 | 90.5%, 71.1–97.3% | 48/63 | +9.5 pts [0, +24] |
| importance-only | 20/21 | 95.2%, 77.3–99.2% | 62/63 | +4.8 pts [0, +14] |
| recency+importance (status-blind) | 20/21 | 95.2%, 77.3–99.2% | 62/63 | +4.8 pts [0, +14] |
| **status-aware, no tiers** | **21/21** | 100.0%, 84.5–100.0% | **63/63** | **+0.0 pts [0, 0]** |
| tiers, status-blind | 20/21 | 95.2%, 77.3–99.2% | 62/63 | +4.8 pts [0, +14] |

### What this does and does not show

* **It shows** the architecture beats a naive recent-first stream on both
  instruments, and that the gap is attributable to *status-aware* retrieval.
* **It does not show** that the tier hierarchy contributes anything. Removing it
  costs exactly zero on both instruments (row 5). One case out of 21 and one check
  out of 63 separate the remaining baselines — those intervals all include zero,
  so **at this N the difference between the full architecture and the
  importance-based baselines is not statistically distinguishable.** The honest
  reading is "status filtering matters; the rest is unproven at this sample size."
* Every interval spans or touches zero except recency-only's lower bound, and even
  that is a 1-case margin out of 21. Treat the ranking as a hypothesis, not a
  result.

## 2. Component and feature ablation

| variant | author-labelled | invariants | note |
|---|---|---|---|
| full architecture | 100.0% | 63/63 | status filter + tiers + semantic tier |
| no status filter | 95.2% | 62/63 | superseded/disputed/expired stay retrievable |
| no tiers (status kept) | 100.0% | 63/63 | flat store, status still enforced |
| tiers, no status | 95.2% | 62/63 | structure without belief status |
| no semantic tier | 100.0% | 63/63 | derived beliefs never retrieved |
| recency only | 90.5% | 48/63 | most recent *k*, no status, no tiers |
| recency + importance, status-blind | 95.2% | 62/63 | blend without relevance or status |
| feature off: **theft** | **71.4%** | 63/63 | one causal channel zeroed |
| feature off: innocence | 95.2% | 63/63 | |
| feature off: help / rumour / confession | 100.0% | 63/63 | no measurable contribution here |

Findings, stated as measured:

1. **Belief status is load-bearing.** It is the only component whose removal
   degrades both instruments.
2. **Tiers are not.** With status filtering intact, the Working/Episodic/Semantic/
   Archive hierarchy changes no decision in this suite. The tier multiplier and the
   admission policy therefore need a different justification — or a different
   experiment — before they can be presented as a contribution.
3. **The semantic tier contributes nothing measurable.** Derived beliefs never
   being retrieved costs zero, because the underlying episodic records carry the
   same feature signal. v0.2.1 fixed the *plumbing* that let semantic records
   influence decisions at all; this shows the influence is currently redundant.
4. **The `theft` channel carries the decision.** Zeroing it costs 6 of 21 cases.
   `help`, `rumour` and `confession` cost nothing — they are implemented and
   documented but unexercised by these cases.

These are negative results about this project's own claims. They are reported
because the alternative — a table where every component "helps" by one case — is
how an unevaluated system looks.

## 3. Scaling

| NPCs | memories/NPC | store records | retrieved | median | p95 | invariants |
|---|---|---|---|---|---|---|
| 5 | 10 | 50 | 5 | 0.035 ms | 0.065 ms | 100% |
| 20 | 50 | 1,000 | 5 | 0.060 ms | 0.088 ms | 100% |
| 20 | 200 | 4,000 | 5 | 0.167 ms | 0.339 ms | 100% |
| 60 | 50 | 3,000 | 5 | 0.098 ms | 0.179 ms | 100% |

(The store sizes dropped from v0.4.0's because the synthetic fixture was appending
a second record under an existing ``event_id``; see section 6.3. A real store keys on
that id, so the fixture now does too.)

* Latency is bounded by **store size, not world size**: retrieval scans every
  record that belongs to the NPC and then keeps five. At 4,800 records a decision
  costs 0.365 ms median / 0.428 ms p95, so a 60 fps frame (16.7 ms) has three
  orders of magnitude of headroom for a handful of NPCs per frame.
* The scan was linear in the *whole* NPC history in v0.4.0, including records no
  decision could ever use. That is fixed in v0.5.0 -- see section 6.4, which measures
  a 4.0x / 9.1x / 1.8x reduction in per-decision retrieval cost on the same stores.
  Retrieval is still linear in the *retrievable* set, so nothing here should be
  described as O(1).
* Cross-NPC stores were generated synthetically (`evaluation/scaling.py`) and do
  not exercise the persistence layer, whose own benchmark is in
  `docs/architecture.md`. Treat the shape of the curve — linear in NPC history,
  flat in retrieved count — as the finding, not the third decimal.

## 4. Engine defect found by this instrument

The author-labelled suite immediately failed three cases in the *full*
architecture: `no-stock-removes-trade`, `no-money-removes-trade` and
`equal-confidence-conflict-is-disputed`. In all three a cautious shopkeeper chose
`warn_player`/`refuse_trade` against a customer with nothing on file.

Cause: `cautious` was added to `warn_player`, `call_guard` and `refuse_trade` as an
ungated flat bonus (`0.20 × cautious`), so any shopkeeper with a high `cautious`
trait pushed a punitive action above `talk` regardless of the memories retrieved —
cautiousness was modelled as a personality that punishes, rather than a response
to a perceived threat.

Fix (`decision/engine.py`): the term is gated on the *presence* of a threat
(`theft > 0 or rumour > 0`). When a believed accusation is in the retrieved set the
weight is bit-for-bit the paper's original value, so no previously correct
scenario moved; the 63/63 invariant result is unchanged. A graded gate was tried
first and rejected: it halved the push in the `accusation+noise` scenario and
broke invariant I2 (63/63 → 62/63). Both the fix and the rejected alternative are
covered by tests in `tests/test_evaluation.py`.

## 5. Limitations

1. **Labels are the author's.** 21 cases is small; the Wilson intervals are wide
   (84.5–100% for a perfect score). No human number exists yet.
2. **The invariant suite is self-authored** and therefore tests self-consistency.
   It is a strong regression net and weak evidence of correctness.
3. **The labelled set is scenario-bound.** Every case is drawn from the bundled
   Mira theft scenario vocabulary, so "passes the suite" cannot be generalised to
   other worlds or roles. The guard role is covered by two cases; no other role is.
4. **One seed.** Invariants use `build_scenarios(60)` and the bootstrap uses seed
   `20260920`; both are fixed so results are reproducible, which also means the
   scenarios are a single sample. `--invariants 200` and `--invariants 1000` widen
   it; the numbers above come from 60.
5. **Ablations are heavy-handed.** `NoStatusFilter` rewrites record status rather
   than modelling a system that never tracked it, and `FeatureMaskedEngine` zeroes
   a channel without retraining anything (there is nothing to retrain — the weights
   are hand-calibrated).
6. **No LLM baseline.** Every policy here is deterministic and local, so the
   comparison says nothing about an LLM-driven NPC.
7. **The long-horizon results are two timelines** (section 6): one NPC, one scenario
   vocabulary, 2 chatter events per day. Retention is demonstrated; *robustness* of
   retention is not.
8. **Tiers remain decision-redundant** even after section 6.3. They now have a
   measurable *cost* role via the index, which is not the same as being necessary.

## 6. Long-horizon retention, and what the tier hierarchy is actually for

Every instrument above freezes time: a handful of records, one day, one decision.
Tiers and semantic beliefs exist to work *over* time, so testing them on frozen state
tests them where they cannot matter. This section runs the clock -- 120 simulated
days through the real pipeline (`event_to_memory` -> `revise` -> `manage_lifecycle` ->
`consolidate`), with warnings probed at days 5/10/20/40/80/120.

Two timelines. **A (exonerated):** day 1 accusation, day 3 verified exoneration --
probes expect warmth. **B (accused):** the accusation is never retracted -- probes
expect the shop to stay shut. "dec" is the share of probes where the decisive record
(the exoneration, or the accusation) was actually in the retrieved top-5.

| policy | A acc | A dec | B acc | B dec |
|---|---|---|---|---|
| **SHM (this architecture)** | **100%** | **100%** | **100%** | **100%** |
| no semantic tier | 100% | 100% | 100% | 100% |
| status-aware, no tiers | 100% | 100% | 100% | 100% |
| tiers, status-blind | 100% | 100% | 100% | 100% |
| recency only | 100% | **0%** | **0%** | **0%** |

### 6.1 Retention holds -- the first real evidence for the architecture's claim

An exoneration verified on day 3 still governs the decision on day 120, and an
accusation never retracted still closes the counter on day 120. Knowledge survives
120 days and ~240 competing records. This is the claim the project has been making
since v0.1 and had never tested.

### 6.2 Accuracy alone would have flattered a system with total amnesia

recency-only scores **100% on timeline A while retrieving the decisive record 0% of
the time**. By day 5 its top-5 is pure chatter, so it answers "warm" because it has
*no signal at all* -- and on timeline A, warm happens to be right. Only the
decisive-in-top-5 column exposes that. Any retention result reported without it
should be distrusted, this one included.

### 6.3 The tier hierarchy is redundant with belief status, and here is the proof

At day 120 the store holds 243 records: 5 working, 1 episodic, 1 semantic, and **236
archived**. Of those 236 archived records, **236 are also `SUPERSEDED` or `EXPIRED`
-- 100%**. The lifecycle only ever archives a record it has already excluded by
status, so `tier != ARCHIVE` excludes a strict subset of what
`status not in (SUPERSEDED, EXPIRED, DISPUTED)` excludes.

That is why removing tiers costs nothing (section 2), and it is worse than that: the
two mechanisms are *mutually* redundant. `tiers, status-blind` also scores 100% on
both timelines, because the archived copy of a superseded record is already out of
reach. Either filter alone reproduces every result this repository can produce.

**What to do about it, honestly:** the tier structure is not earning its keep as a
decider. What it does do is bound cost, which section 6.4 turns into a measurement.
A future version should either give the tiers a decision-level job (the natural
candidate: consolidate a resolved conflict into a semantic belief and *archive its
source episodes*, so knowledge survives compression) or drop them from the claim.
Neither is done here.

### 6.4 The cost side: a retrieval index

If archival never changes a decision but always shrinks the reachable set, then the
exclusion machinery is a *cost* mechanism, and the manager was paying that cost on
every call -- scoring 243 records to keep 7. `memory/index.py` keeps the retrievable
subset per NPC up to date instead, and `TownSimulation` now drives it from its write
hooks.

| store | records | reachable | skipped | median | indexed | speedup | same answer? |
|---|---|---|---|---|---|---|---|
| archived-heavy (day 120) | 243 | 7 | 236 | 0.025 ms | 0.006 ms | **4.0x** | yes |
| multi-NPC (60 x 50) | 3,000 | 8 | 2,992 | 0.067 ms | 0.007 ms | **9.1x** | yes |
| deep history (1 x 4,800) | 4,800 | 896 | 3,904 | 1.249 ms | 0.700 ms | 1.8x | yes |

The equivalence check is not decoration. The first implementation keyed records by
`event_id` in a plain dict, which *silently dropped duplicates*; the indexed path
returned a different top-5 than the brute-force scan on a store that happened to hold
two records under one id, and the check failed the row rather than reporting a 7.2x
speedup that was really an answer-changing bug. The index now uses the SQLite store's
own keying (upsert by `event_id`) and *counts* collisions so a corrupt store shows up
instead of being quietly deduplicated.

Read the table honestly: the win scales with how much of the store is dead weight.
Where almost everything is reachable (deep history, 896 of 4,800) it is 1.8x, and if
the hot set were the whole store there would be no win at all.

## 7. Reproducing

```bash
pip install -e ".[dev]"
python -m npc_memory_project.evaluation.report            # table in section 1
python -m npc_memory_project.evaluation.report --ablation # section 2
python -m npc_memory_project.evaluation.report --scaling  # section 3
python -m npc_memory_project.evaluation.report --longitudinal  # section 6.1-6.3
python -m npc_memory_project.evaluation.report --indexing      # section 6.4
python -m npc_memory_project.evaluation.report --invariants 200
pytest tests/test_evaluation.py tests/test_memory_index.py -q
```

Numbers above were produced on the development machine on 2026-09-20; latencies
are machine-dependent, accuracies are not.
