"""Pixel-art specifications: palettes and hand-authored 16x16 sprites.

Kept free of pygame so the artwork can be validated in tests without a display
(``validate_specs()`` checks every sprite is a well-formed rectangle drawn only
from palette keys).

Characters are not hand-authored per direction/frame -- they are composed at
draw time from a shared body plan with per-NPC colours and accessories
(see ``game/characters.py``), which keeps 4 NPCs x 4 directions x 2 frames
consistent instead of 32 hand-drawn sheets.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence

# --------------------------------------------------------------------- palette
# 4-tuples are RGBA; "." is fully transparent.
PALETTE: Dict[str, tuple] = {
    ".": (0, 0, 0, 0),
    "k": (26, 24, 34, 255),        # outline
    "K": (52, 48, 68, 255),        # dark shade
    "e": (240, 238, 232, 255),     # near white
    "w": (248, 250, 255, 255),     # white
    "W": (198, 206, 224, 255),     # light grey
    "s": (208, 214, 228, 255),     # stone light
    "S": (152, 160, 180, 255),     # stone dark
    "G": (98, 172, 88, 255),       # grass light
    "g": (66, 130, 60, 255),       # grass mid
    "h": (46, 96, 46, 255),        # grass dark
    "n": (116, 184, 108, 255),     # leaf light
    "N": (74, 132, 76, 255),       # leaf dark
    "d": (154, 118, 76, 255),      # dirt light
    "D": (120, 88, 56, 255),       # dirt dark
    "y": (232, 194, 104, 255),     # wood light
    "Y": (172, 130, 60, 255),      # wood dark
    "r": (178, 74, 60, 255),       # roof red
    "R": (132, 52, 46, 255),       # roof dark red
    "A": (142, 58, 66, 255),       # awning stripe / deep blossom
    "b": (86, 134, 202, 255),      # blue
    "B": (50, 86, 150, 255),       # blue dark
    "f": (234, 190, 150, 255),     # skin
    "F": (198, 150, 112, 255),     # skin shadow
    "c": (58, 54, 76, 255),        # cloth dark
    "C": (96, 92, 122, 255),       # cloth mid
    "o": (242, 162, 66, 255),      # orange
    "v": (158, 98, 182, 255),      # purple
    "a": (214, 74, 90, 255),       # accent red
    "t": (38, 78, 66, 255),        # teal dark
    "u": (255, 214, 120, 255),     # warm light (lantern/window)
}


# ---------------------------------------------------------------------- tiles
# Every spec: exactly 16 strings of exactly 16 palette keys.
TILE_SPECS: Dict[str, List[str]] = {
    "tree": [
        "................",
        "................",
        ".....NNNNn......",
        "...NNnnnnNN.....",
        "..NnnGGGGnnnN...",
        ".NnnGGGgGGnnnN..",
        ".NnnGGgggGnnNN..",
        ".NnnnGggggnnnN..",
        "..NnnnnggnnnN...",
        "....NNnngnNN....",
        ".......dD.......",
        ".......dD.......",
        "......ddDD......",
        ".......dD.......",
        "......dDDd......",
        "................",
    ],
    "wall": [
        "kkkkkkkkkkkkkkkk",
        "kyyyyyyyyyyyyyyk",
        "kyYYYYYYYYYYYYyk",
        "kyyyyyyyyyyyyyyk",
        "kyyyykkyyyykkyyk",
        "kyyyykkyyyykkyyk",
        "kyYYYYYYYYYYYYyk",
        "kyyyyyyyyyyyyyyk",
        "kyYYYYYYYYYYYYyk",
        "kyyyykkyyyykkyyk",
        "kyyyykkyyyykkyyk",
        "kyyyyyyyyyyyyyyk",
        "kyYYYYYYYYYYYYyk",
        "kyyyyyyyyyyyyyyk",
        "kyYYYYYYYYYYYYyk",
        "kkkkkkkkkkkkkkkk",
    ],
    "roof": [
        "kkkkkkkkkkkkkkkk",
        "krrrrrrrrrrrrrrk",
        "krRrrRrrRrrRrrRk",
        "krrrrrrrrrrrrrrk",
        "kRrrRrrRrrRrrRrk",
        "krrrrrrrrrrrrrrk",
        "krRrrRrrRrrRrrRk",
        "krrrrrrrrrrrrrrk",
        "kRrrRrrRrrRrrRrk",
        "krrrrrrrrrrrrrrk",
        "krRrrRrrRrrRrrRk",
        "krrrrrrrrrrrrrrk",
        "kRrrRrrRrrRrrRrk",
        "krrrrrrrrrrrrrrk",
        "kRRRRRRRRRRRRRRk",
        "kkkkkkkkkkkkkkkk",
    ],
    "door": [
        "kkkkkkkkkkkkkkkk",
        "kYYYYYYYYYYYYYYk",
        "kYyyyyyyyyyyyyYk",
        "kYyYYYYYYYYYYyYk",
        "kYyYddddddddYyYk",
        "kYyYdDDDDDDdYyYk",
        "kYyYdDyyyyDdYyYk",
        "kYyYdDyKKyDdYyYk",
        "kYyYdDyKKyDdYyYk",
        "kYyYdDyyyyDdYyYk",
        "kYyYdDDDDDDdYyYk",
        "kYyYddddddddYyYk",
        "kYyYYYYYYYYYYyYk",
        "kYyyyyyyyyyyyyYk",
        "kYYYYYYYYYYYYYYk",
        "kkkkkkkkkkkkkkkk",
    ],
    "stall": [
        "kkkkkkkkkkkkkkkk",
        "kaaaaaaaaaaaaaak",
        "kaAAAAAAAAAAAAak",
        "kaaaaaaaaaaaaaak",
        "kaWWWWWWWWWWWWak",
        "kaWWWWWWWWWWWWak",
        "kkkkkkkkkkkkkkkk",
        "kY............Yk",
        "kY............Yk",
        "kY...yyyyyy...Yk",
        "kY..yyYYYYyy..Yk",
        "kY..yyyyyyyy..Yk",
        "kY.YyyyyyyyyY.Yk",
        "kY.YyyyyyyyyY.Yk",
        "kY.YYYYYYYYYY.Yk",
        "kkkkkkkkkkkkkkkk",
    ],
    "well": [
        "................",
        "....kkkkkkkk....",
        "..kkSSSSSSSSkk..",
        ".kSSssssssssSSk.",
        ".kSssSSSSSSssSk.",
        ".kSsSbbbbbbSsSk.",
        ".kSsSbBBBBbSsSk.",
        ".kSsSbBBBBbSsSk.",
        ".kSsSbbbbbbSsSk.",
        ".kSssSSSSSSssSk.",
        ".kSSssssssssSSk.",
        "..kkSSSSSSSSkk..",
        "....kkkkkkkk....",
        "................",
        "................",
        "................",
    ],
    "sign": [
        "................",
        "................",
        "..kkkkkkkkkkk...",
        "..kyyyyyyyyyk...",
        "..kyYYYYYYYyk...",
        "..kyykwkwkyyk...",
        "..kyYYYYYYYyk...",
        "..kyykwkwkyyk...",
        "..kyYYYYYYYyk...",
        "..kkkkkkkkkkk...",
        "......kdk.......",
        "......kdk.......",
        "......kdk.......",
        ".....kkdkk......",
        "................",
        "................",
    ],
    "fence": [
        "................",
        "................",
        "..Y..........Y..",
        ".kYk........kYk.",
        ".kYk........kYk.",
        "kYYYYYYYYYYYYYYk",
        "kyyyyyyyyyyyyyyk",
        "kYYYYYYYYYYYYYYk",
        ".kYk........kYk.",
        ".kYk........kYk.",
        "kYYYYYYYYYYYYYYk",
        "kyyyyyyyyyyyyyyk",
        "kYYYYYYYYYYYYYYk",
        ".kYk........kYk.",
        ".kYk........kYk.",
        "................",
    ],
    "crate": [
        "................",
        "................",
        "..kkkkkkkkkkk...",
        "..kyyyyyyyyyk...",
        "..kyYYYYYYYyk...",
        "..kyYkkkkkYyk...",
        "..kyYkYYYkYyk...",
        "..kyYkYyYkYyk...",
        "..kyYkYYYkYyk...",
        "..kyYkkkkkYyk...",
        "..kyYYYYYYYyk...",
        "..kyyyyyyyyyk...",
        "..kkkkkkkkkkk...",
        "................",
        "................",
        "................",
    ],
    "barrel": [
        "................",
        "....kkkkkk......",
        "...kyyyyyyk.....",
        "..kyYYYYYYyk....",
        "..kYkkkkkkYk....",
        "..kyyyyyyyyk....",
        "..kYkkkkkkYk....",
        "..kyyyyyyyyk....",
        "..kYkkkkkkYk....",
        "..kyyyyyyyyk....",
        "..kYkkkkkkYk....",
        "...kyyyyyyk.....",
        "....kkkkkk......",
        "................",
        "................",
        "................",
    ],
    "flower": [
        "................",
        "................",
        "................",
        "................",
        "................",
        ".....a..........",
        "....aAa....v....",
        ".....a....vAv...",
        "..........v.v...",
        "....hh....h.....",
        "...hhh...hhh....",
        "....h......h....",
        "................",
        "................",
        "................",
        "................",
    ],
}


def validate_specs(specs: Mapping[str, Sequence[str]] | None = None,
                   palette: Mapping[str, tuple] | None = None,
                   size: int = 16) -> None:
    """Raise ValueError if any sprite is ragged or uses an unknown colour."""
    specs = TILE_SPECS if specs is None else specs
    palette = PALETTE if palette is None else palette

    for name, rows in specs.items():
        if len(rows) != size:
            raise ValueError(f"sprite {name!r} has {len(rows)} rows, expected {size}")
        for index, row in enumerate(rows):
            if len(row) != size:
                raise ValueError(
                    f"sprite {name!r} row {index} has {len(row)} columns, expected {size}"
                )
            unknown = set(row) - set(palette)
            if unknown:
                raise ValueError(f"sprite {name!r} row {index} uses unknown keys {sorted(unknown)}")
