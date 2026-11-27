ALTER TABLE integration_connector ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1) AND (archived=0 OR enabled=0));
ALTER TABLE webhook_trigger_definition ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1) AND (archived=0 OR status='disabled'));

-- postgres-only
COMMENT ON COLUMN integration_connector.archived IS '渠道已归档，仅供历史查询';
-- postgres-only
COMMENT ON COLUMN webhook_trigger_definition.archived IS '触发器已归档，仅供历史查询';
