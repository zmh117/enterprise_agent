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


def authorized_workshops(c: Any, app: str, accesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return enabled workshop paths covered by one role's recording grant."""
    grants = {
        (scope["environment_id"], scope["base_id"], scope["workshop_id"])
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
             from platform_environment e join platform_base b on b.environment_id=e.id
             join platform_workshop w on w.base_id=b.id
            where e.status='enabled' and b.status='enabled' and w.status='enabled'
            order by e.code,b.code,w.code"""
    )
    result = []
    for row in rows:
        env, base, shop = row["environment_id"], row["base_id"], row["workshop_id"]
        if (
            (env, None, None) in grants
            or (env, base, None) in grants
            or (env, base, shop) in grants
        ):
            result.append(row)
    return result
