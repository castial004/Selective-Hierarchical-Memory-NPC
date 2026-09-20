# Changelog

## v0.4.1 -- the UI is drawn at window resolution

v0.4.0 made the window scalable but scaled *everything* in it, text included. On a
resized or fullscreen window that meant a 13 px label went through a 1.46x
resample: the memory inspector's text turned to mush and its cause lines were
truncated mid-sentence. Reported from a 1400x933 window, reproduced exactly, fixed
here.

### Two-pass rendering

| pass | what | how |
|---|---|---|
| 1 | world: tiles, characters, shadows | fixed 960x640 logical frame, scaled into the window by `display.py` (blocky, on purpose) |
| 2 | UI: HUD, dialogue, shop, inspector, help, world labels, toast | drawn *after* presenting, straight onto the window, fonts created at `logical_size x factor` px -- never resampled |

New module `game/ui.py` (`UiCanvas`, `window_canvas`). The UI is antialiased; the
world keeps hard pixel edges.

* **Scale-invariant layout** -- `measure`/`wrap` use logical font metrics, so
  panels wrap to the same lines at every window size and resizing never re-flows a
  conversation.
* **Surface-span layout** -- `origin`/`span_w` describe the logical rectangle the
  whole surface covers, so the inspector and help screens use the full window
  instead of the letterboxed column. The HUD and footer bars now span edge to edge.
* The inspector shows as many records as the window can hold, wraps the certified
  cause over up to three lines **in full** (it used to clip at the column edge with
  an ellipsis), and wraps summaries instead of cutting them at 34 characters.

### Also fixed

