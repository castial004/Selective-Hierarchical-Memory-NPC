"""Evaluation package: seeded scenario harness + benchmark driver.

Imports are lazy so that ``python -m npc_memory_project.evaluation.benchmark``
does not import the module twice (which produced a runpy RuntimeWarning in v0.2).
"""

from typing import TYPE_CHECKING, Any

__all__ = [
    "FlatMemoryRetrieval",
    "Scenario",
    "build_scenarios",
    "evaluate",
    "run_paper_benchmark",
    "token_proxy",
]

if TYPE_CHECKING:  # pragma: no cover
    from npc_memory_project.evaluation.benchmark import run_paper_benchmark, token_proxy
    from npc_memory_project.evaluation.harness import (
        FlatMemoryRetrieval,
        Scenario,
        build_scenarios,
        evaluate,
    )


def __getattr__(name: str) -> Any:  # PEP 562 lazy attribute access
    if name in {"run_paper_benchmark", "token_proxy"}:
        from npc_memory_project.evaluation import benchmark

        return getattr(benchmark, name)
    if name in {"FlatMemoryRetrieval", "Scenario", "build_scenarios", "evaluate"}:
        from npc_memory_project.evaluation import harness

        return getattr(harness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
