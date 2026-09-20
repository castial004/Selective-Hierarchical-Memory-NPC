"""Town map: tiles, collision and NPC posts.

Pure geometry and data -- no pygame -- so collision, camera maths and post
placement are unit-testable without a display.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Tile(str, Enum):
    GRASS = "grass"
    TALL_GRASS = "tall_grass"
    FLOWER = "flower"
    PATH = "path"
    PLAZA = "plaza"
    WATER = "water"
    TREE = "tree"
    WALL = "wall"
    ROOF = "roof"
    DOOR = "door"
    STALL = "stall"
    WELL = "well"
    SIGN = "sign"
    FENCE = "fence"
    CRATE = "crate"
    BARREL = "barrel"


#: Tiles a character cannot walk onto.
BLOCKING = frozenset({
    Tile.WATER, Tile.TREE, Tile.WALL, Tile.ROOF, Tile.STALL,
    Tile.WELL, Tile.SIGN, Tile.FENCE, Tile.CRATE, Tile.BARREL, Tile.DOOR,
})

#: Tiles that are purely decorative ground cover (walkable).
GROUND = frozenset({Tile.GRASS, Tile.TALL_GRASS, Tile.FLOWER, Tile.PATH, Tile.PLAZA})


@dataclass(frozen=True)
class NPCPost:
    npc_id: str
    tile: Tuple[int, int]
    facing: str = "down"
    label: str = ""


class TownMap:
    """A tile grid with pixel-space collision queries."""

    def __init__(self, width: int = 40, height: int = 30, tile_size: int = 16,
                 fill: Tile = Tile.GRASS) -> None:
        self.width = width
        self.height = height
        self.tile_size = tile_size
        self.grid: List[List[Tile]] = [[fill for _ in range(width)] for _ in range(height)]
        self.posts: Dict[str, NPCPost] = {}

    # ------------------------------------------------------------- authoring
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def set(self, x: int, y: int, tile: Tile) -> None:
        if self.in_bounds(x, y):
            self.grid[y][x] = tile

    def get(self, x: int, y: int) -> Tile:
        x, y = int(x), int(y)         # callers pass pixel coords, often floats
        if not self.in_bounds(x, y):
            return Tile.WALL          # out of bounds acts solid
        return self.grid[y][x]

    def fill_rect(self, x: int, y: int, w: int, h: int, tile: Tile) -> None:
        for ty in range(y, y + h):
            for tx in range(x, x + w):
                self.set(tx, ty, tile)

    def outline_rect(self, x: int, y: int, w: int, h: int, tile: Tile) -> None:
        for tx in range(x, x + w):
            self.set(tx, y, tile)
            self.set(tx, y + h - 1, tile)
        for ty in range(y, y + h):
            self.set(x, ty, tile)
            self.set(x + w - 1, ty, tile)

    def place_building(self, x: int, y: int, w: int, h: int,
                       roof_rows: int = 2, door_offsets: Tuple[int, ...] = ()) -> None:
        """Block of wall with a roof band on top and optional doors in the base."""
        self.fill_rect(x, y, w, h, Tile.WALL)
        self.fill_rect(x, y, w, roof_rows, Tile.ROOF)
        for offset in door_offsets:
            self.set(x + offset, y + h - 1, Tile.DOOR)

    def add_post(self, npc_id: str, tile: Tuple[int, int], facing: str = "down",
                 label: str = "") -> None:
        self.posts[npc_id] = NPCPost(npc_id, tile, facing, label or npc_id.capitalize())

    def standable_near(self, tile: Tuple[int, int]) -> bool:
        """True when a tile is walkable -- used to sanity-check NPC posts."""
        return self.get(*tile) not in BLOCKING

    # ------------------------------------------------------------ collision
    def is_blocked(self, x: float, y: float) -> bool:
        return self.get(x // self.tile_size, y // self.tile_size) in BLOCKING

    def rect_blocked(self, rect: Tuple[float, float, float, float]) -> bool:
        """Sample a pixel rect's corners and edge midpoints against the grid."""
        x, y, w, h = rect
        points = (
            (x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1),
            (x + w / 2, y), (x + w / 2, y + h - 1),
            (x, y + h / 2), (x + w - 1, y + h / 2),
        )
        return any(self.is_blocked(px, py) for px, py in points)

    def pixel_size(self) -> Tuple[int, int]:
        return self.width * self.tile_size, self.height * self.tile_size


