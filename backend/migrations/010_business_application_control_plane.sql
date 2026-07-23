CREATE TABLE IF NOT EXISTS business_application (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL,
  owner_user_id TEXT REFERENCES app_user(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_business_application_project_status
  ON business_application(project_code, status);
CREATE INDEX IF NOT EXISTS idx_business_application_owner
  ON business_application(owner_user_id);

CREATE TABLE IF NOT EXISTS business_application_revision (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  agent_publication_id TEXT REFERENCES agent_publication(id),
  workflow_publication_id TEXT REFERENCES agent_workflow_publication(id),
  session_policy_json TEXT NOT NULL DEFAULT '{}',
  execution_policy_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{"valid":false,"errors":[]}',
  config_hash TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_business_application_revision_app
  ON business_application_revision(application_id, revision);
CREATE INDEX IF NOT EXISTS idx_business_application_revision_status
  ON business_application_revision(status);

CREATE TABLE IF NOT EXISTS business_application_revision_trigger (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  trigger_type TEXT NOT NULL
    CHECK (trigger_type IN ('dingtalk_private', 'dingtalk_group', 'webhook')),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  routing_key TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  actor_policy TEXT NOT NULL
    CHECK (actor_policy IN ('CURRENT_SENDER', 'SERVICE_ACCOUNT')),
  service_account_user_id TEXT REFERENCES app_user(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order),
  UNIQUE(revision_id, trigger_type, connector_id, normalized_routing_key)
);

CREATE INDEX IF NOT EXISTS idx_business_application_trigger_revision
  ON business_application_revision_trigger(revision_id, binding_order);
CREATE INDEX IF NOT EXISTS idx_business_application_trigger_route
  ON business_application_revision_trigger(
    trigger_type, connector_id, normalized_routing_key
  );

CREATE TABLE IF NOT EXISTS business_application_revision_delivery (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  delivery_type TEXT NOT NULL
    CHECK (delivery_type IN (
      'reply_original', 'dingtalk_private', 'dingtalk_group', 'webhook_callback'
    )),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order)
);

CREATE INDEX IF NOT EXISTS idx_business_application_delivery_revision
  ON business_application_revision_delivery(revision_id, binding_order);

CREATE TABLE IF NOT EXISTS business_application_revision_capability (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  capability_code TEXT NOT NULL,
  version_constraint TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order),
  UNIQUE(revision_id, capability_code, version_constraint)
);

CREATE INDEX IF NOT EXISTS idx_business_application_capability_revision
  ON business_application_revision_capability(revision_id, binding_order);

CREATE TABLE IF NOT EXISTS business_application_publication (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  UNIQUE(application_id, revision),
  UNIQUE(revision_id)
);

CREATE INDEX IF NOT EXISTS idx_business_application_publication_app
  ON business_application_publication(application_id, revision);

CREATE TABLE IF NOT EXISTS business_application_deployment (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  environment TEXT NOT NULL,
  publication_id TEXT REFERENCES business_application_publication(id),
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  activated_by TEXT NOT NULL DEFAULT '',
  activated_at TEXT,
  deactivated_by TEXT NOT NULL DEFAULT '',
  deactivated_at TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, environment)
);

CREATE INDEX IF NOT EXISTS idx_business_application_deployment_environment
  ON business_application_deployment(environment, active);

CREATE TABLE IF NOT EXISTS business_application_active_route (
  id TEXT PRIMARY KEY,
  deployment_id TEXT NOT NULL REFERENCES business_application_deployment(id),
  application_id TEXT NOT NULL REFERENCES business_application(id),
  publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
  environment TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(environment, trigger_type, connector_id, normalized_routing_key),
  UNIQUE(deployment_id, trigger_type, connector_id, normalized_routing_key)
);

CREATE INDEX IF NOT EXISTS idx_business_application_active_route_deployment
  ON business_application_active_route(deployment_id);

COMMENT ON TABLE business_application IS '业务应用稳定定义，不直接参与现有数据面路由';
COMMENT ON TABLE business_application_revision IS '业务应用追加式草稿修订';
COMMENT ON TABLE business_application_publication IS '不可变业务应用发布快照';
COMMENT ON TABLE business_application_deployment IS '环境级显式激活指针';
COMMENT ON TABLE business_application_active_route IS '活动Trigger确定性路由唯一投影';
