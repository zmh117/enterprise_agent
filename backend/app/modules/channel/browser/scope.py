from __future__ import annotations

import hashlib
import json
from typing import Any
from app.modules.channel.browser.answers import CHANNEL, CONNECTOR
from app.modules.channel.browser.http import deny


def fingerprint(parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def active_app(c: Any, origin: str, user: str, app: str) -> dict[str, Any]:
    row = c.database.execute_one(
        """select a.name,a.project_code,r.publication_id,r.deployment_id,agent.runtime_kind from business_application a
        join business_application_active_route r on r.application_id=a.id
        join business_application_deployment d on d.id=r.deployment_id and d.active=1 and d.publication_id=r.publication_id
        join business_application_publication p on p.id=r.publication_id
        join business_application_revision v on v.id=p.revision_id
        join agent_publication agent on agent.id=v.agent_publication_id
        join integration_connector k on k.id=r.connector_id where a.id=? and a.status='enabled'
        and r.environment='local' and r.trigger_type=? and r.normalized_routing_key=? and k.id=? and k.connector_type=?
        and k.enabled=1 and k.deleted=0 and k.allow_ingress=1 and k.allow_delivery=1""",
        (app, CHANNEL, "application:" + app.lower(), CONNECTOR, CHANNEL),
    )
    if (
        not row
        or not c.business_authorization_service.decide(user_id=user, application_id=app)["allowed"]
    ):
        raise deny("access_denied", 404)
    return {
        **row,
        "scope_ref": fingerprint(
            [
                origin,
                user,
                app,
                row["deployment_id"],
                row["publication_id"],
                CONNECTOR,
                row["project_code"],
            ]
        ),
    }


RECORDING_TOOLS = frozenset({"search_recording", "get_recording_evidence"})


ScopeKey = tuple[str, str | None, str | None]


def scope_key(row: dict[str, Any]) -> ScopeKey:
    return row["environment_id"], row["base_id"], row["workshop_id"]


def authorized_scopes(c: Any, app: str, accesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A grant covers itself and its enabled descendants. Never infer a parent grant."""
    grants = {
        scope_key(scope)
        for access in accesses
        if RECORDING_TOOLS.issubset(access["tool_identifiers"])
        for scope in access["scopes"]
    }
    if not grants or not all(
        c.authorization_center_repository.application_tool_is_effective(app, tool)
        for tool in RECORDING_TOOLS
    ):
        return []
    rows = c.database.execute(
        """select e.id as environment_id, e.code as environment_code,
                  coalesce(nullif(e.display_name,''), e.code) as environment_name,
                  b.id as base_id, b.code as base_code,
                  coalesce(nullif(b.display_name,''), b.code) as base_name,
                  w.id as workshop_id, w.code as workshop_code,
                  coalesce(nullif(w.display_name,''), w.code) as workshop_name
             from platform_environment e
             left join platform_base b on b.environment_id=e.id and b.status='enabled'
             left join platform_workshop w on w.base_id=b.id and w.status='enabled'
             where e.status='enabled' order by e.code,b.code,w.code"""
    )
    result = {}
    for row in rows:
        env, base, shop = scope_key(row)
        env_key = (env, None, None)
        base_key = (env, base, None)
        if env_key in grants:
            result[env_key] = {
                **row,
                **dict.fromkeys(
                    (
                        "base_id",
                        "base_code",
                        "base_name",
                        "workshop_id",
                        "workshop_code",
                        "workshop_name",
                    )
                ),
            }
        if base and (env_key in grants or base_key in grants):
            result[base_key] = {
                **row,
                **dict.fromkeys(("workshop_id", "workshop_code", "workshop_name")),
            }
        if shop and (env_key in grants or base_key in grants or scope_key(row) in grants):
            result[scope_key(row)] = row
    return list(result.values())
