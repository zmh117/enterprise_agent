from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application.service import ModelConnectionService, UnavailableModelSecretProvider
    from .infrastructure import (
        ModelConnectionRepository,
        RuntimeModelProbeClient,
        RuntimeModelProbeSettings,
    )

__all__ = [
    "ModelConnectionRepository",
    "ModelConnectionService",
    "RuntimeModelProbeClient",
    "RuntimeModelProbeSettings",
    "UnavailableModelSecretProvider",
]


def __getattr__(name: str) -> object:
    if name in {"ModelConnectionService", "UnavailableModelSecretProvider"}:
        from .application.service import ModelConnectionService, UnavailableModelSecretProvider

        return {
            "ModelConnectionService": ModelConnectionService,
            "UnavailableModelSecretProvider": UnavailableModelSecretProvider,
        }[name]
    if name in {
        "ModelConnectionRepository",
        "RuntimeModelProbeClient",
        "RuntimeModelProbeSettings",
    }:
        from .infrastructure import (
            ModelConnectionRepository,
            RuntimeModelProbeClient,
            RuntimeModelProbeSettings,
        )

        return {
            "ModelConnectionRepository": ModelConnectionRepository,
            "RuntimeModelProbeClient": RuntimeModelProbeClient,
            "RuntimeModelProbeSettings": RuntimeModelProbeSettings,
        }[name]
    raise AttributeError(name)
