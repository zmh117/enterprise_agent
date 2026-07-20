ALTER TABLE app_user
  ADD COLUMN account_type TEXT NOT NULL DEFAULT 'human'
  CHECK (account_type IN ('human', 'service'));

CREATE INDEX IF NOT EXISTS idx_app_user_account_type_status
  ON app_user(account_type, status);

CREATE TABLE IF NOT EXISTS webhook_trigger_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  public_id TEXT NOT NULL UNIQUE,
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  service_account_id TEXT NOT NULL REFERENCES app_user(id),
  status TEXT NOT NULL DEFAULT 'disabled'
    CHECK (status IN ('enabled', 'disabled')),
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_trigger_status_type
  ON webhook_trigger_definition(status, trigger_type);
CREATE INDEX IF NOT EXISTS idx_webhook_trigger_service_account
  ON webhook_trigger_definition(service_account_id);

CREATE TABLE IF NOT EXISTS webhook_trigger_revision (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  schema_version INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL,
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_webhook_trigger_revision_status
  ON webhook_trigger_revision(trigger_id, status, revision);

CREATE TABLE IF NOT EXISTS webhook_trigger_publication (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  revision_id TEXT NOT NULL REFERENCES webhook_trigger_revision(id),
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  agent_revision INTEGER NOT NULL,
  agent_config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'revoked')),
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_webhook_trigger_publication_status
  ON webhook_trigger_publication(trigger_id, status, revision);
CREATE INDEX IF NOT EXISTS idx_webhook_trigger_publication_agent
  ON webhook_trigger_publication(agent_publication_id);

CREATE TABLE IF NOT EXISTS webhook_event (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  trigger_publication_id TEXT NOT NULL REFERENCES webhook_trigger_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
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

CREATE INDEX IF NOT EXISTS idx_webhook_event_trigger_received
  ON webhook_event(trigger_id, received_at);
CREATE INDEX IF NOT EXISTS idx_webhook_event_status_received
  ON webhook_event(status, received_at);
CREATE INDEX IF NOT EXISTS idx_webhook_event_job
  ON webhook_event(job_id);
CREATE INDEX IF NOT EXISTS idx_webhook_event_correlation
  ON webhook_event(correlation_id);

CREATE TABLE IF NOT EXISTS webhook_replay_nonce (
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  nonce_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(trigger_id, nonce_hash)
);

CREATE INDEX IF NOT EXISTS idx_webhook_replay_nonce_expires
  ON webhook_replay_nonce(expires_at);

CREATE TABLE IF NOT EXISTS webhook_outbox (
  id TEXT PRIMARY KEY,
  webhook_event_id TEXT NOT NULL UNIQUE REFERENCES webhook_event(id),
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'publishing', 'published', 'dead')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  published_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_outbox_pending
  ON webhook_outbox(status, next_attempt_at);

ALTER TABLE agent_job
  ADD COLUMN webhook_event_id TEXT REFERENCES webhook_event(id);
ALTER TABLE agent_job
  ADD COLUMN webhook_trigger_id TEXT REFERENCES webhook_trigger_definition(id);
ALTER TABLE agent_job
  ADD COLUMN webhook_trigger_publication_id TEXT REFERENCES webhook_trigger_publication(id);

CREATE INDEX IF NOT EXISTS idx_agent_job_webhook_event
  ON agent_job(webhook_event_id);
CREATE INDEX IF NOT EXISTS idx_agent_job_webhook_trigger
  ON agent_job(webhook_trigger_id, webhook_trigger_publication_id);

COMMENT ON COLUMN app_user.account_type IS '账号类型：human为自然人，service为不可交互登录的受管服务账号';
COMMENT ON TABLE webhook_trigger_definition IS '受管Webhook Trigger稳定定义，保存公开入口、connector、服务账号和当前发布指针';
COMMENT ON COLUMN webhook_trigger_definition.public_id IS '不可预测且可轮换的公共入口标识，不是认证凭证';
COMMENT ON COLUMN webhook_trigger_definition.service_account_id IS 'Webhook运行时统一RBAC主体，必须是service账号';
COMMENT ON TABLE webhook_trigger_revision IS 'Webhook Trigger可编辑草稿和校验结果';
COMMENT ON COLUMN webhook_trigger_revision.config_json IS '不含secret value和测试payload的类型化配置JSON';
COMMENT ON TABLE webhook_trigger_publication IS 'Webhook Trigger不可变发布快照并固定具体Agent publication';
COMMENT ON COLUMN webhook_trigger_publication.snapshot_json IS '固定认证引用、映射、routing、Agent和Delivery语义的不可变JSON';
COMMENT ON TABLE webhook_event IS 'Webhook持久化Inbox，只保存hash、声明式提取结果和脱敏有界摘要';
COMMENT ON COLUMN webhook_event.payload_hash IS '原始请求体SHA-256，仅用于审计和去重辅助，不保存正文';
COMMENT ON COLUMN webhook_event.normalized_event_json IS '有界标准化Channel输入，不包含认证header、secret或完整原始payload';
COMMENT ON TABLE webhook_replay_nonce IS 'HMAC防重放nonce哈希和到期时间，不保存原始nonce';
COMMENT ON TABLE webhook_outbox IS 'Webhook Inbox到RabbitMQ dispatcher的事务Outbox';
COMMENT ON COLUMN webhook_outbox.last_error_summary IS '不包含payload、凭证或连接信息的发布错误摘要';
COMMENT ON COLUMN agent_job.webhook_event_id IS '受管Webhook来源event ID，非Webhook job为空';
COMMENT ON COLUMN agent_job.webhook_trigger_publication_id IS 'job创建时固定的Webhook Trigger publication ID';
