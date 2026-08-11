from __future__ import annotations

from typing import TYPE_CHECKING

from .repository import ModelConnectionRepository

if TYPE_CHECKING:
    from .runtime_probe import RuntimeModelProbeClient, RuntimeModelProbeSettings

__all__ = [
    "ModelConnectionRepository",
    "RuntimeModelProbeClient",
    "RuntimeModelProbeSettings",
]


def __getattr__(name: str) -> object:
    if name in {"RuntimeModelProbeClient", "RuntimeModelProbeSettings"}:
        from .runtime_probe import RuntimeModelProbeClient, RuntimeModelProbeSettings

        return {
            "RuntimeModelProbeClient": RuntimeModelProbeClient,
            "RuntimeModelProbeSettings": RuntimeModelProbeSettings,
        }[name]
    raise AttributeError(name)
