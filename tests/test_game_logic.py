"""Game-layer tests: map, shop, conversation graph, and the quest loop.

None of these need a display -- the pygame-dependent modules are only imported
inside the smoke test, which skips cleanly if pygame is absent.
"""

from __future__ import annotations

import pytest

from npc_memory_project.game.conversation import (
    ENTRY_NODES, NODES, GameContext, apply_effect, available_choices, entry_node,
    get_node, memory_rows, quest_hint,
)
from npc_memory_project.game.shop import (
    CATALOGUE, DISCOUNT_RATE, Wallet, build_offers, buy, price_for,
)
from npc_memory_project.game.world_map import (
    BLOCKING as BLOCKING_TILES, Camera, Tile, TownMap, build_town, move_with_collision,
)
from npc_memory_project.simulation.town_simulation import TownSimulation


# ------------------------------------------------------------------- world map
def test_town_builds_with_reachable_npcs():
    town = build_town()
    assert len(town.posts) == 4
    for post in town.posts.values():
        assert town.standable_near(post.tile), f"{post.npc_id} stands in a wall"


def test_map_borders_and_buildings_block_movement():
    town = build_town()
    assert town.is_blocked(-1, -1)
    assert town.is_blocked(town.pixel_size()[0] + 4, 10)
    # a building interior is solid
    assert town.rect_blocked((4 * 16, 14 * 16, 8, 8)) is True
    # open grass is not
    assert town.rect_blocked((19 * 16 + 4, 24 * 16 + 4, 8, 8)) is False


def test_movement_slides_along_walls_and_stops_at_them():
    town = TownMap(width=6, height=6)
    town.fill_rect(0, 3, 6, 1, Tile.WALL)          # a full-width wall at y=3
    rect = (16.0, 16.0, 8, 8)

    blocked_x, blocked_y = move_with_collision(town, rect, 0, 40)
    assert blocked_y == 16.0, "should not pass through the wall"

    slid_x, slid_y = move_with_collision(town, rect, 20, 40)
    assert slid_x == 36.0, "should still slide horizontally while blocked vertically"
    assert slid_y == 16.0


def test_camera_clamps_and_follows():
    town = build_town(tile_size=48)
    camera = Camera((960, 640), town.pixel_size())
    camera.centre_on(2400, 1800)
    assert 0 <= camera.x <= town.pixel_size()[0] - 960
    assert 0 <= camera.y <= town.pixel_size()[1] - 640

    camera.centre_on(0, 0)
    assert (camera.x, camera.y) == (0.0, 0.0)

    camera.centre_on(*[v / 2 for v in town.pixel_size()])
    x_range, y_range = camera.visible_tiles(48)
    assert len(list(x_range)) >= 20 and len(list(y_range)) >= 13


# ----------------------------------------------------------------------- shop
def test_offers_respect_stock_affordability_and_discount():
    wallet = Wallet(gold=10)
    inventory = {"medicine": 2, "bandage": 5}

    offers = build_offers("mira", wallet, inventory)
    medicine = next(o for o in offers if o.item.item_id == "medicine")
    bandage = next(o for o in offers if o.item.item_id == "bandage")
    assert medicine.in_stock and not medicine.affordable      # 24g vs 10g
    assert bandage.affordable

    discounted = build_offers("mira", wallet, inventory, discount=True)
    cheap = next(o for o in discounted if o.item.item_id == "medicine")
    assert cheap.price == price_for(medicine.item, discount=True)
    assert cheap.price < medicine.price
    assert cheap.price == int(round(medicine.item.price * (1 - DISCOUNT_RATE)))


def test_buying_moves_gold_stock_and_items():
    wallet = Wallet(gold=30)
    inventory = {"bandage": 1}
    offer = next(o for o in build_offers("mira", wallet, inventory) if o.item.item_id == "bandage")

    result = buy(offer, wallet, inventory)
    assert result.ok and wallet.gold == 30 - offer.price
    assert wallet.has("bandage") and "bandage" not in inventory


def test_cannot_buy_without_stock_or_coin():
    wallet = Wallet(gold=100)
    empty: dict = {}
    offer = next(o for o in build_offers("mira", wallet, empty) if o.item.item_id == "medicine")
    assert buy(offer, wallet, empty).ok is False

    poor = Wallet(gold=1)
    offer = build_offers("mira", poor, {"medicine": 1})[0]
    assert buy(offer, poor, {"medicine": 1}).ok is False
    assert poor.gold == 1


def test_every_catalogue_item_has_a_vendor_or_is_a_quest_item():
    for item in CATALOGUE:
        assert item.price >= 0
        if item.item_id != "receipt":
            assert item.sold_by, f"{item.item_id} is unbuyable"


