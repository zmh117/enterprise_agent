from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from app.shared.database import Database


def strict_business_scope_summary(
    database: Database,
    *,
    user_id: str,
    global_access: bool = False,
) -> dict[str, Any]:
    if global_access:
        return {"mode": "global", "grants": []}
    rows = database.execute(
        """
        select distinct e.code as environment_code,
               b.code as base_code, w.code as workshop_code
          from rbac_role_application_scope s
          join rbac_role_application_access aa
            on aa.id = s.application_access_id
          join rbac_role r on r.id = aa.role_id
          join rbac_user_role ur on ur.role_id = r.id
          join app_user u on u.id = ur.user_id
          join platform_environment e on e.id = s.environment_id
          left join platform_base b on b.id = s.base_id
          left join platform_workshop w on w.id = s.workshop_id
         where ur.user_id = ?
           and aa.status = 'enabled'
           and r.status = 'enabled'
           and ur.status = 'enabled'
           and u.status = 'enabled'
           and (ur.expires_at is null or ur.expires_at > ?)
         order by e.code, b.code, w.code
        """,
        (user_id, datetime.now(UTC).isoformat()),
    )
    return {
        "mode": "restricted",
        "grants": [
            {
                "effect": "allow",
                "environment": str(row["environment_code"]),
                "base": str(row.get("base_code") or "*"),
                "workshop": str(row.get("workshop_code") or "*"),
            }
            for row in rows
        ],
    }


class AdminScope:
    def __init__(self, summary: dict[str, Any], user_id: str) -> None:
        self.global_access = summary.get("mode") == "global"
        self.grants = list(summary.get("grants") or [])
        self.user_id = user_id

    def permits(self, item: dict[str, Any]) -> bool:
        if self.global_access:
            return True
        owner = str(
            item.get("internal_user_id") or item.get("requester_id") or item.get("user_id") or ""
        )
        if owner and owner == self.user_id:
            return True
        raw_routing = item.get("routing")
        routing = cast(dict[str, Any], raw_routing) if isinstance(raw_routing, dict) else {}
        environment = str(routing.get("environment") or "")
        base = str(routing.get("base") or "")
        workshop = str(routing.get("workshop") or "")
        matches = [
            grant for grant in self.grants if self._matches(grant, environment, base, workshop)
        ]
        if any(grant.get("effect") == "deny" for grant in matches):
            return False
        return any(grant.get("effect") == "allow" for grant in matches)

    @staticmethod
    def _matches(grant: dict[str, Any], environment: str, base: str, workshop: str) -> bool:
        return all(
            expected in {"*", actual}
            for expected, actual in (
                (str(grant.get("environment") or "*"), environment),
                (str(grant.get("base") or "*"), base),
                (str(grant.get("workshop") or "*"), workshop),
            )
        )
