"""Surface factory: turns pixel specs into scaled pygame surfaces.

Ground tiles are generated procedurally from a fixed seed so the artwork stays
deterministic (identical every run, no binary assets in the repository) while
still reading as hand-placed pixel detail.
"""

from __future__ import annotations

import random
from typing import Dict, List, Mapping, Optional, Tuple

import pygame

from npc_memory_project.game.pixel_art import PALETTE, TILE_SPECS
from npc_memory_project.game.world_map import Tile

TILE = 16
SCALE = 3
TILE_PX = TILE * SCALE          # 48 on screen


# ------------------------------------------------------------------- helpers
def _px(surface: pygame.Surface, x: int, y: int, w: int = 1, h: int = 1,
        color: Tuple[int, int, int, int] = (0, 0, 0, 255)) -> None:
    surface.fill(color, pygame.Rect(x, y, w, h))


def surface_from_spec(spec: List[str], palette: Mapping[str, tuple],
                      scale: int = SCALE) -> pygame.Surface:
    """Build a scaled surface from 16x16 string art (one char per pixel)."""
    size = len(spec)
    base = pygame.Surface((size, size), pygame.SRCALPHA)
    for y, row in enumerate(spec):
        for x, key in enumerate(row):
            color = palette[key]
            if color[3] == 0:
                continue
            base.set_at((x, y), color)
    return pygame.transform.scale(base, (size * scale, size * scale))


def _font(size: int, bold: bool) -> pygame.font.Font:
    font = pygame.font.Font(None, max(12, size))
    font.set_bold(bold)
    return font


def pixel_text(text: str, size: int, color, bold: bool = False) -> pygame.Surface:
    """Render UI text at its final size.

    Previously this rendered at half size and scaled up x2, which mangled the
    default font's small glyphs. Rendering directly is crisp and no slower.
    """
    return _font(size, bold).render(text, False, color)


def wrap_text(text: str, size: int, max_width: int) -> List[str]:
    """Greedy word wrap measured against the real rendered font."""
    font = _font(size, False)
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ------------------------------------------------------- procedural ground
def _speckle(surface: pygame.Surface, colors, count: int, rng: random.Random) -> None:
    for _ in range(count):
        x, y = rng.randrange(TILE), rng.randrange(TILE)
        surface.set_at((x, y), rng.choice(colors))


def make_grass(rng: random.Random) -> pygame.Surface:
    surf = pygame.Surface((TILE, TILE))
    surf.fill(PALETTE["g"])
    _speckle(surf, (PALETTE["G"], PALETTE["h"]), 22, rng)
    return surf


def make_tall_grass(rng: random.Random) -> pygame.Surface:
    surf = make_grass(rng)
    for _ in range(7):
        x, y = rng.randrange(1, TILE - 1), rng.randrange(3, TILE - 2)
        _px(surf, x, y - 2, 1, 3, PALETTE["h"])
        _px(surf, x + 1, y - 1, 1, 2, PALETTE["G"])
    return surf


def make_path(rng: random.Random) -> pygame.Surface:
    surf = pygame.Surface((TILE, TILE))
    surf.fill(PALETTE["d"])
    _speckle(surf, (PALETTE["D"], PALETTE["y"]), 26, rng)
    for _ in range(4):
        x, y = rng.randrange(TILE - 1), rng.randrange(TILE - 1)
        _px(surf, x, y, 2, 1, PALETTE["D"])
    return surf


def make_plaza(rng: random.Random) -> pygame.Surface:
    surf = pygame.Surface((TILE, TILE))
    surf.fill(PALETTE["s"])
    _px(surf, 0, 0, TILE, 1, PALETTE["S"])
    _px(surf, 0, 0, 1, TILE, PALETTE["S"])
    _speckle(surf, (PALETTE["W"], PALETTE["S"]), 16, rng)
    return surf


def make_water() -> pygame.Surface:
    surf = pygame.Surface((TILE, TILE))
    surf.fill(PALETTE["b"])
    for y in range(0, TILE, 4):
        _px(surf, 2, y + 1, 6, 1, PALETTE["B"])
        _px(surf, 9, y + 3, 5, 1, PALETTE["B"])
    _speckle(surf, (PALETTE["W"],), 4, random.Random(7))
    return surf


