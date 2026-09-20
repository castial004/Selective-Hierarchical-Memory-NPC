"""Web layer: HTTP server plus the canvas simulator / XAI inspector.

Import is lazy so ``python -m npc_memory_project.web.server`` does not import the
module twice (which produced a runpy RuntimeWarning in v0.2).
"""

from typing import TYPE_CHECKING, Any

__all__ = ["create_server", "run_server", "GameWebHandler", "main"]

if TYPE_CHECKING:  # pragma: no cover
    from npc_memory_project.web.server import (
        GameWebHandler,
        create_server,
        main,
        run_server,
    )


def __getattr__(name: str) -> Any:  # PEP 562
    if name in __all__:
        from npc_memory_project.web import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
