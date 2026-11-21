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
