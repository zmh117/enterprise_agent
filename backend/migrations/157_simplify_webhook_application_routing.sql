-- Webhook publishes only ingress and roles. Applications own execution and delivery.
-- migration: sqlite-foreign-keys-off
DROP INDEX idx_webhook_trigger_publication_agent;
ALTER TABLE webhook_trigger_publication DROP COLUMN agent_publication_id;
ALTER TABLE webhook_trigger_publication DROP COLUMN agent_revision;
ALTER TABLE webhook_trigger_publication DROP COLUMN agent_config_hash;

-- sqlite-only
CREATE TABLE webhook_event_new (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  trigger_publication_id TEXT NOT NULL REFERENCES webhook_trigger_publication(id),
  agent_publication_id TEXT REFERENCES agent_publication(id),
  service_account_id TEXT NOT NULL REFERENCES app_user(id),
  external_event_id TEXT NOT NULL DEFAULT '',
  dedup_key TEXT,
  payload_hash TEXT NOT NULL,
  request_bytes INTEGER NOT NULL DEFAULT 0,
  safe_summary_json TEXT NOT NULL DEFAULT '{}',
  normalized_event_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  job_id TEXT REFERENCES agent_job(id),
  status TEXT NOT NULL
    CHECK (status IN (
      'REJECTED_AUTH', 'REJECTED', 'IGNORED', 'ACCEPTED', 'DISPATCH_PENDING',
      'JOB_CREATED', 'DISPATCH_FAILED'
    )),
  auth_result TEXT NOT NULL DEFAULT '',
  filter_result TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  dispatched_at TEXT,
  completed_at TEXT,
  UNIQUE(trigger_id, dedup_key)
);
-- sqlite-only
INSERT INTO webhook_event_new SELECT * FROM webhook_event;
-- sqlite-only
DROP TABLE webhook_event;
-- sqlite-only
ALTER TABLE webhook_event_new RENAME TO webhook_event;
-- sqlite-only
CREATE INDEX idx_webhook_event_trigger_received ON webhook_event(trigger_id, received_at);
-- sqlite-only
CREATE INDEX idx_webhook_event_status_received ON webhook_event(status, received_at);
-- sqlite-only
CREATE INDEX idx_webhook_event_job ON webhook_event(job_id);
-- sqlite-only
CREATE INDEX idx_webhook_event_correlation ON webhook_event(correlation_id);
-- postgres-only
ALTER TABLE webhook_event ALTER COLUMN agent_publication_id DROP NOT NULL;

ALTER TABLE webhook_event ADD COLUMN application_publication_id TEXT REFERENCES business_application_publication(id);

-- Old custom mappings cannot remain executable after the contract change.
UPDATE webhook_trigger_definition SET status = 'disabled', current_publication_id = NULL,
 revision = revision + 1;
UPDATE webhook_trigger_publication SET status = 'revoked';

-- Rebind applications explicitly before enabling the new ingress contract.
UPDATE business_application_deployment SET active = 0, revision = revision + 1
 WHERE id IN (SELECT deployment_id FROM business_application_active_route WHERE trigger_type = 'webhook');
DELETE FROM business_application_active_route WHERE deployment_id IN (
 SELECT id FROM business_application_deployment WHERE active = 0
);

COMMENT ON COLUMN webhook_event.application_publication_id IS '接入时固定的业务应用发布版本，分发不得静默切换到其他版本';
