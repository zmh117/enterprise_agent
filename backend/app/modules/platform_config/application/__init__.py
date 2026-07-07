from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import PlatformConfigService

__all__ = ["PlatformConfigService"]


def __getattr__(name: str) -> object:
    if name == "PlatformConfigService":
        from .service import PlatformConfigService

        return PlatformConfigService
    raise AttributeError(name)