# ------------------------------------------------------------------- factory
class SpriteFactory:
    """Builds and caches every surface the renderer needs."""

    def __init__(self, scale: int = SCALE) -> None:
        self.scale = scale
        self.tile_px = TILE * scale
        self._tiles: Dict[Tile, pygame.Surface] = {}
        self._objects: Dict[Tile, pygame.Surface] = {}
        self._cache: Dict[str, pygame.Surface] = {}
        self._build()

    # -- construction -------------------------------------------------------
    def _build(self) -> None:
        rng = random.Random(20260920)

        def scaled(surf: pygame.Surface) -> pygame.Surface:
            return pygame.transform.scale(
                surf, (surf.get_width() * self.scale, surf.get_height() * self.scale)
            )

        self._tiles[Tile.GRASS] = scaled(make_grass(rng))
        self._tiles[Tile.TALL_GRASS] = scaled(make_tall_grass(rng))
        self._tiles[Tile.PATH] = scaled(make_path(rng))
        self._tiles[Tile.PLAZA] = scaled(make_plaza(rng))
        self._tiles[Tile.WATER] = scaled(make_water())

        for tile, spec_name in (
            (Tile.TREE, "tree"),
            (Tile.WALL, "wall"),
            (Tile.ROOF, "roof"),
            (Tile.DOOR, "door"),
            (Tile.STALL, "stall"),
            (Tile.WELL, "well"),
            (Tile.SIGN, "sign"),
            (Tile.FENCE, "fence"),
            (Tile.CRATE, "crate"),
            (Tile.BARREL, "barrel"),
            (Tile.FLOWER, "flower"),
        ):
            self._objects[tile] = surface_from_spec(TILE_SPECS[spec_name], PALETTE, self.scale)

    # -- access -------------------------------------------------------------
    def ground(self, tile: Tile) -> Optional[pygame.Surface]:
        return self._tiles.get(tile)

    def object_surface(self, tile: Tile) -> Optional[pygame.Surface]:
        return self._objects.get(tile)

    def character(self, npc_id: str, direction: str, frame: int) -> pygame.Surface:
        key = f"{npc_id}:{direction}:{frame}"
        if key not in self._cache:
            self._cache[key] = build_character(npc_id, direction, frame, self.scale)
        return self._cache[key]

    def portrait(self, npc_id: str, size: int) -> pygame.Surface:
        """Head-and-shoulders crop of the character sprite, for the dialogue box."""
        key = f"portrait:{npc_id}:{size}"
        if key not in self._cache:
            sprite = self.character(npc_id, "down", 0)
            w, h = sprite.get_size()
            crop = sprite.subsurface(pygame.Rect(0, 0, w, int(h * 0.62))).copy()
            self._cache[key] = pygame.transform.scale(crop, (size, int(size * 0.62 * 1.6)))
        return self._cache[key]


# ------------------------------------------------------------------ people
CHARACTER_PALETTES: Dict[str, Dict[str, Tuple[int, int, int, int]]] = {
    "mira": {
        "hair": (86, 58, 38, 255), "hair2": (58, 38, 26, 255),
        "skin": PALETTE["f"], "shirt": (78, 146, 96, 255), "shirt2": (52, 104, 70, 255),
        "pants": (196, 190, 168, 255), "trim": (240, 238, 226, 255), "eye": PALETTE["k"],
    },
    "kael": {
        "hair": (58, 46, 40, 255), "hair2": (38, 30, 26, 255),
        "skin": PALETTE["f"], "shirt": (74, 92, 132, 255), "shirt2": (52, 66, 98, 255),
        "pants": (66, 72, 92, 255), "trim": PALETTE["W"], "eye": PALETTE["k"],
    },
    "arun": {
        "hair": (196, 118, 56, 255), "hair2": (150, 84, 38, 255),
        "skin": PALETTE["f"], "shirt": (168, 92, 74, 255), "shirt2": (128, 64, 54, 255),
        "pants": (120, 96, 70, 255), "trim": PALETTE["y"], "eye": PALETTE["k"],
    },
    "rohan": {
        "hair": (44, 40, 52, 255), "hair2": (28, 26, 36, 255),
        "skin": PALETTE["F"], "shirt": (78, 76, 92, 255), "shirt2": (54, 52, 68, 255),
        "pants": (62, 60, 74, 255), "trim": (108, 104, 124, 255), "eye": PALETTE["k"],
    },
    "player": {
        "hair": (72, 52, 36, 255), "hair2": (48, 34, 24, 255),
        "skin": PALETTE["f"], "shirt": (92, 122, 196, 255), "shirt2": (62, 88, 154, 255),
        "pants": (58, 60, 84, 255), "trim": PALETTE["y"], "eye": PALETTE["k"],
    },
}

#: Roughly 16x24 pixels: a head over a body, with a 1px outline throughout.
CHAR_W, CHAR_H = 16, 24


