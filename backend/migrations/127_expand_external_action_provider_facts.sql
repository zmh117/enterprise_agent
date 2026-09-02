-- Separate the DingTalk confirmation route from the external Provider that
-- executes an Action Intent. Existing DingTalk rows retain compatible defaults.

ALTER TABLE external_action_intent
  ADD COLUMN confirmation_channel_code TEXT NOT NULL DEFAULT 'dingtalk'
    CHECK (confirmation_channel_code = 'dingtalk');

ALTER TABLE external_action_intent
  ADD COLUMN execution_provider_code TEXT NOT NULL DEFAULT 'dingtalk'
    CHECK (execution_provider_code IN ('dingtalk', 'ones'));

ALTER TABLE external_action_intent
  ADD COLUMN execution_external_identity_id TEXT REFERENCES user_external_identity(id);

ALTER TABLE external_action_intent
  ADD COLUMN execution_scope_id TEXT NOT NULL DEFAULT ''
    CHECK (length(execution_scope_id) <= 128);

ALTER TABLE external_action_intent
  ADD COLUMN target_resource_type TEXT NOT NULL DEFAULT ''
    CHECK (target_resource_type IN ('', 'task'));

ALTER TABLE external_action_intent
  ADD COLUMN target_resource_id TEXT NOT NULL DEFAULT ''
    CHECK (length(target_resource_id) <= 128);

ALTER TABLE external_action_intent
  ADD COLUMN precondition_json TEXT NOT NULL DEFAULT '{}'
    CHECK (length(precondition_json) <= 16384);

ALTER TABLE external_action_intent
  ADD COLUMN precondition_hash TEXT NOT NULL DEFAULT ''
    CHECK (length(precondition_hash) IN (0, 64));

ALTER TABLE external_action_intent
  ADD COLUMN field_catalog_version TEXT NOT NULL DEFAULT ''
    CHECK (length(field_catalog_version) <= 80);

ALTER TABLE external_action_intent
  ADD COLUMN field_catalog_hash TEXT NOT NULL DEFAULT ''
    CHECK (length(field_catalog_hash) IN (0, 64));

ALTER TABLE external_action_intent
  ADD COLUMN intent_fingerprint TEXT NOT NULL DEFAULT ''
    CHECK (length(intent_fingerprint) IN (0, 64));

ALTER TABLE external_action_intent
  ADD COLUMN confirmation_summary_json TEXT NOT NULL DEFAULT '{}'
    CHECK (length(confirmation_summary_json) <= 16384);

CREATE UNIQUE INDEX uq_external_action_intent_fingerprint
  ON external_action_intent(intent_fingerprint)
  WHERE intent_fingerprint <> '';

CREATE INDEX idx_external_action_intent_provider_claim
  ON external_action_intent(execution_provider_code, status,
                            execution_claim_expires_at, created_at);

COMMENT ON COLUMN external_action_intent.confirmation_channel_code IS
  '确认卡片渠道，当前固定为钉钉';
COMMENT ON COLUMN external_action_intent.execution_provider_code IS
  '确认后执行外部写入的Provider';
COMMENT ON COLUMN external_action_intent.execution_external_identity_id IS
  '执行Provider对应的原始外部身份，不含Credential Secret';
COMMENT ON COLUMN external_action_intent.execution_scope_id IS
  '执行Provider的冻结Team scope';
COMMENT ON COLUMN external_action_intent.target_resource_type IS
  '目标资源类型';
COMMENT ON COLUMN external_action_intent.target_resource_id IS
  '目标资源稳定ID';
COMMENT ON COLUMN external_action_intent.precondition_json IS
  '执行前必须重新验证的有界资源快照';
COMMENT ON COLUMN external_action_intent.precondition_hash IS
  '前置条件规范JSON摘要';
COMMENT ON COLUMN external_action_intent.field_catalog_version IS
  '准备时使用的写字段目录版本';
COMMENT ON COLUMN external_action_intent.field_catalog_hash IS
  '准备时使用的写字段目录摘要';
COMMENT ON COLUMN external_action_intent.intent_fingerprint IS
  '包含Job参数身份Team资源快照和目录的幂等摘要';
COMMENT ON COLUMN external_action_intent.confirmation_summary_json IS
  '完整确认卡片摘要，兼容ONES多字段差异且不得包含Secret';
