"""The playable game: movement, dialogue, shopping, day cycle, inspector.

Run it with::

    npc-memory-game                 # or: python -m npc_memory_project.game.app
    npc-memory-game --screenshot out.png --scene dialogue

``--screenshot`` renders a single frame headlessly and exits, which is how the
game is smoke-tested in CI without a display.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from npc_memory_project.game.assets import CHAR_H, CHAR_W, SCALE, TILE_PX, SpriteFactory
from npc_memory_project.game.display import Display
from npc_memory_project.game.ui import UiCanvas, window_canvas
from npc_memory_project.game.conversation import (
    Choice, GameContext, apply_effect, available_choices, entry_node, get_node,
    memory_rows, quest_hint,
)
from npc_memory_project.game.renderer import DialogueView, Renderer, ShopView
from npc_memory_project.game.shop import DISCOUNT_RATE, Wallet, build_offers, buy
from npc_memory_project.game.world_map import Camera, Tile, TownMap, build_town, move_with_collision
from npc_memory_project.simulation.town_simulation import TownSimulation

WINDOW = (960, 640)
FPS = 60
WALK_SPEED = 2.6               # world pixels per frame
TYPE_SPEED = 58.0              # characters per second in the dialogue box
INTERACT_RANGE = 86.0          # pixels between character centres
SPAWN_TILE = (19, 20)

DIRECTION_KEYS = {
    pygame.K_w: "up", pygame.K_UP: "up",
    pygame.K_s: "down", pygame.K_DOWN: "down",
    pygame.K_a: "left", pygame.K_LEFT: "left",
    pygame.K_d: "right", pygame.K_RIGHT: "right",
}


@dataclass
class Entity:
    sprite_id: str
    x: float
    y: float
    w: int = CHAR_W * SCALE
    h: int = CHAR_H * SCALE
    facing: str = "down"
    frame: int = 0
    label: str = ""
    npc_id: str = ""
    moving: bool = False
    anim_timer: float = 0.0

    @property
    def centre(self) -> Tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def foot_rect(self) -> Tuple[float, float, float, float]:
        """Small box at the feet used for collision."""
        return self.x + 8, self.y + self.h - 18, self.w - 16, 16


class Game:
    """Scene manager and main loop."""

    def __init__(self, headless: bool = False, *, scale: float = 1.0,
                 fullscreen: bool = False,
                 window_size: Optional[Tuple[int, int]] = None) -> None:
        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        self.display = Display(logical_size=WINDOW, scale=scale, fullscreen=fullscreen,
                               window_size=window_size)
        self.screen = self.display.logical        # everything is drawn here
        self.clock = pygame.time.Clock()

        self.sim = TownSimulation()
        # tile_size must match the rendering scale, or Camera.clamp() thinks the
        # map is smaller than the viewport and pins the view to the corner
        self.town: TownMap = build_town(tile_size=TILE_PX)
        self.sprites = SpriteFactory()
        self.renderer = Renderer(
            self.screen, self.sprites,
            ui=UiCanvas.for_logical(self.screen, logical_size=WINDOW),
        )
        self.camera = Camera(WINDOW, self.town.pixel_size())
        self.wallet = Wallet(gold=40)
        self.ctx = GameContext(sim=self.sim, wallet=self.wallet)

        self.player = Entity("player", *self._tile_to_px(*SPAWN_TILE), facing="down", label="You")
        self.npcs: Dict[str, Entity] = {}
        for npc_id, post in self.town.posts.items():
            entity = Entity(npc_id, *self._tile_to_px(*post.tile), facing=post.facing,
                            label=post.label, npc_id=npc_id)
            self.npcs[npc_id] = entity

        self.scene = "world"
        self.running = True
        self.toast = ""
        self.toast_timer = 0.0

        # dialogue state
        self.active_npc: Optional[str] = None
        self.node_id = ""
        self.pages: List[str] = []
        self.page_index = 0
        self.revealed = 0.0
        self.choices: List[Choice] = []
        self.selected = 0
        self.scroll = 0
        self.certified_reason = ""
        self.dialogue_source = "deterministic"

        # shop state
        self.shop_message = ""

        # day overlay
        self.day_entries: List[str] = []

        self.camera.centre_on(*self.player.centre)

    # -------------------------------------------------------------- helpers
    def _tile_to_px(self, tx: int, ty: int) -> Tuple[float, float]:
        return (tx * TILE_PX + (TILE_PX - CHAR_W * SCALE) / 2,
                ty * TILE_PX + (TILE_PX - CHAR_H * SCALE) / 2)

    def _distance_to(self, entity: Entity) -> float:
        px, py = self.player.centre
        ex, ey = entity.centre
        return ((px - ex) ** 2 + (py - ey) ** 2) ** 0.5

    def nearest_npc(self) -> Optional[Entity]:
        candidates = [(self._distance_to(e), e) for e in self.npcs.values()]
        if not candidates:
            return None
        distance, entity = min(candidates, key=lambda pair: pair[0])
        return entity if distance <= INTERACT_RANGE else None

    def notify(self, message: str) -> None:
        self.toast = message
        self.toast_timer = 3.0

    # ------------------------------------------------------------- dialogue
    def open_dialogue(self, npc_id: str) -> None:
        self.active_npc = npc_id
        self.scene = "dialogue"
        self._enter_node(entry_node(npc_id))

    def _enter_node(self, node_id: str) -> None:
        assert self.active_npc
        self.node_id = node_id
        node = get_node(node_id)
        self.pages = list(node.lines(self.ctx))
        self.page_index = 0
        self.revealed = 0.0
        self.choices = available_choices(self.ctx, node_id)
        self.selected = 0
        self.scroll = 0

        # ground the speaker line in the certified cause, when there is one
        reasons = self.ctx.certified_reasons(self.active_npc)
        self.certified_reason = reasons[0] if reasons else ""
        self.dialogue_source = "deterministic"

    @property
    def page_text(self) -> str:
        if not self.pages:
            return ""
        return self.pages[min(self.page_index, len(self.pages) - 1)]

    def page_done(self) -> bool:
        return self.revealed >= len(self.page_text)

    def last_page(self) -> bool:
        return self.page_index >= len(self.pages) - 1

    def advance_dialogue(self) -> None:
        if not self.page_done():
            self.revealed = float(len(self.page_text))
        elif not self.last_page():
            self.page_index += 1
            self.revealed = 0.0
        # otherwise the choice list is already showing

    def move_selection(self, delta: int) -> None:
        if not self.choices:
            return
        self.selected = (self.selected + delta) % len(self.choices)
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + 5:
            self.scroll = self.selected - 4

    def activate_choice(self, index: int) -> None:
        if not (0 <= index < len(self.choices)):
            return
        choice = self.choices[index]
        if not choice.enabled(self.ctx):
            self.notify(choice.reason(self.ctx) or "That is not possible right now.")
            return

        assert self.active_npc
        if choice.kind == "goto":
            self._enter_node(choice.target)
        elif choice.kind == "shop":
            self.scene = "shop"
            self.shop_message = ""
        elif choice.kind == "effect":
            message = apply_effect(self.ctx, choice.target)
            self.notify(message)
            # return to the speaker so their reaction reflects the new state
            self._enter_node(entry_node(self.active_npc))
            self.revealed = 0.0
        elif choice.kind == "close":
            self.close_dialogue()

    def close_dialogue(self) -> None:
        self.scene = "world"
        self.active_npc = None

    # ----------------------------------------------------------------- shop
    def shop_offers(self):
        assert self.active_npc
        npc = self.sim.npcs[self.active_npc]
        discount = self.ctx.top_action(self.active_npc) == "offer_discount"
        return build_offers(self.active_npc, self.wallet, npc.inventory, discount=discount)

    def shop_purchase(self, index: int) -> None:
        offers = self.shop_offers()
        if not (0 <= index < len(offers)):
            return
        offer = offers[index]
        result = buy(offer, self.wallet, self.sim.npcs[self.active_npc].inventory)
        self.shop_message = result.message
        if result.ok:
            self.ctx.tell(result.message)
            if offer.item.item_id == "rumour":
                # a rumour is not stock -- it is the vendor's own top memory
                self.shop_message = f'"{self.ctx.recall(self.active_npc)}"'
                self.ctx.tell("Bought a rumour from Arun.")

    # ------------------------------------------------------------- day cycle
    def advance_day(self) -> None:
        before = len(self.sim.event_log)
        self.sim.advance_day()
        self.day_entries = [entry["text"] for entry in self.sim.event_log[before:]]
        self.scene = "day"

    # ------------------------------------------------------------- keyboard
    def handle_world_key(self, event: pygame.event.Event) -> None:
        if event.key in (pygame.K_e, pygame.K_SPACE, pygame.K_RETURN):
            target = self.nearest_npc()
            if target:
                self.open_dialogue(target.npc_id)
        elif event.key == pygame.K_n:
            self.advance_day()
        elif event.key in (pygame.K_j, pygame.K_TAB):
            self.scene = "memory"
        elif event.key == pygame.K_F1:
            self.scene = "help"
        elif event.key == pygame.K_ESCAPE:
            self.running = False

    def handle_dialogue_key(self, event: pygame.event.Event) -> None:
        if self.page_done() and self.last_page():
            if event.key in (pygame.K_UP, pygame.K_w):
                self.move_selection(-1)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.move_selection(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_e):
                self.activate_choice(self.selected)
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.activate_choice(event.key - pygame.K_1)
            elif event.key == pygame.K_ESCAPE:
                self.close_dialogue()
        else:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_e, pygame.K_DOWN):
                self.advance_dialogue()
            elif event.key == pygame.K_ESCAPE:
                self.close_dialogue()

    def handle_shop_key(self, event: pygame.event.Event) -> None:
        offers = self.shop_offers()
        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected = (self.selected - 1) % max(1, len(offers))
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected = (self.selected + 1) % max(1, len(offers))
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_e):
            self.shop_purchase(self.selected)
        elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.scene = "dialogue"
        elif pygame.K_1 <= event.key <= pygame.K_9:
            self.shop_purchase(event.key - pygame.K_1)

    # --------------------------------------------------------------- update
    def update(self, dt: float) -> None:
        if self.toast_timer > 0:
            self.toast_timer = max(0.0, self.toast_timer - dt)

        for npc in self.npcs.values():                      # gentle idle bob
            npc.anim_timer += dt
            if npc.anim_timer > 0.45:
                npc.anim_timer = 0.0
                npc.frame = (npc.frame + 1) % 2

        if self.scene != "world":
            if self.scene == "dialogue":
                if not self.page_done():
                    self.revealed = min(len(self.page_text), self.revealed + TYPE_SPEED * dt)
            return

        keys = pygame.key.get_pressed()
        dx = dy = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= WALK_SPEED
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += WALK_SPEED
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= WALK_SPEED
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += WALK_SPEED

        moving = dx != 0 or dy != 0
        if moving:
            self.try_move(dx, dy)
            self.player.anim_timer += dt
            if self.player.anim_timer > 0.16:
                self.player.anim_timer = 0.0
                self.player.frame = (self.player.frame + 1) % 2
        else:
            self.player.frame = 0

        self.player.moving = moving
        self.camera.centre_on(*self.player.centre)

    def try_move(self, dx: float, dy: float) -> Tuple[float, float]:
        """Move the player, respecting tiles and other characters. Returns the delta."""
        if dx or dy:
            if abs(dx) >= abs(dy):
                self.player.facing = "right" if dx > 0 else "left"
            else:
                self.player.facing = "down" if dy > 0 else "up"

        before = (self.player.x, self.player.y)
        x, y, w, h = self.player.foot_rect()
        nx, ny = move_with_collision(self.town, (x, y, w, h), dx, dy)
        self.player.x += nx - x
        self.player.y += ny - y

        for npc in self.npcs.values():                     # do not walk through people
            if self._distance_to(npc) < 40 and self._is_blocked_toward(npc, before):
                self.player.x, self.player.y = before
                break

        return self.player.x - before[0], self.player.y - before[1]

    def _is_blocked_toward(self, npc: Entity, before: Tuple[float, float]) -> bool:
        """True when this step moved the player *closer* to the NPC."""
        px, py = self.player.centre
        ex, ey = npc.centre
        was = ((before[0] + self.player.w / 2 - ex) ** 2
               + (before[1] + self.player.h / 2 - ey) ** 2)
        now = (px - ex) ** 2 + (py - ey) ** 2
        return now < was

    # ----------------------------------------------------------------- draw
    def render(self) -> None:
        """One frame, in two passes.

        The world is drawn to the logical surface and scaled into the window; then
        the window is presented; then the UI is drawn *on top of the presented
        window* at its real resolution. Text is therefore never resampled, which
        is what made the inspector unreadable on a resized window.
        """
        self.draw_world()
        self.display.present(flip=False)
        self.renderer.attach_ui(window_canvas(self.display))
        self.draw_ui()
        pygame.display.flip()

    def draw_world(self) -> None:
        self.screen.fill((24, 26, 34))
        self.renderer.draw_world(self.town, self.camera, self.player,
                                 list(self.npcs.values()))

    def draw_ui(self) -> None:
        """Pass 2. Everything here is text or a panel, so it stays crisp."""
        target = self.nearest_npc()
        prompt = "E  talk" if target and self.scene == "world" else None
        prompt_at = (target.x + target.w / 2, target.y - 6) if target else (0, 0)

        self.renderer.draw_world_labels(self.camera, list(self.npcs.values()),
                                        self.player, prompt, prompt_at)

        self.renderer.draw_hud(
            day=self.sim.world.game_day,
            gold=self.wallet.gold,
            item_count=self.wallet.total_items(),
            quest_hint=quest_hint(self.ctx),
            npc_name=self.active_npc.capitalize() if self.active_npc else "",
        )

        if self.scene == "dialogue":
            self.renderer.draw_dialogue(self._dialogue_view())
        elif self.scene == "shop":
            self.renderer.draw_shop(self._shop_view())
        elif self.scene == "memory":
            panels = {npc_id: memory_rows(self.ctx, npc_id) for npc_id in self.npcs}
            reasons = {npc_id: self.ctx.certified_reasons(npc_id) for npc_id in self.npcs}
            self.renderer.draw_memory_panel(panels, reasons, quest_hint(self.ctx))
        elif self.scene == "day":
            self.renderer.draw_day_overlay(self.sim.world.game_day, self.day_entries)
        elif self.scene == "help":
            self.renderer.draw_help()

        if self.toast_timer > 0 and self.scene in {"world", "dialogue", "shop"}:
            self.renderer.draw_toast(self.toast)

    @staticmethod
    def width_centre(surface: pygame.Surface) -> int:
        return (WINDOW[0] - surface.get_width()) // 2

    def _dialogue_view(self) -> DialogueView:
        from npc_memory_project.game.assets import wrap_text

        name = self.active_npc.capitalize() if self.active_npc else ""
        text = self.page_text
        shown = text[: int(self.revealed)]
        wrapped = self.renderer.ui.wrap(shown or " ", 21, self.renderer.width - 220)
        show_choices = self.page_done() and self.last_page()

        rows: List[Dict[str, object]] = []
        if show_choices:
            for choice in self.choices:
                rows.append({
                    "label": choice.label,
                    "enabled": choice.enabled(self.ctx),
                    "reason": choice.reason(self.ctx) if not choice.enabled(self.ctx) else "",
                })

        return DialogueView(
            speaker=self.active_npc or "player",
            label=name,
            page_lines=wrapped,
            revealed=len(shown),
            total_chars=len(text),
            page_done=self.page_done(),
            show_choices=show_choices,
            choices=rows,
            selected=self.selected,
            scroll=self.scroll,
            certified_reason=self.certified_reason,
            dialogue_source=self.dialogue_source,
        )

    def _shop_view(self) -> ShopView:
        offers = self.shop_offers()
        rows = [{
            "name": offer.item.name,
            "description": offer.item.description,
            "price": f"{offer.price}",
            "available": offer.available,
            "in_stock": offer.in_stock,
        } for offer in offers]
        name = self.active_npc.capitalize() if self.active_npc else ""
        return ShopView(
            vendor=self.active_npc or "",
            label=name,
            rows=rows,
            selected=min(self.selected, max(0, len(rows) - 1)),
            message=self.shop_message,
            gold=self.wallet.gold,
            discount=bool(offers and offers[0].discounted),
        )

    # ----------------------------------------------------------------- loop
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type == pygame.VIDEORESIZE:
            self.display.resize((event.w, event.h))
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.display.toggle_fullscreen()
            if not self.display.fullscreen_supported:
                self.notify("Fullscreen is unavailable in this environment.")
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F10:
            factor = self.display.cycle_window_scale()
            self.notify(f"Window scale {factor:g}x")
            return

        if event.type != pygame.KEYDOWN and event.type != pygame.MOUSEBUTTONDOWN:
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse = self.display.to_logical(event.pos)
            if self.scene == "dialogue":
                if self.page_done() and self.last_page():
                    for index, rect in enumerate(self.renderer.choice_rects):
                        if rect.collidepoint(mouse):
                            if index == self.selected:
                                self.activate_choice(index)
                            else:
                                self.selected = index
                            return
                    self.advance_dialogue()
                else:
                    self.advance_dialogue()
            elif self.scene == "shop":
                for index, rect in enumerate(self.renderer.choice_rects):
                    if rect.collidepoint(mouse):
                        self.selected = index
                        self.shop_purchase(index)
                        return
            return

        if event.key == pygame.K_ESCAPE and self.scene in {"memory", "help"}:
            self.scene = "world"
            return
        if self.scene == "world":
            self.handle_world_key(event)
        elif self.scene == "dialogue":
            self.handle_dialogue_key(event)
        elif self.scene == "shop":
            self.handle_shop_key(event)
        elif self.scene in {"day", "memory", "help"}:
            if event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_n, pygame.K_j):
                self.scene = "world"

    def run(self, max_frames: Optional[int] = None) -> None:
        frames = 0
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.render()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        pygame.quit()


# ------------------------------------------------------------------ CLI
def _prepare_scene(game: Game, scene: str, day: Optional[int] = None) -> None:
    """Set up a deterministic state for screenshotting.

    ``day`` overrides the scene's default (which is "far enough in for the case to
    be resolved"): ``--day 1`` captures the town before the exoneration, which is
    how the refusal screenshot is made without hand-editing state.
    """
    if day is None and scene in {"dialogue", "day3", "shop", "memory"}:
        for _ in range(3):
            game.sim.advance_day()
    elif day == 1:
        pass                                   # day 1 is the opening state
    elif day is not None:
        while game.sim.world.game_day < day:
            game.sim.advance_day()

    if scene == "dialogue":
        game.open_dialogue("mira")
        # skip past the typewriter so the screenshot shows text and choices
        game.page_index = len(game.pages) - 1
        game.revealed = float(len(game.page_text))
    elif scene == "day3":
        game.day_entries = ["Officer Kael verified Rohan was the thief. Mira revised her beliefs (Day 3)."]
        game.scene = "day"
    elif scene == "shop":
        game.open_dialogue("arun")
        game.scene = "shop"
    elif scene == "memory":
        game.scene = "memory"
    elif scene == "help":
        game.scene = "help"
    elif scene == "world":
        game.scene = "world"
    game.update(0.016)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ashfen — playable SHM-NPC town")
    parser.add_argument("--screenshot", metavar="PATH",
                        help="render one frame to PATH and exit (no display needed)")
    parser.add_argument("--scene", default="world",
                        choices=["world", "dialogue", "shop", "memory", "help", "day3"])
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--scale", type=float, default=1.0,
                        help="initial window scale (1.0 = 960x640; 2.0 = 1920x1280)")
    parser.add_argument("--window", metavar="WxH", default=None,
                        help="explicit initial window size, e.g. 1600x900")
    parser.add_argument("--fullscreen", action="store_true",
                        help="start fullscreen (F11 toggles at runtime)")
    parser.add_argument("--day", type=int, default=None,
                        help="with --screenshot: advance to this day first "
                             "(--day 1 shows the town before the resolution)")
    parser.add_argument("--capture-window", action="store_true",
                        help="deprecated: --screenshot always saves the presented "
                             "window now (identical to the logical frame at 1x)")
    args = parser.parse_args(argv)

    scale = args.scale
    window_size = None
    if args.window:
        try:
            width, height = (int(part) for part in args.window.lower().split("x"))
        except ValueError:
            parser.error("--window must look like 1600x900")
        window_size = (width, height)

    if args.screenshot:
        game = Game(headless=True, scale=scale, fullscreen=args.fullscreen,
                    window_size=window_size)
        _prepare_scene(game, args.scene, args.day)
        game.render()
        # always the presented window: at scale 1.0 that is the 960x640 logical
        # frame, larger sizes get the same frame with its crisp UI pass on top
        target = game.display.window
        pygame.image.save(target, args.screenshot)
        print(f"screenshot written to {args.screenshot} "
              f"({target.get_width()}x{target.get_height()}, scene={args.scene}, "
              f"day={game.sim.world.game_day})")
        pygame.quit()
        return 0

    game = Game(scale=scale, fullscreen=args.fullscreen, window_size=window_size)
    print(
        "Ashfen is open.\n"
        "  WASD/arrows walk   E talk   N next day   J memory   F1 help\n"
        "  F11 fullscreen     F10 cycle window size   ESC quit"
    )
    game.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
