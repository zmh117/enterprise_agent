from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Mapping


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PLATFORM = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}/[a-z0-9][a-z0-9._-]{0,31}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class BuildIdentityError(ValueError):
    """Safe configuration error for non-secret build provenance."""


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    component: str
    source_revision: str
    build_id: str
    platform: str
    image_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("component", "source_revision", "build_id"):
            value = getattr(self, name)
            if _IDENTIFIER.fullmatch(value) is None:
                raise BuildIdentityError(f"Invalid build identity field: {name}")
        if _PLATFORM.fullmatch(self.platform) is None:
            raise BuildIdentityError("Invalid build identity field: platform")
        if self.image_digest and _IMAGE_DIGEST.fullmatch(self.image_digest) is None:
            raise BuildIdentityError("Invalid build identity field: image_digest")

    def to_dict(self) -> dict[str, str]:
        value = {
            "component": self.component,
            "source_revision": self.source_revision,
            "build_id": self.build_id,
            "platform": self.platform,
        }
        if self.image_digest:
            value["image_digest"] = self.image_digest
        return value

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        expected_component: str,
    ) -> BuildIdentity:
        allowed = {
            "component",
            "source_revision",
            "build_id",
            "platform",
            "image_digest",
        }
        if set(value) - allowed:
            raise BuildIdentityError("Unknown build identity field")
        component = str(value.get("component") or "")
        if component != expected_component:
            raise BuildIdentityError("Build identity component mismatch")
        return cls(
            component=component,
            source_revision=str(value.get("source_revision") or ""),
            build_id=str(value.get("build_id") or ""),
            platform=str(value.get("platform") or ""),
            image_digest=str(value.get("image_digest") or ""),
        )


def build_identity_from_environment(
    component: str,
    environment: Mapping[str, str] | None = None,
) -> BuildIdentity:
    source = environment if environment is not None else os.environ
    return BuildIdentity(
        component=component,
        source_revision=str(source.get("BUILD_SOURCE_REVISION") or ""),
        build_id=str(source.get("BUILD_ID") or ""),
        platform=str(source.get("BUILD_PLATFORM") or ""),
        image_digest=str(source.get("BUILD_IMAGE_DIGEST") or ""),
    )
