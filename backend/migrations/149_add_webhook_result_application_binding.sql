-- Reuse the Webhook publication's frozen result route in Business Applications.
-- migration: sqlite-foreign-keys-off

-- sqlite-only
CREATE TABLE business_application_revision_delivery_new (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  delivery_type TEXT NOT NULL CHECK (delivery_type IN (
    'reply_original', 'dingtalk_private', 'dingtalk_group', 'webhook_callback', 'webhook_result'
  )),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order)
);

-- sqlite-only
INSERT INTO business_application_revision_delivery_new
  SELECT * FROM business_application_revision_delivery;

-- sqlite-only
DROP TABLE business_application_revision_delivery;

-- sqlite-only
ALTER TABLE business_application_revision_delivery_new
  RENAME TO business_application_revision_delivery;

-- sqlite-only
CREATE INDEX idx_business_application_delivery_revision
  ON business_application_revision_delivery(revision_id, binding_order);

-- postgres-only
ALTER TABLE business_application_revision_delivery
  DROP CONSTRAINT business_application_revision_delivery_delivery_type_check;

-- postgres-only
ALTER TABLE business_application_revision_delivery
  ADD CONSTRAINT business_application_revision_delivery_delivery_type_check
  CHECK (delivery_type IN (
    'reply_original', 'dingtalk_private', 'dingtalk_group', 'webhook_callback', 'webhook_result'
  ));
