from __future__ import annotations

import json

from app.modules.webhook.domain.models import config_hash


def prepare_test_webhook(c):
    """Synthetic published ingress. Application fixtures grant its selected role separately."""
    existing = c.database.execute_one(
        "select id from webhook_trigger_publication where id='webhook_trigger_publication_grafana_v1'"
    )
    if existing:
        return
    role = c.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code="webhook-test",
        name="Webhook synthetic role",
        description="Synthetic fixture",
        purpose_tags=[],
    )
    config = {
        "schema_version": 2,
        "adapter": "grafana_alertmanager_v1",
        "authentication": {
            "type": "bearer_v1",
            "secret_ref": "secret://platform/grafana_webhook_token",
        },
        "role_ids": [role["role"]["id"]],
    }
    snapshot = {
        **config,
        "service_account_id": "user_webhook_grafana_default",
        "source_connector_id": "connector-grafana-default",
    }
    c.database.execute(
        """insert into webhook_trigger_revision
        (id,trigger_id,revision,status,schema_version,config_json,config_hash,validation_json,created_by,created_at,updated_at)
        values ('webhook_trigger_revision_grafana_v1','webhook_trigger_grafana_default',1,'published',2,?,?,'{}','user_local_admin',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
        (json.dumps(config), config_hash(config)),
    )
    c.database.execute(
        """insert into webhook_trigger_publication
        (id,trigger_id,revision_id,revision,schema_version,snapshot_json,config_hash,status,published_by,published_at)
        values ('webhook_trigger_publication_grafana_v1','webhook_trigger_grafana_default','webhook_trigger_revision_grafana_v1',1,2,?,?,'active','user_local_admin',CURRENT_TIMESTAMP)""",
        (json.dumps(snapshot), config_hash(config)),
    )
    c.database.execute(
        "update webhook_trigger_definition set status='enabled', current_publication_id='webhook_trigger_publication_grafana_v1' where id='webhook_trigger_grafana_default'"
    )
    c.database.execute("""insert into agent_channel_binding (id,publication_id,direction,connector_id,config_json,created_at)
        values ('binding-test-grafana','agent_publication_default_v1','ingress','connector-grafana-default','{}',CURRENT_TIMESTAMP)
        on conflict(publication_id,direction,connector_id) do nothing""")
    c.authorization_center_service.replace_service_roles(
        actor_id="user_local_admin",
        user_id="user_webhook_grafana_default",
        role_ids=[role["role"]["id"]],
    )
