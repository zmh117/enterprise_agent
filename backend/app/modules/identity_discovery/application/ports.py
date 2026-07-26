from __future__ import annotations

from typing import Protocol

from app.modules.identity_discovery.domain import DingTalkIdentityObservation


class DingTalkIdentityDiscoveryStore(Protocol):
    def observe(self, observation: DingTalkIdentityObservation) -> dict[str, object]: ...

    def list_candidates(
        self,
        *,
        cutoff: str,
        search: str,
        conversation_scope: str,
        limit: int,
        after_last_seen_at: str,
        after_id: str,
    ) -> tuple[list[dict[str, object]], bool]: ...

    def get_visible_candidate(
        self, candidate_id: str, *, cutoff: str
    ) -> dict[str, object]: ...

    def count_visible(self, *, cutoff: str) -> int: ...

    def cleanup_expired(self, *, cutoff: str, limit: int = 500) -> int: ...
