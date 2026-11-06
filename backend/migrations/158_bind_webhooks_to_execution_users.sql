-- migration: sqlite-foreign-keys-off
-- New Webhooks bind an explicit human execution user. Never infer one from old roles.
DROP INDEX idx_webhook_trigger_service_account;
ALTER TABLE webhook_trigger_definition ADD COLUMN execution_user_id TEXT REFERENCES app_user(id);
ALTER TABLE webhook_trigger_definition DROP COLUMN service_account_id;
CREATE INDEX idx_webhook_trigger_execution_user ON webhook_trigger_definition(execution_user_id);
ALTER TABLE webhook_event RENAME COLUMN service_account_id TO execution_user_id;

-- sqlite-only
CREATE TABLE business_application_revision_trigger_new (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('dingtalk_private', 'dingtalk_group', 'webhook')),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  routing_key TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  actor_policy TEXT NOT NULL CHECK (actor_policy IN ('CURRENT_SENDER', 'BOUND_USER')),
  execution_user_id TEXT REFERENCES app_user(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order),
  UNIQUE(revision_id, trigger_type, connector_id, normalized_routing_key)
);
-- sqlite-only
INSERT INTO business_application_revision_trigger_new
SELECT id,revision_id,binding_order,trigger_type,connector_id,routing_key,normalized_routing_key,
  CASE WHEN actor_policy='SERVICE_ACCOUNT' THEN 'BOUND_USER' ELSE actor_policy END,
  service_account_user_id,enabled,config_json,created_at FROM business_application_revision_trigger;
-- sqlite-only
DROP TABLE business_application_revision_trigger;
-- sqlite-only
ALTER TABLE business_application_revision_trigger_new RENAME TO business_application_revision_trigger;
-- sqlite-only
CREATE INDEX idx_business_application_trigger_revision ON business_application_revision_trigger(revision_id,binding_order);
-- sqlite-only
CREATE INDEX idx_business_application_trigger_route ON business_application_revision_trigger(trigger_type,connector_id,normalized_routing_key);
-- postgres-only
ALTER TABLE business_application_revision_trigger RENAME COLUMN service_account_user_id TO execution_user_id;
-- postgres-only
ALTER TABLE business_application_revision_trigger DROP CONSTRAINT business_application_revision_trigger_actor_policy_check;
-- postgres-only
UPDATE business_application_revision_trigger SET actor_policy='BOUND_USER' WHERE actor_policy='SERVICE_ACCOUNT';
-- postgres-only
ALTER TABLE business_application_revision_trigger ADD CONSTRAINT business_application_revision_trigger_actor_policy_check CHECK (actor_policy IN ('CURRENT_SENDER','BOUND_USER'));

UPDATE webhook_trigger_definition SET status='disabled', current_publication_id=NULL, revision=revision+1;
UPDATE webhook_trigger_publication SET status='revoked';
-- postgres-only
COMMENT ON COLUMN webhook_trigger_definition.execution_user_id IS '当前 Webhook 发布绑定的执行人员；草稿不修改此索引';
-- postgres-only
COMMENT ON COLUMN webhook_event.execution_user_id IS '接收时固定的执行主体；历史服务账号仅保留审计引用';
