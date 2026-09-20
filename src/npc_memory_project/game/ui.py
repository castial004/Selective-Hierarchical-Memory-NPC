"""The UI pass: text and panels drawn at the window's real resolution.

Why this module exists
----------------------
The game used to draw everything -- world *and* UI -- into a fixed 960x640
surface and then scale that surface into the window. Pixel art survives that
(blocky is the point) but text does not: a 13 px font resampled by 1.46 turns to
mush, which is exactly what the memory inspector looked like on a resized window
and in fullscreen.

So rendering is now split in two passes:

1. **world pass** -- tiles, characters, shadows, drawn to the logical surface and
   scaled by :class:`~npc_memory_project.game.display.Display` with nearest
   neighbour where it can. Blocky by design.
2. **UI pass** -- HUD, dialogue, shop, inspector, help, world labels, drawn
   *after* presenting, straight onto the window, with every font rendered at its
   final pixel size (``logical_size x factor``). Crisp at 1x, at 1.46x, at 2x and
   in fullscreen, because nothing is ever resampled.

:class:`UiCanvas` is the coordinate system for pass 2. Callers keep writing the
logical layout they always wrote -- ``(16, 11)`` for the HUD, ``size 13`` for
footnote text -- and the canvas turns those into window pixels. In logical mode
(``factor=1``) it is byte-for-byte the old behaviour, which is what the
``--screenshot`` captures use.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import pygame

from npc_memory_project.game.assets import font_for

Color = Tuple[int, ...]


class UiCanvas:
    """Draws UI in logical coordinates at the surface's real pixel size."""

    def __init__(
        self,
        surface: pygame.Surface,
        factor: float = 1.0,
        offset: Tuple[float, float] = (0.0, 0.0),
        logical_size: Optional[Tuple[int, int]] = None,
        antialias: bool = True,
    ) -> None:
        self.surface = surface
        self.factor = float(factor)
        self.offset = (float(offset[0]), float(offset[1]))
        self.logical_size = logical_size or surface.get_size()
        self.width, self.height = self.logical_size
        self.antialias = antialias

    # The surface may be wider than the logical frame (letterbox bars). These
    # give the logical rectangle the *whole* surface covers, so full-screen
    # panels can spread out instead of hugging a letterboxed column.
    @property
    def origin(self) -> Tuple[float, float]:
        return (-self.offset[0] / self.factor, -self.offset[1] / self.factor)

    @property
    def origin_x(self) -> float:
        return self.origin[0]

    @property
    def origin_y(self) -> float:
        return self.origin[1]

    @property
    def span_w(self) -> float:
        return self.surface.get_width() / self.factor

    @property
    def span_h(self) -> float:
        return self.surface.get_height() / self.factor

    # ------------------------------------------------------------- geometry
    def at(self, x: float, y: float) -> Tuple[int, int]:
        """Logical point -> surface pixel."""
        return (
            int(round(x * self.factor + self.offset[0])),
            int(round(y * self.factor + self.offset[1])),
        )

    def px(self, value: float, minimum: int = 1) -> int:
        """Logical length -> surface pixels, never below ``minimum``."""
        return max(minimum, int(round(value * self.factor)))

    def rect_of(self, rect) -> pygame.Rect:
        x, y = self.at(rect[0], rect[1])
        return pygame.Rect(x, y, self.px(rect[2]), self.px(rect[3]))

    # ----------------------------------------------------------------- text
    def font_size(self, size: int) -> int:
        """Final pixel height of a logical ``size`` font on this canvas."""
        return max(9, int(round(size * self.factor)))

    def text(self, value: str, size: int, color: Color, bold: bool = False) -> pygame.Surface:
        """Render text at its final size -- never scaled afterwards."""
        return font_for(self.font_size(size), bold).render(value, self.antialias, color)

    def _logical_font(self, size: int, bold: bool = False):
        """A font at the *logical* size, used for measurement only.

        Measurement deliberately ignores ``factor``: if it scaled with the window,
        a panel would re-wrap into a different shape every time the player resized
        it. Layout stays identical at every size; only the rendering resolution
        changes.
        """
        return font_for(size, bold)

    def measure(self, value: str, size: int, bold: bool = False) -> int:
        """Width of ``value`` in *logical* units, independent of window scale."""
        return self._logical_font(size, bold).size(value)[0]

    def wrap(self, value: str, size: int, max_width: int) -> List[str]:
        """Greedy word wrap against the logical font metrics."""
        font = self._logical_font(size, False)
        words = value.split()
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

    def clip_text(self, value: str, size: int, color: Color, max_width: int,
                  bold: bool = False, ellipsis: str = "…") -> pygame.Surface:
        """Render ``value`` truncated with an ellipsis to ``max_width`` logical px."""
        if self.measure(value, size, bold) > max_width:
            while value and self.measure(value + ellipsis, size, bold) > max_width:
                value = value[:-1]
            value = value.rstrip() + ellipsis
        return self.text(value, size, color, bold)

    # ---------------------------------------------------------- composition
    def blit(self, surface: pygame.Surface, pos: Tuple[float, float]) -> None:
        self.surface.blit(surface, self.at(pos[0], pos[1]))

    def blit_right(self, surface: pygame.Surface, right_x: float, y: float) -> None:
        self.surface.blit(surface, self.at(right_x - surface.get_width() / self.factor, y))

    def blit_center(self, surface: pygame.Surface, center_x: float, y: float) -> None:
        self.surface.blit(surface, self.at(center_x - surface.get_width() / (2 * self.factor), y))

    def text_right(self, value: str, size: int, color: Color, right_x: float, y: float,
                   bold: bool = False) -> pygame.Surface:
        surface = self.text(value, size, color, bold)
        self.blit_right(surface, right_x, y)
        return surface

    def text_center(self, value: str, size: int, color: Color, center_x: float, y: float,
                    bold: bool = False) -> pygame.Surface:
        surface = self.text(value, size, color, bold)
        self.blit_center(surface, center_x, y)
        return surface

    # -------------------------------------------------------------- shapes
    def fill(self, color: Color, rect: Sequence[float]) -> None:
        """Translucent-safe fill of a logical rect (alpha only blits, not draws)."""
        target = self.rect_of(rect)
        if target.width <= 0 or target.height <= 0:
            return
        if len(color) == 4 and color[3] < 255:
            patch = pygame.Surface(target.size, pygame.SRCALPHA)
            patch.fill(color)
            self.surface.blit(patch, target.topleft)
        else:
            pygame.draw.rect(self.surface, color[:3], target)

    def rect(self, color: Color, rect: Sequence[float], width: int = 0,
             radius: int = 0) -> None:
        target = self.rect_of(rect)
        if len(color) == 4 and color[3] < 255 and width == 0:
            self.fill(color, rect)
            return
        pygame.draw.rect(self.surface, color[:3], target,
                         self.px(width) if width else 0,
                         border_radius=self.px(radius, minimum=0))

    def line(self, color: Color, start: Tuple[float, float], end: Tuple[float, float],
             width: int = 1) -> None:
        pygame.draw.line(self.surface, color[:3], self.at(*start), self.at(*end),
                         self.px(width))

    def triangle(self, color: Color, points, ) -> None:
        """Filled triangle from logical points.

        Used for the reply cursor: the glyph ``▶`` is not in pygame's default font
        and rendered as a tofu box on every platform, which looked like a bug in
        the dialogue box.
        """
        pygame.draw.polygon(self.surface, color[:3], [self.at(x, y) for x, y in points])

    def square(self, color: Color, x: float, y: float, size: float) -> None:
        pygame.draw.rect(self.surface, color[:3], self.rect_of((x, y, size, size)))

    def panel(self, rect: Sequence[float], fill: Color, edge: Optional[Color] = None,
              width: int = 3, radius: int = 10) -> pygame.Rect:
        """A translucent plate with a border, drawn in one allocation."""
        target = self.rect_of(rect)
        if target.width <= 0 or target.height <= 0:
            return target
        patch = pygame.Surface(target.size, pygame.SRCALPHA)
        patch.fill(fill)
        if edge is not None:
            pygame.draw.rect(patch, edge[:3] if len(edge) == 3 else edge,
                             patch.get_rect(), self.px(width),
                             border_radius=self.px(radius, minimum=0))
        self.surface.blit(patch, target.topleft)
        return target

    def fill_row(self, color: Color, y: float, height: float) -> None:
        """Fill a horizontal band across the *whole* canvas, letterbox included.

        The HUD is the reason: in fullscreen the frame is letterboxed left and
        right, and a HUD bar that stopped at the frame edge would look like a
        mistake rather than a design.
        """
        top = self.at(0.0, y)[1]
        target = pygame.Rect(0, top, self.surface.get_width(), self.px(height))
        if len(color) == 4 and color[3] < 255:
            patch = pygame.Surface(target.size, pygame.SRCALPHA)
            patch.fill(color)
            self.surface.blit(patch, target.topleft)
        else:
            self.surface.fill(color[:3], target)

    def dim(self, color: Color) -> None:
        """Dim the whole canvas -- the window, letterbox bars included."""
        patch = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        patch.fill(color)
        self.surface.blit(patch, (0, 0))

    def sprite(self, surface: pygame.Surface, pos: Tuple[float, float],
               logical_size: Optional[int] = None) -> None:
        """Blit sprite art, nearest-neighbour, at ``logical_size`` logical px."""
        if logical_size is not None:
            target = self.px(logical_size)
            if target != surface.get_width():
                surface = pygame.transform.scale(surface, (target, target))
        self.surface.blit(surface, self.at(pos[0], pos[1]))

    # -------------------------------------------------------------- factory
    @classmethod
    def for_logical(cls, surface: pygame.Surface,
                    logical_size: Optional[Tuple[int, int]] = None) -> "UiCanvas":
        """Pass-2 canvas that draws straight into the logical surface."""
        return cls(surface, factor=1.0, offset=(0.0, 0.0), logical_size=logical_size)


def window_canvas(display) -> UiCanvas:
    """Pass-2 canvas bound to a live :class:`Display` window.

    Uses the display's own scale and letterbox offset, so logical coordinates land
    exactly where the scaled world put them.
    """
    return UiCanvas(
        display.window,
        factor=display.scale,
        offset=(display.offset_x, display.offset_y),
        logical_size=display.logical_size,
    )