* Reply cursor and "more replies" marker rendered as tofu boxes (`▶`, `▼` are not in
  pygame's default font). They are drawn shapes now.
* Shop hint used `↑/↓`, which was also two tofu boxes; it reads `UP / DOWN`.
* `--screenshot` saves the presented window at any size, so the old
  `--capture-window` distinction is gone (the flag is kept as a no-op alias).
* `Game.draw()` became `draw_world()` + `draw_ui()` + `render()`; the headless test
  now saves the window rather than the pre-UI logical frame.

### New

* `--day N` for `--screenshot`, so the day-1 refusal capture is reproducible from
  the CLI instead of hand-edited state.
* `tests/test_ui_canvas.py` (13 tests) and a scale test in `tests/test_game_logic.py`
  pinning the contract: fonts are rendered at final size, layout is scale-invariant,
  and full-screen panels really do cover the letterbox area.
* Screenshots regenerated with the new pipeline, plus a fullscreen inspector and a
  1600x1000 dialogue capture, and a before/after pair in the README.

Tests 107 -> **120**.

## v0.4.0 -- window scaling and research validation

Two unrelated pieces of work, both from the same audit pass: the game now fills any
window, and the project can finally measure itself against something.

### Game: bigger UI, real fullscreen

The window was fixed at 960x640 with no way to enlarge it. The fix keeps a fixed
**logical** frame and scales it into whatever window exists, so no UI element is
repositioned and the pixel art stays crisp at integer scales.

| Control | Effect |
|---|---|
| `F11` | toggle fullscreen |
| `F10` | cycle window size 1x / 1.25x / 1.5x / 2x |
| drag the window edge | live resize, letterboxed |

New flags: `--scale 2`, `--window 1600x900`, `--fullscreen`, `--capture-window`.
New module `game/display.py` (`Display`, `LOGICAL_SIZE`, `WINDOW_STEPS`), 9 tests in
`tests/test_display.py`. Mouse clicks are mapped through `to_logical`, so hit-testing
is unaffected by scaling or letterbox bars.

### Evaluation: baselines, ablation, scaling, statistics

The v0.2 numbers were stale and there was nothing to compare against.

| Module | Role |
|---|---|
| `evaluation/baselines.py` | five retrieval policies behind the manager's own signature: recency-only, importance-only, recency+importance, status-aware-no-tiers, tiers-status-blind |
| `evaluation/labelled.py` | 21 author-labelled decision cases, each isolating one mechanism (`label_source="author"`) |
| `evaluation/ablation.py` | component and per-feature-channel ablation |
| `evaluation/scaling.py` | decision latency vs NPC count and per-NPC history |
| `evaluation/stats.py` | Wilson interval, paired bootstrap, Cohen's kappa, summaries |
| `evaluation/report.py` | one CLI producing every reported number; `--export-labels`, `--labels`, `--preference`, `--invariants N` |
| `docs/EVALUATION.md` | the results, with limitations, including the negative ones |
| `docs/HUMAN_EVAL_PROTOCOL.md` | the protocol for real human labels -- **written, not executed** |

Main result: 21/21 labelled and 63/63 invariants for the full architecture, against
19/21 and 48/63 for recency-only. Honest caveats, all in `docs/EVALUATION.md`:
labels are the author's, no interval except recency-only's excludes zero, and the
tier hierarchy plus the semantic tier cost nothing measurable when removed.

### Fixed

* **Cautious NPCs punished innocent players.** `cautious` was added to
  `refuse_trade` / `warn_player` / `call_guard` as an ungated flat bonus, so a
  cautious shopkeeper warned a customer with nothing on file. It is now gated on the
  presence of a threat (`theft > 0 or rumour > 0`), which restores the paper's
  original weights in every scenario that has an accusation and leaves 63/63
  intact. Found by the labelled suite on its first run.
* `Display.window_size` overrides `scale` -- `--window 1600x900` produced 1600x1066
  by deriving the scale from width alone.
* Window capture saved a black frame unless `display.present()` had run.
* `to_logical`/`to_window` now `round` instead of truncating, which was dropping the
  last logical pixel and breaking click round-trips.

### Tests

73 -> **106** (`tests/test_evaluation.py` adds 24, `tests/test_display.py` adds 9).
`test_baselines_actually_discriminate` exists because the first version of the
labelled set scored every method identically -- a comparison that does not compare.

## v0.3.0 — the playable town

A pixel-art pygame front end over the research core, plus the fixes the game
needed. The core (`memory/`, `beliefs/`, `decision/`, `explainability/`) is
untouched; the game is a new optional layer.

```bash
pip install -e ".[game]"
npc-memory-game
```

**New package — `src/npc_memory_project/game/`**

| Module | Role |
|---|---|
| `pixel_art.py` | palettes + 16x16 sprite specs, with a validator (no pygame import) |
| `assets.py` | builds/caches scaled surfaces; procedural ground; 16x24 character composer |
| `world_map.py` | tile grid, `BLOCKING`, collision, `Camera`, `move_with_collision` |
| `shop.py` | catalogue, wallet, offers, discount rule, purchases |
| `conversation.py` | 18-node dialogue graph gated on live memory state + 6 effects |
| `renderer.py` | world/HUD/dialogue/shop/inspector/day/help drawing |
| `app.py` | `Game` — loop, scenes, input, `--screenshot` headless mode |

**Gameplay**

* Four NPCs in a walkable town: Mira (apothecary), Kael (guard), Arun (market
  stall), Rohan (alley).
* Genshin-style dialogue box: portrait, name plate, typewritten speech, up to
  seven numbered replies with mouse and 1–9 selection.
* The orange tag above every line is the counterfactually certified cause — the
  research claim, visible in-game.
* Shops gate on memory state: Mira refuses to trade while she believes the
  accusation, and opens the counter once the belief is revised.
* A resolution quest with two routes: buy the market ledgers from Arun and
  present the receipts to Kael, or corner Rohan into a confession. Both flow
  through the normal belief updater.
* Rumours are buyable at Arun's stall and return his actual top memory as hedged
  speech, confidence included.
* `J` memory inspector: tier and status dots, importance, confidence per NPC.
* `N` day cycle with a summary overlay, `F1` help, `--screenshot` for headless
  capture.

**Fixes surfaced while building it**

* `TownMap.is_blocked()` crashed with `TypeError` on float coordinates — i.e.
  the first frame of movement. `get()` now coerces to `int`.
* `Camera` was pinned to the map corner because `build_town()` defaulted to a
  16px tile size while the renderer draws 48px tiles; the game now passes
  `tile_size=TILE_PX`.
* A tree was planted inside the pond, and the alley fence filled its own
  interior, leaving Rohan unreachable.
* Arun's stall listed `apples`/`bread` while the shop catalogue asked for
  `apple`/`bread`, so every item showed "out of stock".
* UI text was rendered at half size and upscaled x2, which mangled the default
  font; text now renders at final size.
* `npc-memory-game` is a console entry point; `pygame` is an optional extra, so
  the core still installs with no dependencies at all.

**Tests: 53 → 73.** `tests/test_game_logic.py` covers map integrity (every NPC
stands somewhere walkable), collision and sliding, camera clamping, the shop
rules, every dialogue node and `goto` target, the memory-state gating, a full
quest-loop integration test, and a headless render smoke test that skips cleanly
when pygame is absent.
