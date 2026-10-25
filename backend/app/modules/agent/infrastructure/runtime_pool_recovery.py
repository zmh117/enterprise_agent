from __future__ import annotations

from app.modules.agent.infrastructure.runtime_http_client import (
    RuntimeClientSettings,
    probe_runtime_readiness,
)
from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
from app.shared.config import AgentRuntimeSettings
from app.shared.database import Database


def reconcile_runtime_nodes(settings: AgentRuntimeSettings, database: Database) -> None:
    """Control-plane scan; never inferred from timeout or from an arbitrary URL."""
    pool = RuntimePoolStore(database)
    pool.expire(limit=100)
    for node, url in settings.python_nodes:
        state = probe_runtime_readiness(
            RuntimeClientSettings(
                base_url=url,
                allowed_runtime_hosts=settings.python_allowed_hosts,
                allow_insecure_internal_http=settings.allow_insecure_internal_http,
            )
        )
        if (
            state.get("identity") == "verified"
            and state.get("pool_enabled")
            and state.get("node_id") == node
            and state.get("instance_id")
        ):
            pool.record_replacement(node, str(state["instance_id"]))
