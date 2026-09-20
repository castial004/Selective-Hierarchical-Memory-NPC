"""Display / scaling tests (headless)."""

from __future__ import annotations

import os

import pytest

pygame = pytest.importorskip("pygame", reason="game extra not installed")

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from npc_memory_project.game.display import LOGICAL_SIZE, WINDOW_STEPS, Display  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pygame.display.init()
    yield


def test_default_window_matches_the_logical_size():
    display = Display()
    assert display.window_size == LOGICAL_SIZE
    assert display.scale == 1.0
    assert display.dest_size == LOGICAL_SIZE
    assert (display.offset_x, display.offset_y) == (0.0, 0.0)


def test_scale_parameter_enlarges_the_window():
    display = Display(scale=2.0)
    assert display.window_size == (1920, 1280)
    assert display.scale > 1.0


def test_explicit_window_size_is_respected_over_scale():
    display = Display(window_size=(1600, 900))
    assert display.window_size == (1600, 900)
    # a 16:9 window showing a 3:2 frame letterboxes left and right, keeping the
    # full height
    assert display.dest_size == (1350, 900)
    assert display.offset_y == 0.0
    assert display.offset_x > 0


def test_resize_keeps_aspect_and_letterboxes():
    display = Display()
    display.resize((1920, 1200))
    assert display.window_size == (1920, 1200)
    assert display.dest_size == (1800, 1200)
    assert display.offset_x == pytest.approx(60.0)
    assert display.offset_y == pytest.approx(0.0)


def test_resize_never_goes_below_a_usable_minimum():
    display = Display()
    display.resize((10, 10))
    assert display.window_size[0] >= 320 and display.window_size[1] >= 240


def test_mouse_mapping_round_trips_and_clamps():
    display = Display()
    display.resize((1920, 1200))
    for logical in ((0, 0), (480, 320), (959, 639)):
        assert display.to_logical(display.to_window(logical)) == logical

    # a click inside the letterbox clamps to the frame edge rather than going
    # negative, and a click past the far edge clamps to the last logical pixel
    # (window y 600 at 1.875x -> logical y 320)
    assert display.to_logical((-40, 600)) == (0, 320)
    assert display.to_logical((5000, 5000)) == (959, 639)


def test_cycle_window_scale_walks_the_presets_and_wraps():
    display = Display()
    seen = [display.cycle_window_scale() for _ in range(len(WINDOW_STEPS) + 1)]
    assert seen == [1.25, 1.5, 2.0, 1.0, 1.25]      # steps up, then wraps
    assert display.window_size == (1200, 800)


def test_fullscreen_toggle_is_safe_when_unsupported():
    display = Display()
    initial = display.fullscreen
    assert display.toggle_fullscreen() == initial   # dummy driver: no-op
    if not display.fullscreen_supported:
        assert display.window_size == (960, 640)


def test_present_scales_into_the_window():
    display = Display()
    display.resize((1920, 1280))
    display.logical.fill((10, 20, 30))
    display.present()
    assert display.window.get_size() == (1920, 1280)
    # the frame is stretched to fill: sample a point inside the drawn area
    assert display.window.get_at((960, 640))[:3] == (10, 20, 30)
