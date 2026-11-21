-- migration: sqlite-foreign-keys-off
-- sqlite-only
CREATE TABLE business_application_revision_trigger_new (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('dingtalk_private', 'dingtalk_group', 'webhook', 'browser_extension')),
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
  actor_policy,execution_user_id,enabled,config_json,created_at FROM business_application_revision_trigger;
-- sqlite-only
DROP TABLE business_application_revision_trigger;
-- sqlite-only
ALTER TABLE business_application_revision_trigger_new RENAME TO business_application_revision_trigger;
-- sqlite-only
CREATE INDEX idx_business_application_trigger_revision ON business_application_revision_trigger(revision_id,binding_order);
-- sqlite-only
CREATE INDEX idx_business_application_trigger_route ON business_application_revision_trigger(trigger_type,connector_id,normalized_routing_key);
-- postgres-only
ALTER TABLE business_application_revision_trigger DROP CONSTRAINT business_application_revision_trigger_trigger_type_check;
-- postgres-only
ALTER TABLE business_application_revision_trigger ADD CONSTRAINT business_application_revision_trigger_trigger_type_check CHECK (trigger_type IN ('dingtalk_private','dingtalk_group','webhook','browser_extension'));

INSERT INTO integration_connector(id,connector_type,name,enabled,allow_ingress,allow_delivery,created_at,updated_at)
VALUES('browser-extension','browser_extension','浏览器插件',1,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);

CREATE TABLE browser_extension_grant (
 session_id TEXT NOT NULL REFERENCES user_session(id) ON DELETE CASCADE,
 client_id TEXT NOT NULL, origin TEXT NOT NULL,
 PRIMARY KEY (session_id,client_id,origin)
);
CREATE TABLE browser_extension_credential (
 digest TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('code','access')),
 session_id TEXT NOT NULL, client_id TEXT NOT NULL, origin TEXT NOT NULL,
 challenge TEXT NOT NULL, expires_at BIGINT NOT NULL,
 FOREIGN KEY (session_id,client_id,origin) REFERENCES browser_extension_grant(session_id,client_id,origin) ON DELETE CASCADE
);
CREATE INDEX browser_credential_expiry ON browser_extension_credential(expires_at);
CREATE TABLE browser_answer_delta (
 job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
 attempt INTEGER NOT NULL, sequence INTEGER NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(job_id,attempt,sequence)
);
CREATE TABLE browser_message_receipt (
 origin TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES app_user(id), application_id TEXT NOT NULL REFERENCES business_application(id),
 client_message_id TEXT NOT NULL, digest TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
 PRIMARY KEY(origin,user_id,application_id,client_message_id), UNIQUE(job_id)
);
-- postgres-only
COMMENT ON TABLE browser_message_receipt IS '插件问题的事务受理与幂等回执';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.origin IS '登记的平台来源';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.user_id IS '提问的内部用户';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.application_id IS '业务应用标识';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.client_message_id IS '客户端提交键';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.digest IS '原始提交语义摘要';
-- postgres-only
COMMENT ON COLUMN browser_message_receipt.job_id IS '受理的执行任务';
-- postgres-only
COMMENT ON TABLE browser_answer_delta IS '原插件会话的短期回答草稿';
-- postgres-only
COMMENT ON COLUMN browser_answer_delta.job_id IS '所属执行任务';
-- postgres-only
COMMENT ON COLUMN browser_answer_delta.attempt IS '任务重试次数';
-- postgres-only
COMMENT ON COLUMN browser_answer_delta.sequence IS '已校验的 Runtime 源序号';
-- postgres-only
COMMENT ON COLUMN browser_answer_delta.body IS '当前批次的主对话 Markdown 增量';
-- postgres-only
COMMENT ON TABLE browser_extension_grant IS '登录会话内的插件同意记录';
-- postgres-only
COMMENT ON COLUMN browser_extension_grant.session_id IS '父登录会话';
-- postgres-only
COMMENT ON COLUMN browser_extension_grant.client_id IS '登记的浏览器扩展';
-- postgres-only
COMMENT ON COLUMN browser_extension_grant.origin IS '平台来源';
-- postgres-only
COMMENT ON TABLE browser_extension_credential IS '插件一次性授权码和短期业务凭据的摘要';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.digest IS '随机凭据的单向摘要';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.kind IS '凭据用途';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.session_id IS '有效父会话';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.client_id IS '登记的扩展';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.origin IS '绑定的平台来源';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.challenge IS '授权码的 PKCE S256 挑战';
-- postgres-only
COMMENT ON COLUMN browser_extension_credential.expires_at IS '到期的 UTC 秒数';