def build_town(tile_size: int = 16) -> TownMap:
    """Assemble the town: pond, plaza, apothecary, guard post, market, alley."""
    tm = TownMap(width=40, height=30, tile_size=tile_size)

    # --- pond in the north-west ---
    tm.fill_rect(3, 3, 8, 5, Tile.WATER)
    tm.outline_rect(3, 3, 8, 5, Tile.WATER)

    # --- plaza: main stone square in the centre ---
    tm.fill_rect(14, 12, 12, 9, Tile.PLAZA)
    tm.set(19, 15, Tile.WELL)
    tm.set(20, 15, Tile.WELL)
    tm.set(19, 16, Tile.WELL)
    tm.set(20, 16, Tile.WELL)

    # --- paths: plaza to the three buildings ---
    tm.fill_rect(10, 15, 4, 2, Tile.PATH)      # west, to the apothecary
    tm.fill_rect(26, 15, 5, 2, Tile.PATH)      # east, to the market
    tm.fill_rect(19, 21, 2, 5, Tile.PATH)      # south, to the guard post
    tm.fill_rect(19, 7, 2, 5, Tile.PATH)       # north, to the pond

    # --- apothecary (Mira), west side ---
    tm.place_building(4, 13, 6, 5, roof_rows=2, door_offsets=(2, 3))
    tm.set(1, 18, Tile.CRATE)
    tm.set(2, 18, Tile.CRATE)
    tm.set(1, 19, Tile.BARREL)
    tm.add_post("mira", (10, 16), facing="right", label="Mira")
    tm.set(10, 13, Tile.SIGN)

    # --- market stall (Arun), east side ---
    tm.place_building(29, 12, 7, 5, roof_rows=2, door_offsets=(3,))
    tm.set(28, 18, Tile.STALL)
    tm.set(29, 18, Tile.STALL)
    tm.set(30, 18, Tile.STALL)
    tm.set(31, 19, Tile.CRATE)
    tm.add_post("arun", (28, 16), facing="left", label="Arun")

    # --- guard post (Kael), south ---
    tm.place_building(16, 25, 8, 4, roof_rows=1, door_offsets=(3, 4))
    tm.set(15, 24, Tile.FENCE)
    tm.set(24, 24, Tile.FENCE)
    tm.add_post("kael", (20, 23), facing="up", label="Kael")

    # --- alley (Rohan), north-east, behind the market ---
    # Fence the perimeter and leave the interior walkable, with a gate to the
    # south -- otherwise the enclosure seals the NPC inside it.
    tm.fill_rect(33, 4, 5, 6, Tile.GRASS)
    tm.outline_rect(33, 4, 5, 6, Tile.FENCE)
    tm.set(35, 9, Tile.PATH)                   # gate through the south fence
    tm.set(35, 8, Tile.PATH)
    tm.set(35, 7, Tile.PATH)
    tm.fill_rect(30, 9, 5, 1, Tile.PATH)       # path in from the market
    tm.set(34, 5, Tile.CRATE)
    tm.add_post("rohan", (35, 6), facing="down", label="Rohan")

    # --- scenery: trees around the border, flowers on the grass ---
    for x, y in (
        (0, 0), (1, 1), (2, 0), (0, 2), (11, 1), (12, 2), (26, 1), (27, 0), (38, 0), (39, 2),
        (0, 27), (1, 28), (3, 29), (36, 28), (38, 27), (39, 29), (13, 28), (12, 29), (26, 29),
        (0, 12), (1, 11), (2, 25), (5, 29), (30, 28), (33, 22), (12, 6), (25, 24), (8, 22),
    ):
        tm.set(x, y, Tile.TREE)      # note: nothing inside the pond (3..10 x 3..7)

    for x, y in (
        (13, 3), (14, 5), (24, 4), (25, 6), (6, 22), (7, 24), (33, 26), (34, 27),
        (9, 9), (10, 10), (28, 8), (29, 26), (15, 27), (24, 27), (8, 12), (32, 11),
    ):
        tm.set(x, y, Tile.FLOWER)

    for x, y in (
        (16, 5), (21, 6), (23, 9), (15, 10), (17, 22), (22, 23), (12, 12), (27, 22),
    ):
        tm.set(x, y, Tile.TALL_GRASS)

    return tm


class Camera:
    """Viewport that follows a target in world pixels and clamps to the map."""

    def __init__(self, viewport: Tuple[int, int], map_pixels: Tuple[int, int]) -> None:
        self.view_w, self.view_h = viewport
        self.map_w, self.map_h = map_pixels
        self.x = 0.0
        self.y = 0.0

    def centre_on(self, target_x: float, target_y: float) -> None:
        self.x = target_x - self.view_w / 2
        self.y = target_y - self.view_h / 2
        self.clamp()

    def clamp(self) -> None:
        max_x = max(0, self.map_w - self.view_w)
        max_y = max(0, self.map_h - self.view_h)
        self.x = min(max(0.0, self.x), float(max_x))
        self.y = min(max(0.0, self.y), float(max_y))

    def world_to_screen(self, x: float, y: float) -> Tuple[int, int]:
        return int(x - self.x), int(y - self.y)

    def visible_tiles(self, tile_px: int) -> Tuple[range, range]:
        """Tile index ranges intersecting the viewport, plus one tile of margin."""
        x0 = max(0, int(self.x // tile_px) - 1)
        y0 = max(0, int(self.y // tile_px) - 1)
        x1 = int((self.x + self.view_w) // tile_px) + 2
        y1 = int((self.y + self.view_h) // tile_px) + 2
        return range(x0, x1), range(y0, y1)


def move_with_collision(town: TownMap, rect: Tuple[float, float, float, float],
                        dx: float, dy: float) -> Tuple[float, float]:
    """Axis-separated movement: attempt X, then Y, so walls can be slid along."""
    x, y, w, h = rect
    if not town.rect_blocked((x + dx, y, w, h)):
        x += dx
    if not town.rect_blocked((x, y + dy, w, h)):
        y += dy
    return x, y
