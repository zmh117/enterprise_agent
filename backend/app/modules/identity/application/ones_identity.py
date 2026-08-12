from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class VerifiedOnesTeam:
    id: str
    name: str = ""


@dataclass(frozen=True)
class VerifiedOnesIdentity:
    user_uuid: str
    display_name: str
    teams: tuple[VerifiedOnesTeam, ...]
    verified_at: str
    token: str = field(repr=False)

    def __repr__(self) -> str:
        return (
            "VerifiedOnesIdentity("
            f"user_uuid={self.user_uuid!r}, display_name={self.display_name!r}, "
            f"teams={self.teams!r}, verified_at={self.verified_at!r}, token=<hidden>)"
        )

    @property
    def team_uuids(self) -> tuple[str, ...]:
        return tuple(team.id for team in self.teams)

    @classmethod
    def create(
        cls,
        *,
        user_uuid: str,
        display_name: str,
        team_uuids: tuple[str, ...] = (),
        teams: tuple[VerifiedOnesTeam, ...] = (),
        token: str,
    ) -> VerifiedOnesIdentity:
        normalized: list[VerifiedOnesTeam] = []
        seen: set[str] = set()
        for team in (*teams, *(VerifiedOnesTeam(id=value) for value in team_uuids)):
            team_id = team.id.strip()
            if not team_id or team_id in seen:
                continue
            seen.add(team_id)
            normalized.append(VerifiedOnesTeam(id=team_id, name=team.name.strip()))
        return cls(
            user_uuid=user_uuid,
            display_name=display_name,
            teams=tuple(normalized),
            verified_at=datetime.now(UTC).isoformat(),
            token=token,
        )


class OnesIdentityVerifier(Protocol):
    @property
    def available(self) -> bool: ...

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity: ...
