# Evaluation Results — v0.4.0

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
| 5 | 10 | 60 | 5 | 0.036 ms | 0.061 ms | 100% |
| 20 | 50 | 1,200 | 5 | 0.062 ms | 0.091 ms | 100% |
| 20 | 200 | 4,800 | 5 | 0.365 ms | 0.428 ms | 100% |
| 60 | 50 | 3,600 | 5 | 0.114 ms | 0.173 ms | 100% |

* Latency is bounded by **store size, not world size**: retrieval scans every
  record that belongs to the NPC and then keeps five. At 4,800 records a decision
  costs 0.365 ms median / 0.428 ms p95, so a 60 fps frame (16.7 ms) has three
  orders of magnitude of headroom for a handful of NPCs per frame.
* It is **not** sublinear, and nothing here should be described as O(1) or
  "constant-time". An index over `(npc_id, tier, status, game_day)` is the obvious
  next optimisation and is not implemented.
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

## 6. Reproducing

```bash
pip install -e ".[dev]"
python -m npc_memory_project.evaluation.report            # table in section 1
python -m npc_memory_project.evaluation.report --ablation # section 2
python -m npc_memory_project.evaluation.report --scaling  # section 3
python -m npc_memory_project.evaluation.report --invariants 200
pytest tests/test_evaluation.py -q
```

Numbers above were produced on the development machine on 2026-09-20; latencies
are machine-dependent, accuracies are not.
