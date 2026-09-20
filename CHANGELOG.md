# Changelog

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
