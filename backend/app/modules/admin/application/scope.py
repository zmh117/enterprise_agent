from __future__ import annotations

from typing import Any, cast


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
