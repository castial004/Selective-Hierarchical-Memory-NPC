"""Window and scaling management.

The game draws to a fixed *logical* surface (960x640) and this class presents it
in whatever window the player actually has -- windowed, resized, or fullscreen.
Everything inside the game keeps working in logical coordinates; only this layer
knows about the real window, letterboxing and mouse mapping.

That separation is what makes "make the UI bigger" a one-line change instead of
a re-layout: the window grows, every sprite and every line of text with it.

* ``F11``   toggle fullscreen
* ``F10``   cycle window size (1.0x / 1.25x / 1.5x / 2.0x of the logical size)
* dragging the window edge resizes live; the view scales to fit and letterboxes
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import pygame

LOGICAL_SIZE: Tuple[int, int] = (960, 640)
WINDOW_STEPS: Sequence[float] = (1.0, 1.25, 1.5, 2.0)


class Display:
    """Owns the real window and the mapping to/from logical coordinates."""

    def __init__(
        self,
        logical_size: Tuple[int, int] = LOGICAL_SIZE,
        scale: float = 1.0,
        fullscreen: bool = False,
        resizable: bool = True,
        window_size: Optional[Tuple[int, int]] = None,
        title: str = "Selective Hierarchical Memory — the town of Ashfen",
    ) -> None:
        if not pygame.display.get_init():
            pygame.display.init()
        self.logical_size = logical_size
        self.logical_w, self.logical_h = logical_size
        self.resizable = resizable
        self.fullscreen = False
        self.fullscreen_supported = pygame.display.get_driver() != "dummy"
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.dest_size = (self.logical_w, self.logical_h)
        # an explicit size wins over the scale factor (the window may have a
        # different aspect ratio, in which case the view letterboxes)
        self._windowed_size = window_size or (
            max(320, int(self.logical_w * scale)),
            max(240, int(self.logical_h * scale)),
        )
        # set_mode must come first: Surface.convert() needs a display format
        self.window = pygame.display.set_mode(self._windowed_size, self._flags())
        pygame.display.set_caption(title)
        self.logical = pygame.Surface(logical_size).convert()
        self._recompute()

    # ---------------------------------------------------------------- window
    def _flags(self) -> int:
        flags = 0
        if self.fullscreen:
            flags |= pygame.FULLSCREEN
        elif self.resizable:
            flags |= pygame.RESIZABLE
        return flags

    def resize(self, size: Tuple[int, int]) -> None:
        """Handle a window resize (drag, or a window manager event)."""
        width, height = max(320, int(size[0])), max(240, int(size[1]))
        if not self.fullscreen:
            self._windowed_size = (width, height)
        self.window = pygame.display.set_mode((width, height), self._flags())
        self._recompute()

    def toggle_fullscreen(self) -> bool:
        """Switch to exclusive fullscreen and back. Returns the new state."""
        if not self.fullscreen_supported:
            return self.fullscreen          # headless: nothing to toggle
        if self.fullscreen:
            self.fullscreen = False
            self.window = pygame.display.set_mode(self._windowed_size, self._flags())
        else:
            self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.fullscreen = True
        self._recompute()
        return self.fullscreen

    def cycle_window_scale(self, steps: Sequence[float] = WINDOW_STEPS) -> float:
        """Grow to the next preset window size, wrapping back to 1.0x."""
        if self.fullscreen:
            self.toggle_fullscreen()
        current = self._windowed_size[0] / self.logical_w
        ordered = sorted(steps)
        nxt = next((s for s in ordered if s > current + 0.01), ordered[0])
        self.resize((int(self.logical_w * nxt), int(self.logical_h * nxt)))
        return nxt

    # ---------------------------------------------------------------- layout
    def _recompute(self) -> None:
        win_w, win_h = self.window.get_size()
        self.scale = min(win_w / self.logical_w, win_h / self.logical_h)
        self.dest_size = (
            max(1, int(round(self.logical_w * self.scale))),
            max(1, int(round(self.logical_h * self.scale))),
        )
        self.offset_x = (win_w - self.dest_size[0]) / 2
        self.offset_y = (win_h - self.dest_size[1]) / 2

    @property
    def window_size(self) -> Tuple[int, int]:
        return self.window.get_size()

    def _is_integer_scale(self) -> bool:
        step = self.scale
        return abs(step - round(step)) < 1e-6 and round(step) >= 1

    # ----------------------------------------------------------- mapping
    def to_logical(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        """Map a window coordinate (e.g. a mouse click) into logical space."""
        x = (pos[0] - self.offset_x) / self.scale
        y = (pos[1] - self.offset_y) / self.scale
        # round rather than truncate: truncation loses the last pixel to
        # rounding error, so clicks at the edge of the frame missed their target
        x = min(max(0.0, round(x)), self.logical_w - 1)
        y = min(max(0.0, round(y)), self.logical_h - 1)
        return int(x), int(y)

    def to_window(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        """Inverse of :meth:`to_logical`, for tests and debug overlays."""
        return (
            round(pos[0] * self.scale + self.offset_x),
            round(pos[1] * self.scale + self.offset_y),
        )

    # ----------------------------------------------------------- presenting
    def present(self) -> None:
        """Scale the logical frame into the window and flip."""
        self.window.fill((0, 0, 0))                       # letterbox bars
        if self.dest_size == self.logical_size:
            scaled: Optional[pygame.Surface] = self.logical
        elif self._is_integer_scale() or self.scale < 1.0:
            # nearest-neighbour keeps pixel art crisp at whole-number and
            # down-scaled sizes
            scaled = pygame.transform.scale(self.logical, self.dest_size)
        else:
            scaled = pygame.transform.smoothscale(self.logical, self.dest_size)
        self.window.blit(scaled, (int(self.offset_x), int(self.offset_y)))
        pygame.display.flip()