# ------------------------------------------------------------------ dialogue
def _ctx() -> GameContext:
    sim = TownSimulation()
    wallet = Wallet(gold=40)
    return GameContext(sim=sim, wallet=wallet)


def test_every_registered_node_builds_lines_and_choices():
    ctx = _ctx()
    for node_id in NODES:
        node = get_node(node_id)
        lines = list(node.lines(ctx))
        assert lines, f"{node_id} produced no lines"
        assert all(isinstance(line, str) for line in lines)
        choices = node.choices(ctx)
        assert choices, f"{node_id} offers no choices"


def test_every_goto_target_exists():
    ctx = _ctx()
    for node_id in NODES:
        for choice in get_node(node_id).choices(ctx):
            if choice.kind == "goto":
                assert choice.target in NODES, f"{node_id} -> unknown node {choice.target}"
            if choice.kind == "effect":
                assert choice.target, f"{node_id} has an effect choice with no target"


def test_all_entry_nodes_exist_for_every_npc():
    for npc_id, node_id in ENTRY_NODES.items():
        assert node_id in NODES
        assert node_id.startswith(npc_id)


def test_mira_refuses_to_sell_while_she_believes_the_accusation():
    ctx = _ctx()
    assert ctx.top_action("mira") == "refuse_trade"
    assert ctx.trade_allowed("mira") is False

    choices = available_choices(ctx, "mira.greet")
    shop = next(c for c in choices if c.kind == "shop")
    assert shop.enabled(ctx) is False
    assert "will not sell" in shop.reason(ctx)


def test_mira_serves_the_player_after_the_accusation_is_revised():
    ctx = _ctx()
    for _ in range(3):
        ctx.sim.advance_day()

    assert ctx.belief("mira", "rohan_stole") is not None
    assert ctx.trade_allowed("mira") is True

    shop = next(c for c in available_choices(ctx, "mira.greet") if c.kind == "shop")
    assert shop.enabled(ctx) is True


def test_dialogue_cites_the_counterfactually_certified_memory():
    ctx = _ctx()
    for _ in range(3):
        ctx.sim.advance_day()

    reasons = ctx.certified_reasons("mira")
    assert reasons and "guard proved" in reasons[0].lower()

    greeted = " ".join(get_node("mira.greet").lines(ctx))
    assert "apolog" in greeted.lower()
    assert "Because it weighed on me" in " ".join(get_node("mira.why").lines(ctx))


def test_why_node_is_honest_when_no_memory_is_responsible():
    ctx = _ctx()
    ctx.sim.store.clear()                      # an NPC with nothing on file
    text = " ".join(get_node("mira.why").lines(ctx))
    assert "weighed on me" not in text


def test_memory_rows_expose_tier_status_and_importance():
    ctx = _ctx()
    for _ in range(3):
        ctx.sim.advance_day()
    rows = memory_rows(ctx, "mira")

    assert rows
    assert all({"summary", "tier", "status", "importance", "confidence", "day"} <= set(r) for r in rows)
    assert any(r["status"] == "superseded" for r in rows), "history should be kept, not erased"
    assert any(r["tier"] == "semantic" for r in rows)


# --------------------------------------------------------------- quest loop
def test_full_quest_loop_from_accusation_to_shop():
    """Play the intended route end to end, through the same code the game runs."""
    ctx = _ctx()

    # 1. Kael explains how a traveller proves innocence.
    assert any(c.target == "ask_arun_hint"
               for c in available_choices(ctx, "kael.how_to_prove"))
    apply_effect(ctx, "ask_arun_hint")
    assert ctx.flags["arun_hint"] is True

    # 2. Arun sells the market copies -> the player gains the receipts.
    assert ctx.wallet.has("receipt") is False
    message = apply_effect(ctx, "arun.buy_ledgers")
    assert ctx.wallet.has("receipt")
    assert ctx.wallet.gold == 35
    assert "receipt" in message.lower() or "roll" in message.lower()

    # 3. Presenting them to Kael revises Mira's belief through the belief updater.
    before = ctx.top_action("mira")
    assert before in {"refuse_trade", "warn_player", "call_guard"}
    apply_effect(ctx, "present_evidence:kael")

    assert ctx.belief("mira", "rohan_stole") is not None
    assert ctx.belief("mira", "player_stole") is None or \
        ctx.belief("mira", "player_stole").status.value != "active"
    assert ctx.top_action("mira") == "apologise"

    # 4. She will now trade, and the counter works.
    assert ctx.trade_allowed("mira") is True
    offer = next(o for o in build_offers("mira", ctx.wallet, ctx.sim.npcs["mira"].inventory)
                 if o.item.item_id == "medicine")
    assert buy(offer, ctx.wallet, ctx.sim.npcs["mira"].inventory).ok
    assert ctx.wallet.has("medicine")

    # 5. The certified cause is the guard's evidence (Kael re-issues it in his
    #    own words when the player presents the receipts), and history is intact.
    cause = ctx.certified_reasons("mira")[0].lower()
    assert "rohan" in cause and ("proved" in cause or "proving" in cause or "confirmed" in cause)
    assert any(r["status"] == "superseded" for r in memory_rows(ctx, "mira"))


