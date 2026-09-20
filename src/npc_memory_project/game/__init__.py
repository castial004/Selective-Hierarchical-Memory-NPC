"""Playable pixel-art town built on the SHM-NPC research core.

Requires the optional ``game`` extra::

    pip install -e ".[game]"

Import is lazy so the rest of the package works without pygame installed.
"""

from typing import TYPE_CHECKING, Any

__all__ = ["Game", "main", "build_town", "GameContext", "Wallet"]

if TYPE_CHECKING:  # pragma: no cover
    from npc_memory_project.game.app import Game, main
    from npc_memory_project.game.conversation import GameContext
    from npc_memory_project.game.shop import Wallet
    from npc_memory_project.game.world_map import build_town


def __getattr__(name: str) -> Any:  # PEP 562: keep pygame optional
    if name in {"Game", "main"}:
        from npc_memory_project.game import app
        return getattr(app, name)
    if name == "GameContext":
        from npc_memory_project.game.conversation import GameContext
        return GameContext
    if name == "Wallet":
        from npc_memory_project.game.shop import Wallet
        return Wallet
    if name == "build_town":
        from npc_memory_project.game.world_map import build_town
        return build_town
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
