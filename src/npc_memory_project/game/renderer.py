"""Rendering, in two passes: the pixel world, then a native-resolution UI.

**Pass 1 -- world.** Tiles, characters and shadows are drawn to the logical
960x640 surface and scaled into the window. Blocky on purpose; that is what pixel
art is supposed to do.

**Pass 2 -- UI.** Every piece of text, every panel, drawn straight onto the window
after presenting, at the window's real resolution (see ``game/ui.py``). Text is
never resampled, so it stays sharp when the window is resized or fullscreen. This
is the fix for the memory inspector being unreadable at 1.46x: the panel used to
be part of the scaled frame, so a 13 px font went through a resample and turned to
mush.

The dialogue box keeps its Genshin shape -- portrait plate, name label, typewritten
body, numbered replies -- with the counterfactually certified reason shown as its
own tag, so the research claim is visible in-game rather than only in a paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from npc_memory_project.game.assets import (
    CHAR_H, CHAR_W, SCALE, TILE_PX, SpriteFactory,
)
from npc_memory_project.game.ui import UiCanvas
from npc_memory_project.game.world_map import Tile, TownMap

# ------------------------------------------------------------------ palette
INK = (22, 20, 30)
PANEL = (28, 26, 40, 238)
PANEL_EDGE = (96, 92, 130)
TEXT = (238, 236, 246)
MUTED = (154, 152, 176)
ACCENT = (120, 214, 140)
WARN = (246, 172, 92)
DANGER = (232, 108, 108)
GOLD = (246, 208, 110)
HIGHLIGHT = (70, 62, 106, 230)

TIER_COLORS = {
    "working": (150, 148, 176),
    "episodic": (110, 172, 232),
    "semantic": (168, 134, 226),
    "archive": (120, 116, 132),
}
STATUS_COLORS = {
    "active": ACCENT,
    "corroborated": (120, 214, 200),
    "disputed": WARN,
    "resolved": ACCENT,
    "superseded": MUTED,
    "expired": (110, 106, 124),
}


@dataclass
class DialogueView:
    speaker: str
    label: str
    page_lines: List[str]          # already wrapped, ready to draw
    revealed: int                  # characters revealed so far (typewriter)
    total_chars: int
    page_done: bool
    show_choices: bool
    choices: List[Dict[str, object]] = field(default_factory=list)
    selected: int = 0
    certified_reason: str = ""
    dialogue_source: str = "deterministic"
    scroll: int = 0


@dataclass
class ShopView:
    vendor: str
    label: str
    rows: List[Dict[str, object]]
    selected: int = 0
    message: str = ""
    gold: int = 0
    discount: bool = False


class Renderer:
    def __init__(self, screen: pygame.Surface, sprites: SpriteFactory,
                 ui: Optional[UiCanvas] = None) -> None:
        self.screen = screen
        self.sprites = sprites
        self.width, self.height = screen.get_size()
        #: Pass-2 canvas. Logical by default (used for the 1x captures) and
        #: swapped for a window-bound canvas every frame by ``Game.render``.
        self.ui = ui if ui is not None else UiCanvas.for_logical(
            screen, logical_size=(self.width, self.height))
        self.choice_rects: List[pygame.Rect] = []

    def attach_ui(self, ui: UiCanvas) -> None:
        """Point the UI pass at a canvas (logical or window-resolution)."""
        self.ui = ui

    # ------------------------------------------------------------- world
    def draw_world(self, town: TownMap, camera, player: "Entity",
                   npcs: Sequence["Entity"]) -> None:
        x_range, y_range = camera.visible_tiles(TILE_PX)

        # ground pass
        for ty in y_range:
            for tx in x_range:
                tile = town.get(tx, ty)
                ground = self.sprites.ground(tile)
                sx, sy = camera.world_to_screen(tx * TILE_PX, ty * TILE_PX)
                if ground is not None:
                    self.screen.blit(ground, (sx, sy))
                else:
                    # objects sit on grass
                    self.screen.blit(self.sprites.ground(Tile.GRASS), (sx, sy))

        # depth-sorted pass: tall objects and characters share a y ordering
        drawables: List[Tuple[float, str, object]] = []
        for ty in y_range:
            for tx in x_range:
                obj = self.sprites.object_surface(town.get(tx, ty))
                if obj is not None:
                    drawables.append((ty * TILE_PX + TILE_PX, "tile", (tx, ty, obj)))
        for entity in list(npcs) + [player]:
            drawables.append((entity.y + entity.h, "entity", entity))
        drawables.sort(key=lambda item: item[0])

        for _, kind, payload in drawables:
            if kind == "tile":
                tx, ty, obj = payload            # type: ignore[misc]
                sx, sy = camera.world_to_screen(tx * TILE_PX, ty * TILE_PX)
                self.screen.blit(obj, (sx, sy))
            else:
                self._draw_entity(payload, camera)   # type: ignore[arg-type]

    def _draw_entity(self, entity: "Entity", camera) -> None:
        sx, sy = camera.world_to_screen(entity.x, entity.y)
        shadow = pygame.Surface((entity.w, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 70), shadow.get_rect())
        self.screen.blit(shadow, (sx, sy + entity.h - 6))
        sprite = self.sprites.character(entity.sprite_id, entity.facing, entity.frame)
        self.screen.blit(sprite, (sx, sy))

    def draw_world_labels(self, camera, npcs: Sequence["Entity"], player: "Entity",
                          prompt: Optional[str] = None,
                          prompt_at: Tuple[float, float] = (0, 0)) -> None:
        """Name plates and the ``E talk`` prompt, drawn in the UI pass.

        They follow entities in the world, but they are *text*, so they belong to
        the crisp pass: at 2x a name rendered into the scaled frame is a blocky
        smear, and this is the one label the player looks at while walking.
        """
        for entity in list(npcs) + [player]:
            if not entity.label:
                continue
            sx, sy = camera.world_to_screen(entity.x, entity.y)
            surface = self.ui.text(entity.label, 14, TEXT, bold=True)
            width = self.ui.measure(entity.label, 14, bold=True)
            height = surface.get_height() / self.ui.factor
            plate_w, plate_h = width + 8, height + 4
            plate_x = sx + entity.w / 2 - plate_w / 2
            plate_y = sy - plate_h - 2
            self.ui.fill((18, 16, 26, 170), (plate_x, plate_y, plate_w, plate_h))
            self.ui.blit_center(surface, sx + entity.w / 2, plate_y + 2)

        if prompt:
            self._draw_prompt(prompt, prompt_at, camera)

    def _draw_prompt(self, text: str, at: Tuple[float, float], camera) -> None:
        sx, sy = camera.world_to_screen(*at)
        surface = self.ui.text(text, 16, INK, bold=True)
        width = self.ui.measure(text, 16, bold=True)
        height = surface.get_height() / self.ui.factor
        box_w, box_h = width + 14, height + 10
        box_x = sx - box_w / 2
        box_y = sy - box_h
        self.ui.panel((box_x, box_y, box_w, box_h), (246, 240, 210, 240),
                      INK, width=2, radius=6)
        self.ui.blit(surface, (box_x + 7, box_y + 5))

    # --------------------------------------------------------------- HUD
    def draw_hud(self, day: int, gold: int, item_count: int, quest_hint: str,
                 npc_name: str = "", interacting: bool = False) -> None:
        ui = self.ui
        ui.fill_row((16, 14, 24, 190), 0, 40)

        left = ui.origin_x
        right = ui.origin_x + ui.span_w
        ui.blit(ui.text(f"DAY {day}", 21, GOLD, bold=True), (left + 16, 10))
        ui.blit(ui.text(f"{gold} GOLD", 19, GOLD), (left + 150, 11))
        ui.blit(ui.text(f"{item_count} ITEMS", 19, MUTED), (left + 300, 11))

        # quest hint, right aligned, clipped with an ellipsis if it would collide
        limit = max(240, ui.span_w - 660)
        hint = quest_hint
        while ui.measure(hint, 16) > limit and len(hint) > 8:
            hint = hint[:-1]
        if hint != quest_hint:
            hint = hint.rstrip() + "…"
        ui.text_right(hint, 16, TEXT, right - 16, 13)

        ui.fill_row((16, 14, 24, 170), ui.origin_y + ui.span_h - 24, 24)
        ui.blit(ui.text("WASD move   E talk   N next day   J memory   F1 help", 14, MUTED),
                (left + 16, ui.origin_y + ui.span_h - 20))

        if npc_name:
            ui.text_right(npc_name, 16, ACCENT, right - 16, 44, bold=True)

    # ---------------------------------------------------------- dialogue
    def draw_dialogue(self, view: DialogueView) -> None:
        ui = self.ui
        box_h = 336
        box = pygame.Rect(24, self.height - box_h - 30, self.width - 48, box_h)
        ui.panel(box, PANEL, PANEL_EDGE, width=3, radius=10)

        # portrait plate
        portrait_box = pygame.Rect(box.x + 16, box.y + 16, 132, 150)
        ui.panel(portrait_box, (20, 18, 30), PANEL_EDGE, width=2, radius=8)
        face = self.sprites.portrait(view.speaker, 116)
        ui.sprite(face, (portrait_box.x + 8, portrait_box.y + 10), logical_size=116)

        name = ui.text(view.label.upper(), 21, ACCENT, bold=True)
        name_w = ui.measure(view.label.upper(), 21, bold=True)
        plate = pygame.Rect(box.x + 16, portrait_box.bottom + 8,
                            max(name_w + 20, 132), 32)
        ui.panel(plate, (34, 30, 48), PANEL_EDGE, width=2, radius=6)
        ui.blit(name, (plate.x + 10, plate.y + 6))

        text_x = box.x + 172
        text_w = box.right - text_x - 24

        # certified causal reason tag -- its own line, above the speech
        if view.certified_reason:
            tag_y = box.y + 12
            for line in ui.wrap("CAUSAL CAUSE CERTIFIED BY ABLATION:  " + view.certified_reason,
                                14, text_w)[:2]:
                ui.blit(ui.text(line, 14, WARN), (text_x, tag_y))
                tag_y += 18

        if view.dialogue_source == "llm_rejected":
            ui.blit(ui.text("UNGROUNDED LLM LINE REJECTED", 14, DANGER), (text_x, box.y + 52))

        # body text with the typewriter cut
        line_height = 30
        budget = max(view.revealed, 0)
        consumed = 0
        y = box.y + 52
        for line in view.page_lines:
            visible = line
            if consumed + len(line) > budget:
                visible = line[: max(0, budget - consumed)]
            if visible:
                ui.blit(ui.text(visible, 21, TEXT), (text_x, y))
            consumed += len(line) + 1
            y += line_height
            if y > box.y + 148:
                break

        # choices
        self.choice_rects = []
        if not view.show_choices:
            ui.text_right("SPACE / ENTER to continue", 15, MUTED,
                          box.right - 24, box.bottom - 32)
            return

        list_y = box.y + 150
        visible_choices = view.choices[view.scroll: view.scroll + 6]
        for row, choice in enumerate(visible_choices):
            index = view.scroll + row
            enabled = bool(choice.get("enabled", True))
            selected = index == view.selected
            row_rect = pygame.Rect(box.x + 168, list_y + row * 28, box.right - box.x - 192, 26)
            self.choice_rects.append(row_rect)

            if selected:
                ui.fill(HIGHLIGHT, row_rect)
                ui.rect(PANEL_EDGE, row_rect, 2, radius=6)

            color = TEXT if enabled else (108, 104, 124)
            # a drawn cursor, not a glyph: the default font has no U+25B6 and
            # rendered a tofu box instead
            if selected:
                ui.triangle(ACCENT, (
                    (row_rect.x + 8, row_rect.y + 8),
                    (row_rect.x + 8, row_rect.y + 18),
                    (row_rect.x + 16, row_rect.y + 13),
                ))
            ui.blit(ui.text(f"{row + 1}. {choice.get('label', '')}", 18, color, bold=selected),
                    (row_rect.x + 22, row_rect.y + 5))

            if not enabled and choice.get("reason"):
                reason = str(choice["reason"])
                right_x = row_rect.right - 10
                room = int((row_rect.right - row_rect.x) * 0.55)
                while ui.measure(reason, 13) > room and len(reason) > 4:
                    reason = reason[:-1]
                ui.text_right(reason, 13, (140, 132, 128), right_x, row_rect.y + 7)

        remaining = len(view.choices) - view.scroll - 6
        if remaining > 0:
            ui.triangle(MUTED, (
                (box.x + 176, list_y + 6 * 28 + 4),
                (box.x + 186, list_y + 6 * 28 + 4),
                (box.x + 181, list_y + 6 * 28 + 11),
            ))
            ui.blit(ui.text(f"{remaining} more", 14, MUTED), (box.x + 192, list_y + 6 * 28 + 2))

    # -------------------------------------------------------------- shop
    def draw_shop(self, view: ShopView) -> None:
        ui = self.ui
        panel_w, panel_h = 620, 400
        px = (self.width - panel_w) // 2
        py = (self.height - panel_h) // 2 - 40
        ui.panel((px, py, panel_w, panel_h), PANEL, PANEL_EDGE, width=3, radius=10)

        ui.blit(ui.text(f"{view.label}  —  Goods", 23, ACCENT, bold=True), (px + 24, py + 18))
        ui.text_right(f"{view.gold} gold", 19, GOLD, px + panel_w - 24, py + 22)
        if view.discount:
            ui.text_right("favour: 25% off", 15, ACCENT, px + panel_w - 24, py + 50)

        self.choice_rects = []
        for index, row in enumerate(view.rows):
            y = py + 80 + index * 52
            rect = pygame.Rect(px + 20, y, panel_w - 40, 46)
            self.choice_rects.append(rect)
            if index == view.selected:
                ui.fill(HIGHLIGHT, rect)
                ui.rect(PANEL_EDGE, rect, 2, radius=8)

            available = bool(row.get("available"))
            color = TEXT if available else (116, 112, 132)
            ui.blit(ui.text(str(row["name"]), 19, color, bold=index == view.selected),
                    (rect.x + 14, rect.y + 5))
            ui.blit(ui.text(str(row["description"]), 14, MUTED), (rect.x + 14, rect.y + 27))

            price = f"{row['price']}g"
            price_color = GOLD if available else (116, 112, 132)
            ui.text_right(price, 19, price_color, rect.right - 16, rect.y + 11, bold=True)

            if not row.get("in_stock"):
                ui.text_right("out of stock", 13, DANGER, rect.right - 16, rect.y + 31)

        if view.message:
            ui.blit(ui.text(view.message, 16, ACCENT), (px + 24, py + panel_h - 58))
        ui.blit(ui.text("UP / DOWN choose    ENTER buy    ESC back", 15, MUTED),
                (px + 24, py + panel_h - 30))

    # ---------------------------------------------------- memory inspector
    def draw_memory_panel(self, panels: Dict[str, List[Dict[str, str]]],
                          reasons: Dict[str, List[str]], quest_hint: str) -> None:
        """The panel the whole research claim is judged on, so it is made legible.

        Sizes were 11-13 px inside a frame that then got resampled: the reason tag
        was truncated mid-sentence (``Arun accused the player of stealing Mira's
        med…``) and the meta line was unreadable. Now the reason wraps over up to
        three lines in full, summaries wrap instead of clipping at 34 characters,
        and everything renders at window resolution.
        """
        ui = self.ui
        ui.dim((10, 9, 16, 232))

        left = ui.origin_x + 40
        right = ui.origin_x + ui.span_w - 40
        ui.blit(ui.text("MEMORY INSPECTOR — what each NPC actually holds", 24, ACCENT,
                        bold=True), (left, ui.origin_y + 24))
        ui.blit(ui.text("every record this NPC holds · tier · status · importance · confidence"
                        "   (ESC / J to close)", 15, MUTED), (left, ui.origin_y + 56))

        columns = list(panels.keys())
        col_w = int((right - left) / max(1, len(columns)))

        for index, npc_id in enumerate(columns):
            x = left + index * col_w
            content_w = col_w - 36
            y = ui.origin_y + 92
            ui.blit(ui.text(npc_id.upper(), 20, TEXT, bold=True), (x, y))
            y += 28

            reason_lines = reasons.get(npc_id, [])
            if reason_lines:
                for line in ui.wrap("cause: " + reason_lines[0], 15, content_w)[:3]:
                    ui.blit(ui.text(line, 15, WARN), (x, y))
                    y += 19
            y += 6

            # as many rows as the window can hold, so a fullscreen inspector
            # shows the whole store instead of the first eight records
            rows_that_fit = max(4, int((ui.origin_y + ui.span_h - 70 - y) / 30))
            for row in panels[npc_id][:rows_that_fit]:
                tier = str(row.get("tier", ""))
                status = str(row.get("status", ""))
                ui.square(TIER_COLORS.get(tier, MUTED), x, y + 5, 8)
                ui.square(STATUS_COLORS.get(status, MUTED), x + 13, y + 5, 8)

                text_x = x + 28
                summary_lines = ui.wrap(str(row.get("summary", "")), 15, content_w - 28)[:2]
                for line in summary_lines:
                    ui.blit(ui.text(line, 15, TEXT), (text_x, y))
                    y += 18
                meta = f"{tier[:4] or '—'} · {status} · imp {row.get('importance')}"
                ui.blit(ui.text(meta, 13, MUTED), (text_x, y))
                y += 30

        ui.blit(ui.text("next: " + quest_hint, 16, ACCENT),
                (left, ui.origin_y + ui.span_h - 46))

    # ---------------------------------------------------------- overlays
    def draw_day_overlay(self, day: int, entries: Sequence[str]) -> None:
        ui = self.ui
        ui.dim((8, 8, 14, 224))

        centre = ui.origin_x + ui.span_w / 2
        ui.text_center(f"DAY {day}", 44, GOLD, centre, ui.origin_y + 118, bold=True)

        y = ui.origin_y + 214
        for entry in list(entries)[:8]:
            for line in ui.wrap(entry, 19, ui.span_w - 240)[:2]:
                ui.text_center(line, 19, TEXT, centre, y)
                y += 27
            y += 6

        if not entries:
            ui.text_center("A quiet night passes over the town.", 19, MUTED, centre, y)

        ui.text_center("SPACE / ENTER to wake", 16, MUTED, centre,
                       ui.origin_y + ui.span_h - 92)

    def draw_help(self) -> None:
        ui = self.ui
        ui.dim((10, 9, 16, 236))

        left = ui.origin_x + 60
        top = ui.origin_y + 44
        ui.blit(ui.text("HOW TO PLAY", 32, ACCENT, bold=True), (left, top))

        lines = [
            ("WASD / ARROWS", "walk around the town"),
            ("E / SPACE / ENTER", "talk to a nearby townsfolk"),
            ("UP / DOWN", "pick a reply in the dialogue box"),
            ("1 – 9", "jump straight to a reply"),
            ("MOUSE", "hover and click replies"),
            ("N", "sleep and advance one day"),
            ("J / TAB", "memory inspector (tiers, status, causes)"),
            ("F11", "fullscreen (on / off)"),
            ("F10", "cycle window size (1x, 1.25x, 1.5x, 2x)"),
            ("drag the window", "the view scales to fit, and the text stays sharp"),
            ("F1", "this screen        ESC  close / back"),
        ]
        y = top + 64
        for key, description in lines:
            ui.blit(ui.text(key, 18, TEXT, bold=True), (left, y))
            ui.blit(ui.text(description, 18, MUTED), (left + 240, y))
            y += 28

        y += 12
        for line in [
            "The town runs on the research core: every reply you get is generated from",
            "that NPC's own memory store, and the orange tag in the dialogue box names",
            "the memory the counterfactual verifier certified as the cause of their",
            "decision. J opens the same evidence layer for every townsfolk at once.",
        ]:
            ui.blit(ui.text(line, 17, MUTED), (left, y))
            y += 24

        ui.blit(ui.text("Mira will not trade with you while she believes you a thief.", 17, ACCENT),
                (left, y + 10))

    def draw_toast(self, text: str) -> None:
        """A short system message near the top centre, crisp like the rest."""
        ui = self.ui
        lines = ui.wrap(text, 17, 620)[:3]
        box_h = 18 + len(lines) * 24
        box_w = max(ui.measure(line, 17) for line in lines) + 32
        box_x = ui.origin_x + (ui.span_w - box_w) / 2
        ui.panel((box_x, 60, box_w, box_h), (20, 18, 30, 226), (110, 104, 140),
                 width=2, radius=8)
        for index, line in enumerate(lines):
            ui.blit(ui.text(line, 17, (240, 236, 250)), (box_x + 16, 68 + index * 24))