def test_rohan_confession_also_resolves_the_case():
    ctx = _ctx()
    apply_effect(ctx, "confront_rohan")
    assert ctx.flags["confessed"] is True
    assert ctx.belief("kael", "rohan_stole") is not None


def test_quest_hint_tracks_progress():
    ctx = _ctx()
    first = quest_hint(ctx)
    assert "Kael" in first
    apply_effect(ctx, "ask_arun_hint")
    assert "Arun" in quest_hint(ctx)
    apply_effect(ctx, "arun.buy_ledgers")
    assert "receipts" in quest_hint(ctx).lower()
    apply_effect(ctx, "present_evidence:kael")
    assert "Mira" in quest_hint(ctx)


# ------------------------------------------------------------------- smoke
def test_headless_render_smoke(tmp_path):
    pygame = pytest.importorskip("pygame", reason="game extra not installed")
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from npc_memory_project.game.app import TILE_PX, Game

    game = Game(headless=True)
    game.update(0.016)
    game.render()
    out = tmp_path / "world.png"
    # the presented window, which is what a player sees: the world pass plus the
    # native-resolution UI pass drawn over it
    pygame.image.save(game.display.window, str(out))
    assert out.exists() and out.stat().st_size > 2000
    assert game.display.window.get_size() == (960, 640)

    # the real movement path, with float coordinates, must not raise
    start = (game.player.x, game.player.y)
    moved_x, moved_y = game.try_move(0, -6)
    assert (game.player.x, game.player.y) != start
    game.camera.centre_on(*game.player.centre)

    # pushing into a solid tile for many frames must not tunnel through it
    game.player.x, game.player.y = game._tile_to_px(4, 11)      # below the apothecary
    for _ in range(120):
        game.try_move(0, -3)
    assert game.town.get(
        int((game.player.foot_rect()[0]) // TILE_PX),
        int((game.player.foot_rect()[1]) // TILE_PX),
    ) not in BLOCKING_TILES

    # every scene renders without raising
    game.open_dialogue("mira")
    game.render()
    game.page_index = len(game.pages) - 1
    game.revealed = float(len(game.page_text))
    game.render()
    for scene in ("shop", "memory", "help", "day"):
        game.scene = scene
        game.render()
    pygame.quit()


def test_ui_pass_draws_readable_text_at_any_window_size(tmp_path):
    """The regression this test exists for: the inspector must stay legible.

    The UI used to be part of the scaled logical frame, so on a 1400x933 window a
    13 px label was resampled by 1.46 and turned to mush. The two-pass renderer
    draws the UI at the window's own resolution, so here we assert the properties
    that fix actually buys:

    * the font a given logical size resolves to grows with the window, and
    * text keeps roughly its share of the window height (it never gets *smaller*
      relative to the window), and
    * full-screen panels span past the letterboxed frame and use the whole window.
    """
    pygame = pytest.importorskip("pygame", reason="game extra not installed")
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from npc_memory_project.game.app import Game
    from npc_memory_project.game.ui import window_canvas

    fonts = {}
    shares = {}
    spans = {}
    for size in ((960, 640), (1400, 933), (1920, 1080)):
        game = Game(headless=True, window_size=size)
        game.scene = "memory"
        game.render()

        canvas = window_canvas(game.display)
        # a 15 px label is drawn with a 15 x factor px font, never scaled afterwards
        assert canvas.font_size(15) == max(9, round(15 * canvas.factor))
        fonts[size] = canvas.font_size(15)
        shares[size] = fonts[size] / size[1]
        spans[size] = canvas.span_w
        pygame.quit()

    assert fonts[(960, 640)] < fonts[(1400, 933)] < fonts[(1920, 1080)]
    # constant share of the window, not a collapsing one
    assert all(0.020 < share < 0.026 for share in shares.values())
    # the inspector is laid out over the whole surface, letterbox bars included
    assert spans[(1920, 1080)] > 960
    assert spans[(960, 640)] == 960
