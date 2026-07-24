from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class VerifiedOnesIdentity:
    user_uuid: str
    display_name: str
    team_uuids: tuple[str, ...]
    verified_at: str

    @classmethod
    def create(
        cls,
        *,
        user_uuid: str,
        display_name: str,
        team_uuids: tuple[str, ...],
    ) -> VerifiedOnesIdentity:
        return cls(
            user_uuid=user_uuid,
            display_name=display_name,
            team_uuids=team_uuids,
            verified_at=datetime.now(UTC).isoformat(),
        )


class OnesIdentityVerifier(Protocol):
    @property
    def available(self) -> bool: ...

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity: ...