def build_character(npc_id: str, direction: str, frame: int, scale: int = SCALE) -> pygame.Surface:
    """Compose one character sprite. ``frame`` toggles the walking legs."""
    pal = CHARACTER_PALETTES.get(npc_id, CHARACTER_PALETTES["player"])
    surf = pygame.Surface((CHAR_W, CHAR_H), pygame.SRCALPHA)
    outline = PALETTE["k"]
    frame = frame % 2

    # --- legs ---------------------------------------------------------------
    leg_shift = 1 if frame == 1 else 0
    _px(surf, 5, 19, 2, 4 + 1 - leg_shift, pal["pants"])
    _px(surf, 9, 19, 2, 4 + leg_shift, pal["pants"])
    _px(surf, 5, 23 - leg_shift, 2, 1, outline)
    _px(surf, 9, 23, 2, 1, outline)
    _px(surf, 4, 19, 1, 5, outline)
    _px(surf, 11, 19, 1, 5, outline)

    # --- body ---------------------------------------------------------------
    _px(surf, 4, 12, 8, 8, pal["shirt"])
    _px(surf, 4, 12, 8, 2, pal["shirt2"])
    _px(surf, 3, 12, 1, 8, outline)
    _px(surf, 12, 12, 1, 8, outline)
    _px(surf, 4, 20, 8, 1, outline)

    # --- arms (swing with the walk cycle) ----------------------------------
    arm_y = 13 + (1 if frame == 1 else 0)
    _px(surf, 2, arm_y, 2, 6, pal["shirt"])
    _px(surf, 12, arm_y, 2, 6, pal["shirt"])
    _px(surf, 2, arm_y + 5, 2, 2, pal["skin"])
    _px(surf, 12, arm_y + 5, 2, 2, pal["skin"])
    _px(surf, 1, arm_y, 1, 7, outline)
    _px(surf, 14, arm_y, 1, 7, outline)

    # --- head ---------------------------------------------------------------
    _px(surf, 4, 3, 8, 8, pal["skin"])
    _px(surf, 3, 3, 1, 8, outline)
    _px(surf, 12, 3, 1, 8, outline)
    _px(surf, 4, 2, 8, 1, outline)
    _px(surf, 4, 11, 8, 1, outline)

    # --- hair / headgear ----------------------------------------------------
    _px(surf, 3, 1, 10, 3, pal["hair"])
    _px(surf, 3, 1, 10, 1, pal["hair2"])
    _px(surf, 3, 4, 2, 4, pal["hair"])
    _px(surf, 11, 4, 2, 4, pal["hair"])
    if npc_id == "kael":
        _px(surf, 3, 0, 10, 2, pal["trim"])          # guard helm band
        _px(surf, 2, 1, 12, 1, outline)
    if npc_id == "arun":
        _px(surf, 3, 0, 10, 2, pal["trim"])          # vendor's cap
        _px(surf, 2, 2, 12, 1, outline)
    if npc_id == "mira":
        _px(surf, 3, 0, 10, 2, pal["trim"])          # apothecary's kerchief
    if npc_id == "rohan":
        _px(surf, 2, 2, 12, 6, pal["shirt2"])        # hood, pulled low
        _px(surf, 4, 3, 8, 2, pal["hair"])

    # --- face (only when facing the camera or sideways) ---------------------
    if direction == "down":
        _px(surf, 6, 6, 1, 2, pal["eye"])
        _px(surf, 9, 6, 1, 2, pal["eye"])
        _px(surf, 7, 9, 2, 1, pal["hair2"])
    elif direction == "left":
        _px(surf, 5, 6, 1, 2, pal["eye"])
        _px(surf, 4, 8, 1, 1, pal["skin"])
    elif direction == "right":
        _px(surf, 10, 6, 1, 2, pal["eye"])
        _px(surf, 11, 8, 1, 1, pal["skin"])

    # --- accessories --------------------------------------------------------
    if npc_id == "mira":                              # apothecary apron
        _px(surf, 5, 14, 6, 5, pal["trim"])
        _px(surf, 5, 14, 6, 1, pal["shirt2"])
    if npc_id == "kael":                              # sword at the hip
        _px(surf, 13, 14, 1, 6, pal["trim"])
        _px(surf, 12, 19, 3, 1, PALETTE["Y"])
    if npc_id == "arun":                              # coin pouch
        _px(surf, 2, 16, 3, 3, PALETTE["y"])

    return pygame.transform.scale(surf, (CHAR_W * scale, CHAR_H * scale))
