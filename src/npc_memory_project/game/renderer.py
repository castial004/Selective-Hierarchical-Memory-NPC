"""Rendering: tile world, characters, HUD, dialogue box, shop and memory panels.

The dialogue box is deliberately Genshin-shaped -- a portrait plate, a name
label, a typewritten body, and a numbered list of selectable replies, with the
counterfactually certified reason shown as a small tag so the research claim is
visible in-game rather than only in a paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pygame

from npc_memory_project.game.assets import (
    CHAR_H, CHAR_W, SCALE, TILE_PX, SpriteFactory, pixel_text, wrap_text,
)
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
    def __init__(self, screen: pygame.Surface, sprites: SpriteFactory) -> None:
        self.screen = screen
        self.sprites = sprites
        self.width, self.height = screen.get_size()
        self.choice_rects: List[pygame.Rect] = []

    # ------------------------------------------------------------- world
    def draw_world(self, town: TownMap, camera, player: "Entity",
                   npcs: Sequence["Entity"], prompt: Optional[str] = None,
                   prompt_at: Tuple[int, int] = (0, 0)) -> None:
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

        if prompt:
            self._draw_prompt(prompt, prompt_at, camera)

    def _draw_entity(self, entity: "Entity", camera) -> None:
        sx, sy = camera.world_to_screen(entity.x, entity.y)
        shadow = pygame.Surface((entity.w, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 70), shadow.get_rect())
        self.screen.blit(shadow, (sx, sy + entity.h - 6))

        sprite = self.sprites.character(entity.sprite_id, entity.facing, entity.frame)
        self.screen.blit(sprite, (sx, sy))

        if entity.label:
            text = pixel_text(entity.label, 14, TEXT, bold=True)
            plate = pygame.Surface((text.get_width() + 8, text.get_height() + 4),
                                   pygame.SRCALPHA)
            plate.fill((18, 16, 26, 170))
            self.screen.blit(plate, (sx + entity.w // 2 - plate.get_width() // 2,
                                     sy - plate.get_height() - 2))
            self.screen.blit(text, (sx + entity.w // 2 - text.get_width() // 2,
                                    sy - text.get_height())) 

    def _draw_prompt(self, text: str, at: Tuple[int, int], camera) -> None:
        sx, sy = camera.world_to_screen(*at)
        surf = pixel_text(text, 16, INK, bold=True)
        box = pygame.Surface((surf.get_width() + 14, surf.get_height() + 10), pygame.SRCALPHA)
        pygame.draw.rect(box, (246, 240, 210, 240), box.get_rect(), border_radius=6)
        pygame.draw.rect(box, INK, box.get_rect(), 2, border_radius=6)
        box.blit(surf, (7, 5))
        self.screen.blit(box, (sx - box.get_width() // 2, sy - box.get_height()))

    # --------------------------------------------------------------- HUD
    def draw_hud(self, day: int, gold: int, item_count: int, quest_hint: str,
                 npc_name: str = "", interacting: bool = False) -> None:
        bar = pygame.Surface((self.width, 40), pygame.SRCALPHA)
        bar.fill((16, 14, 24, 190))
        self.screen.blit(bar, (0, 0))

        left = pixel_text(f"DAY {day}", 20, GOLD, bold=True)
        self.screen.blit(left, (16, 11))
        gold_text = pixel_text(f"{gold} GOLD", 18, GOLD)
        self.screen.blit(gold_text, (150, 12))
        bag = pixel_text(f"{item_count} ITEMS", 18, MUTED)
        self.screen.blit(bag, (300, 12))

        hint = pixel_text(quest_hint, 15, TEXT)
        if hint.get_width() > 430:                    # keep it clear of the edge
            while hint.get_width() > 430 and len(quest_hint) > 8:
                quest_hint = quest_hint[:-1]
                hint = pixel_text(quest_hint.rstrip() + "…", 15, TEXT)
        self.screen.blit(hint, (self.width - hint.get_width() - 16, 14))

        controls = pixel_text("WASD move   E talk   N next day   J memory   F1 help", 13, MUTED)
        footer = pygame.Surface((self.width, 22), pygame.SRCALPHA)
        footer.fill((16, 14, 24, 170))
        self.screen.blit(footer, (0, self.height - 22))
        self.screen.blit(controls, (16, self.height - 18))

        if npc_name:
            name = pixel_text(npc_name, 15, ACCENT, bold=True)
            self.screen.blit(name, (self.width - name.get_width() - 16, 44))

    # ---------------------------------------------------------- dialogue
    def draw_dialogue(self, view: DialogueView) -> None:
        box_h = 336
        box = pygame.Rect(24, self.height - box_h - 30, self.width - 48, box_h)
        panel = pygame.Surface(box.size, pygame.SRCALPHA)
        panel.fill(PANEL)
        pygame.draw.rect(panel, PANEL_EDGE, panel.get_rect(), 3, border_radius=10)
        self.screen.blit(panel, box.topleft)

        # portrait plate
        portrait_box = pygame.Rect(box.x + 16, box.y + 16, 132, 150)
        pygame.draw.rect(self.screen, (20, 18, 30), portrait_box, border_radius=8)
        pygame.draw.rect(self.screen, PANEL_EDGE, portrait_box, 2, border_radius=8)
        face = self.sprites.portrait(view.speaker, 116)
        self.screen.blit(face, (portrait_box.x + 8, portrait_box.y + 10))

        name = pixel_text(view.label.upper(), 20, ACCENT, bold=True)
        plate = pygame.Rect(box.x + 16, portrait_box.bottom + 8,
                            max(name.get_width() + 20, 132), name.get_height() + 12)
        pygame.draw.rect(self.screen, (34, 30, 48), plate, border_radius=6)
        pygame.draw.rect(self.screen, PANEL_EDGE, plate, 2, border_radius=6)
        self.screen.blit(name, (plate.x + 10, plate.y + 6))

        # certified causal reason tag -- its own line, above the speech
        text_x = box.x + 172
        text_w = box.right - text_x - 24
        if view.certified_reason:
            tag = "CAUSAL CAUSE CERTIFIED BY ABLATION:  " + view.certified_reason
            label = pixel_text(tag, 13, WARN)
            if label.get_width() > text_w:
                label = label.subsurface(pygame.Rect(0, 0, text_w, label.get_height())).copy()
            self.screen.blit(label, (text_x, box.y + 14))

        if view.dialogue_source == "llm_rejected":
            warn = pixel_text("UNGROUNDED LLM LINE REJECTED", 13, DANGER)
            self.screen.blit(warn, (text_x, box.y + 32))

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
                self.screen.blit(pixel_text(visible, 20, TEXT), (text_x, y))
            consumed += len(line) + 1
            y += line_height
            if y > box.y + 148:
                break

        # choices
        self.choice_rects = []
        if not view.show_choices:
            hint = pixel_text("SPACE / ENTER to continue", 14, MUTED)
            self.screen.blit(hint, (box.right - hint.get_width() - 24, box.bottom - 30))
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
                pygame.draw.rect(self.screen, HIGHLIGHT, row_rect, border_radius=6)
                pygame.draw.rect(self.screen, PANEL_EDGE, row_rect, 2, border_radius=6)

            color = TEXT if enabled else (108, 104, 124)
            marker = "▶" if selected else " "
            label = f"{marker} {row + 1}. {choice.get('label', '')}"
            self.screen.blit(pixel_text(label, 17, color, bold=selected),
                             (row_rect.x + 8, row_rect.y + 6))

            if not enabled and choice.get("reason"):
                reason = pixel_text(str(choice["reason"]), 12, (128, 120, 116))
                reason = reason.subsurface(pygame.Rect(
                    0, 0, min(reason.get_width(), 300), reason.get_height())).copy()
                self.screen.blit(reason, (row_rect.right - reason.get_width() - 8,
                                          row_rect.y + 8))

        if view.scroll + 6 < len(view.choices):
            more = pixel_text(f"▼ {len(view.choices) - view.scroll - 6} more", 13, MUTED)
            self.screen.blit(more, (box.x + 176, list_y + 6 * 28 + 2))

    # -------------------------------------------------------------- shop
    def draw_shop(self, view: ShopView) -> None:
        panel_w, panel_h = 620, 400
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill(PANEL)
        pygame.draw.rect(panel, PANEL_EDGE, panel.get_rect(), 3, border_radius=10)
        px = (self.width - panel_w) // 2
        py = (self.height - panel_h) // 2 - 40
        self.screen.blit(panel, (px, py))

        title = pixel_text(f"{view.label}  —  Goods", 22, ACCENT, bold=True)
        self.screen.blit(title, (px + 24, py + 20))
        purse = pixel_text(f"{view.gold} gold", 18, GOLD)
        self.screen.blit(purse, (px + panel_w - purse.get_width() - 24, py + 24))
        if view.discount:
            deal = pixel_text("favour: 25% off", 14, ACCENT)
            self.screen.blit(deal, (px + panel_w - deal.get_width() - 24, py + 50))

        self.choice_rects = []
        for index, row in enumerate(view.rows):
            y = py + 80 + index * 52
            rect = pygame.Rect(px + 20, y, panel_w - 40, 46)
            self.choice_rects.append(rect)
            if index == view.selected:
                pygame.draw.rect(self.screen, HIGHLIGHT, rect, border_radius=8)
                pygame.draw.rect(self.screen, PANEL_EDGE, rect, 2, border_radius=8)

            available = bool(row.get("available"))
            color = TEXT if available else (116, 112, 132)
            self.screen.blit(pixel_text(str(row["name"]), 18, color, bold=index == view.selected),
                             (rect.x + 14, rect.y + 6))
            self.screen.blit(pixel_text(str(row["description"]), 13, MUTED), (rect.x + 14, rect.y + 26))

            price = str(row["price"]) + "g"
            price_color = GOLD if available else (116, 112, 132)
            surf = pixel_text(price, 18, price_color, bold=True)
            self.screen.blit(surf, (rect.right - surf.get_width() - 16, rect.y + 12))

            if not row.get("in_stock"):
                out = pixel_text("out of stock", 12, DANGER)
                self.screen.blit(out, (rect.right - out.get_width() - 16, rect.y + 30))

        if view.message:
            msg = pixel_text(view.message, 15, ACCENT)
            self.screen.blit(msg, (px + 24, py + panel_h - 54))
        hint = pixel_text("↑/↓ choose    ENTER buy    ESC back", 14, MUTED)
        self.screen.blit(hint, (px + 24, py + panel_h - 28))

    # ---------------------------------------------------- memory inspector
    def draw_memory_panel(self, panels: Dict[str, List[Dict[str, str]]],
                          reasons: Dict[str, List[str]], quest_hint: str) -> None:
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((10, 9, 16, 226))
        self.screen.blit(overlay, (0, 0))

        title = pixel_text("MEMORY INSPECTOR — what each NPC actually holds", 22, ACCENT, bold=True)
        self.screen.blit(title, (40, 28))
        sub = pixel_text("tier · status · importance · confidence   (ESC / J to close)", 14, MUTED)
        self.screen.blit(sub, (40, 58))

        columns = list(panels.keys())
        col_w = (self.width - 80) // max(1, len(columns))
        for index, npc_id in enumerate(columns):
            x = 40 + index * col_w
            y = 96
            self.screen.blit(pixel_text(npc_id.upper(), 18, TEXT, bold=True), (x, y))
            y += 30

            reason_lines = reasons.get(npc_id, [])
            if reason_lines:
                tag = pixel_text("cause: " + reason_lines[0], 12, WARN)
                tag = tag.subsurface(pygame.Rect(
                    0, 0, min(tag.get_width(), col_w - 20), tag.get_height())).copy()
                self.screen.blit(tag, (x, y))
            y += 24

            for row in panels[npc_id][:9]:
                tier = str(row.get("tier", ""))
                status = str(row.get("status", ""))
                pygame.draw.rect(self.screen, TIER_COLORS.get(tier, MUTED), (x, y + 6, 6, 6))
                pygame.draw.rect(self.screen, STATUS_COLORS.get(status, MUTED), (x + 12, y + 6, 6, 6))
                summary = str(row.get("summary", ""))
                if len(summary) > 34:
                    summary = summary[:32] + "…"
                self.screen.blit(pixel_text(summary, 13, TEXT), (x + 24, y))
                meta = f"{tier[:4]}·{status[:5]}·{row.get('importance')}"
                self.screen.blit(pixel_text(meta, 11, MUTED), (x + 24, y + 14))
                y += 34

        hint = pixel_text("next: " + quest_hint, 15, ACCENT)
        self.screen.blit(hint, (40, self.height - 52))

    # ---------------------------------------------------------- overlays
    def draw_day_overlay(self, day: int, entries: Sequence[str]) -> None:
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((8, 8, 14, 210))
        self.screen.blit(overlay, (0, 0))

        title = pixel_text(f"DAY {day}", 40, GOLD, bold=True)
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, 120))

        y = 210
        for entry in list(entries)[:8]:
            for line in wrap_text(entry, 18, self.width - 240)[:2]:
                surf = pixel_text(line, 18, TEXT)
                self.screen.blit(surf, (self.width // 2 - surf.get_width() // 2, y))
                y += 26
            y += 6

        if not entries:
            surf = pixel_text("A quiet night passes over the town.", 18, MUTED)
            self.screen.blit(surf, (self.width // 2 - surf.get_width() // 2, y))

        hint = pixel_text("SPACE / ENTER to wake", 15, MUTED)
        self.screen.blit(hint, (self.width // 2 - hint.get_width() // 2, self.height - 90))

    def draw_help(self) -> None:
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((10, 9, 16, 232))
        self.screen.blit(overlay, (0, 0))

        title = pixel_text("HOW TO PLAY", 30, ACCENT, bold=True)
        self.screen.blit(title, (60, 50))

        lines = [
            "WASD / ARROWS      walk around the town",
            "E / SPACE / ENTER  talk to a nearby townsfolk",
            "UP / DOWN          pick a reply in the dialogue box",
            "1 – 9              jump straight to a reply",
            "MOUSE              hover and click replies",
            "N                  sleep and advance one day",
            "J / TAB            memory inspector (tiers, status, causes)",
            "F1                 this screen        ESC  close / back",
            "",
            "The town runs on the research core: every reply you get is",
            "generated from that NPC's own memory store, and the orange tag in",
            "the dialogue box names the memory the counterfactual verifier",
            "certified as the cause of their decision.",
            "",
            "Mira will not trade with you while she believes you a thief.",
            "Kael can tell you how a traveller proves their innocence.",
        ]
        y = 110
        for line in lines:
            color = TEXT if line else MUTED
            self.screen.blit(pixel_text(line, 17, color), (60, y))
            y += 28
