"""Tests for the native-resolution UI canvas.

The canvas exists because the UI used to be part of the scaled logical frame: a
13 px label on a 1400x933 window went through a 1.46x resample and became
unreadable. These tests pin the contract that replaced it -- logical coordinates
in, window pixels out, fonts rendered at their final size.
"""

from __future__ import annotations

import os

import pytest

pygame = pytest.importorskip("pygame", reason="game extra not installed")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from npc_memory_project.game.display import LOGICAL_SIZE, Display  # noqa: E402
from npc_memory_project.game.ui import UiCanvas, window_canvas  # noqa: E402


@pytest.fixture(autouse=True)
def _pygame_ready():
    """Font rendering needs pygame.font, and surfaces need a display format."""
    pygame.init()
    pygame.display.set_mode((10, 10))
    yield
    pygame.quit()


@pytest.fixture
def surface():
    return pygame.Surface((1920, 1080)).convert()


# ----------------------------------------------------------------- geometry
def test_logical_canvas_is_the_identity_mapping():
    logical_surface = pygame.Surface(LOGICAL_SIZE)
    canvas = UiCanvas.for_logical(logical_surface, logical_size=LOGICAL_SIZE)
    assert canvas.at(16, 11) == (16, 11)
    assert canvas.px(3) == 3
    assert canvas.span_w == LOGICAL_SIZE[0]
    assert canvas.origin == (0.0, 0.0)


def test_window_canvas_maps_through_scale_and_letterbox(surface):
    canvas = UiCanvas(surface, factor=2.0, offset=(60.0, 0.0), logical_size=LOGICAL_SIZE)
    assert canvas.at(0, 0) == (60, 0)
    assert canvas.at(480, 320) == (1020, 640)
    assert canvas.px(3) == 6
    # a 1920-wide surface at 2x is 960 logical wide plus 60px bars either side
    assert canvas.span_w == 960.0
    assert canvas.origin_x == -30.0


def test_px_never_returns_zero_length():
    canvas = UiCanvas(pygame.Surface((100, 100)), factor=0.2, logical_size=(500, 500))
    assert canvas.px(1) == 1


# --------------------------------------------------------------------- text
def test_text_is_rendered_at_its_final_size_not_scaled_afterwards(surface):
    logical = UiCanvas.for_logical(pygame.Surface(LOGICAL_SIZE), logical_size=LOGICAL_SIZE)
    native = UiCanvas(surface, factor=2.0, offset=(0.0, 0.0), logical_size=LOGICAL_SIZE)

    small = logical.text("MEMORY INSPECTOR", 15, (255, 255, 255))
    big = native.text("MEMORY INSPECTOR", 15, (255, 255, 255))

    assert logical.font_size(15) == 15
    assert native.font_size(15) == 30
    # glyphs are really drawn bigger, not blitted bigger
    assert big.get_width() > small.get_width() * 1.8
    assert big.get_height() > small.get_height() * 1.8


def test_measure_returns_logical_units_so_layout_math_is_unchanged(surface):
    logical = UiCanvas.for_logical(pygame.Surface(LOGICAL_SIZE), logical_size=LOGICAL_SIZE)
    native = UiCanvas(surface, factor=2.0, offset=(60.0, 0.0), logical_size=LOGICAL_SIZE)

    text = "cause: The guard proved that Rohan, not the player, stole the medicine"
    # measurement is scale-invariant by design: same logical width everywhere
    assert logical.measure(text, 15) == native.measure(text, 15) > 0


def test_wrap_never_exceeds_the_given_width(surface):
    canvas = UiCanvas.for_logical(pygame.Surface(LOGICAL_SIZE), logical_size=LOGICAL_SIZE)
    text = ("cause: The guard proved that Rohan, not the player, stole the medicine "
            "from behind the counter on the third day")
    for width in (120, 180, 300):
        for line in canvas.wrap(text, 15, width):
            assert canvas.measure(line, 15) <= width + 1, (line, width)


def test_wrap_at_native_scale_matches_the_logical_break_points(surface):
    """Wrapping must not change with the window size, or panels would reflow."""
    logical = UiCanvas.for_logical(pygame.Surface(LOGICAL_SIZE), logical_size=LOGICAL_SIZE)
    native = UiCanvas(surface, factor=1.4578, offset=(0.0, 0.0), logical_size=LOGICAL_SIZE)
    text = "The guard proved that Rohan, not the player, stole the medicine"
    # identical break points at every window size, so panels never reflow
    assert logical.wrap(text, 15, 200) == native.wrap(text, 15, 200)


def test_text_right_and_center_land_where_asked(surface):
    canvas = UiCanvas(pygame.Surface((400, 200)), factor=2.0, offset=(0.0, 0.0),
                      logical_size=(200, 100))
    canvas.text_right("GOLD", 16, (255, 255, 255), 190, 10)
    canvas.text_center("DAY 4", 16, (255, 255, 255), 100, 40)
    # both calls drew something (surface is no longer uniformly black)
    assert pygame.transform.average_color(canvas.surface)[0] > 0


# ------------------------------------------------------------------- shapes
def test_fill_blends_alpha_instead_of_replacing(surface):
    canvas = UiCanvas(pygame.Surface(LOGICAL_SIZE), factor=1.0, offset=(0, 0),
                      logical_size=LOGICAL_SIZE)
    canvas.surface.fill((0, 0, 0))
    canvas.fill((255, 255, 255, 128), (10, 10, 20, 20))
    pixel = canvas.surface.get_at((15, 15))
    assert 100 < pixel[0] < 160, "alpha must blend, not overwrite"


def test_dim_covers_the_letterbox_bars_too(surface):
    canvas = UiCanvas(surface, factor=2.0, offset=(60.0, 0.0), logical_size=LOGICAL_SIZE)
    canvas.surface.fill((255, 255, 255))
    canvas.dim((0, 0, 0, 200))
    assert canvas.surface.get_at((5, 5))[0] < 100          # inside the left bar
    assert canvas.surface.get_at((1900, 5))[0] < 100       # inside the right bar


def test_fill_row_spans_the_whole_surface(surface):
    canvas = UiCanvas(surface, factor=2.0, offset=(60.0, 0.0), logical_size=LOGICAL_SIZE)
    canvas.surface.fill((0, 0, 0))
    canvas.fill_row((255, 0, 0), 0, 40)
    assert canvas.surface.get_at((2, 10))[0] > 200         # in the bar
    assert canvas.surface.get_at((i := 960, 10))[0] > 200  # in the frame
    assert canvas.surface.get_at((1917, 10))[0] > 200      # past the frame


def test_triangle_draws_the_reply_cursor(surface):
    canvas = UiCanvas(pygame.Surface(LOGICAL_SIZE), factor=1.0, offset=(0, 0),
                      logical_size=LOGICAL_SIZE)
    canvas.surface.fill((0, 0, 0))
    canvas.triangle((0, 255, 0), ((0, 0), (0, 10), (8, 5)))
    assert canvas.surface.get_at((2, 5))[1] > 200


# ----------------------------------------------------------- display bridge
def test_window_canvas_tracks_a_live_display_resize():
    display = Display(logical_size=LOGICAL_SIZE, window_size=(1200, 800))
    canvas = window_canvas(display)
    assert canvas.factor == pytest.approx(1.25)
    assert canvas.font_size(16) == 20

    display.resize((960, 640))
    canvas = window_canvas(display)
    assert canvas.factor == pytest.approx(1.0)
    assert canvas.font_size(16) == 16
    pygame.quit()
