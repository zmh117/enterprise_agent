-- Add the encrypted external-identity credential boundary and the retained
-- business-payload audit evidence required by the identity-aware ONES MCP.
-- Existing external identities remain unchanged and intentionally have no
-- current credential until their owner completes a new verification challenge.
-- migration: sqlite-foreign-keys-off

-- sqlite-only
ALTER TABLE agent_publication_mcp_tool
  RENAME TO agent_publication_mcp_tool_before_multi_server;

-- sqlite-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order),
  UNIQUE(agent_publication_id, server_code, tool_identifier)
);

-- sqlite-only
INSERT INTO agent_publication_mcp_tool
  (agent_publication_id, server_code, tool_identifier, schema_hash,
   model_description, selection_order, created_at)
SELECT agent_publication_id, server_code, tool_identifier, schema_hash,
       model_description, selection_order, created_at
  FROM agent_publication_mcp_tool_before_multi_server;

-- sqlite-only
ALTER TABLE business_application_revision_mcp_tool
  RENAME TO business_application_revision_mcp_tool_before_multi_server;

-- sqlite-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      server_code,
      tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_revision_mcp_tool
  (application_revision_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_revision_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_revision_mcp_tool_before_multi_server;

-- sqlite-only
ALTER TABLE business_application_publication_mcp_tool
  RENAME TO business_application_publication_mcp_tool_before_multi_server;

-- sqlite-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      server_code,
      tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_publication_mcp_tool
  (application_publication_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_publication_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_publication_mcp_tool_before_multi_server;

-- sqlite-only
DROP TABLE business_application_revision_mcp_tool_before_multi_server;

-- sqlite-only
DROP TABLE business_application_publication_mcp_tool_before_multi_server;

-- sqlite-only
DROP TABLE agent_publication_mcp_tool_before_multi_server;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  DROP CONSTRAINT agent_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  ADD CONSTRAINT agent_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp'));

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  ADD CONSTRAINT uq_agent_publication_mcp_tool_server_identity
  UNIQUE (agent_publication_id, server_code, tool_identifier);

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  DROP CONSTRAINT business_application_revision_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  ADD CONSTRAINT business_application_revision_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp'));

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  DROP CONSTRAINT fk_business_application_revision_mcp_tool_0;

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  ADD CONSTRAINT fk_business_application_revision_mcp_tool_0
  FOREIGN KEY (agent_publication_id, server_code, tool_identifier)
  REFERENCES agent_publication_mcp_tool(
    agent_publication_id,
    server_code,
    tool_identifier
  );

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  DROP CONSTRAINT business_application_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  ADD CONSTRAINT business_application_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp'));

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  DROP CONSTRAINT fk_business_application_publication_mcp_tool_0;

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  ADD CONSTRAINT fk_business_application_publication_mcp_tool_0
  FOREIGN KEY (agent_publication_id, server_code, tool_identifier)
  REFERENCES agent_publication_mcp_tool(
    agent_publication_id,
    server_code,
    tool_identifier
  );

CREATE TABLE external_identity_credential (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL UNIQUE
    REFERENCES user_external_identity(id),
  provider TEXT NOT NULL CHECK (length(provider) > 0),
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'REAUTH_REQUIRED', 'DISABLED', 'UNBOUND')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  login_material_ciphertext TEXT,
  login_material_nonce TEXT,
  token_ciphertext TEXT,
  token_nonce TEXT,
  key_id TEXT NOT NULL,
  algorithm TEXT NOT NULL DEFAULT 'AES-256-GCM'
    CHECK (algorithm = 'AES-256-GCM'),
  verified_at TEXT NOT NULL,
  token_refreshed_at TEXT,
  last_used_at TEXT,
  reauth_required_at TEXT,
  disabled_at TEXT,
  unbound_at TEXT,
  last_error_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (login_material_ciphertext IS NULL AND login_material_nonce IS NULL)
    OR
    (login_material_ciphertext IS NOT NULL AND login_material_nonce IS NOT NULL)
  ),
  CHECK (
    (token_ciphertext IS NULL AND token_nonce IS NULL)
    OR
    (token_ciphertext IS NOT NULL AND token_nonce IS NOT NULL)
  ),
  CHECK (
    status <> 'ACTIVE'
    OR (
      login_material_ciphertext IS NOT NULL
      AND login_material_nonce IS NOT NULL
      AND token_ciphertext IS NOT NULL
      AND token_nonce IS NOT NULL
    )
  ),
  CHECK (
    status <> 'UNBOUND'
    OR (
      login_material_ciphertext IS NULL
      AND login_material_nonce IS NULL
      AND token_ciphertext IS NULL
      AND token_nonce IS NULL
    )
  )
);

CREATE INDEX idx_external_identity_credential_provider_status
  ON external_identity_credential(provider, status);

CREATE INDEX idx_external_identity_credential_updated
  ON external_identity_credential(updated_at, id);

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN login_material_ciphertext TEXT;

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN login_material_nonce TEXT;

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN token_ciphertext TEXT;

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN token_nonce TEXT;

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN credential_key_id TEXT;

ALTER TABLE ones_identity_verification_challenge
  ADD COLUMN credential_algorithm TEXT;

CREATE TABLE mcp_operation_audit (
  id TEXT PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  principal_jti TEXT NOT NULL,
  actor_user_id TEXT NOT NULL REFERENCES app_user(id),
  actor_type TEXT NOT NULL DEFAULT 'user'
    CHECK (actor_type IN ('user', 'agent', 'system')),
  external_identity_id TEXT REFERENCES user_external_identity(id),
  credential_id TEXT REFERENCES external_identity_credential(id),
  credential_revision INTEGER CHECK (
    credential_revision IS NULL OR credential_revision >= 1
  ),
  provider TEXT NOT NULL DEFAULT 'ones',
  team_id TEXT NOT NULL DEFAULT '',
  provider_email TEXT NOT NULL DEFAULT '',
  provider_user_id TEXT NOT NULL DEFAULT '',
  server_code TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  operation TEXT NOT NULL,
  event_kind TEXT NOT NULL
    CHECK (event_kind IN ('TOOL', 'PROVIDER', 'CREDENTIAL')),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  status TEXT NOT NULL
    CHECK (status IN ('STARTED', 'SUCCEEDED', 'FAILED', 'DENIED')),
  error_code TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  payload_schema_version INTEGER NOT NULL DEFAULT 1
    CHECK (payload_schema_version = 1),
  tool_request_json TEXT NOT NULL DEFAULT '{}',
  provider_request_json TEXT NOT NULL DEFAULT '{}',
  provider_response_json TEXT NOT NULL DEFAULT '{}',
  tool_response_json TEXT NOT NULL DEFAULT '{}',
  audit_event_id TEXT REFERENCES audit_event(id),
  agent_tool_call_id TEXT REFERENCES agent_tool_call(id),
  created_at TEXT NOT NULL
);

CREATE INDEX idx_mcp_operation_audit_created
  ON mcp_operation_audit(created_at, id);

CREATE INDEX idx_mcp_operation_audit_correlation
  ON mcp_operation_audit(correlation_id, created_at, id);

CREATE INDEX idx_mcp_operation_audit_job
  ON mcp_operation_audit(job_id, created_at, id);

CREATE INDEX idx_mcp_operation_audit_actor
  ON mcp_operation_audit(actor_user_id, created_at, id);

CREATE INDEX idx_mcp_operation_audit_identity
  ON mcp_operation_audit(external_identity_id, created_at, id);

CREATE INDEX idx_mcp_operation_audit_principal
  ON mcp_operation_audit(principal_jti, created_at, id);

CREATE INDEX idx_mcp_operation_audit_status
  ON mcp_operation_audit(status, error_code, created_at, id);

COMMENT ON TABLE external_identity_credential IS
  '外部身份当前 Provider 凭据；只保存 AES-256-GCM 密文和不可重放生命周期事实。';
COMMENT ON COLUMN external_identity_credential.id IS
  '外部身份当前凭据记录 ID。';
COMMENT ON COLUMN external_identity_credential.external_identity_id IS
  '一对一关联 user_external_identity 的外部身份事实。';
COMMENT ON COLUMN external_identity_credential.provider IS
  '由代码注册表约束的 Provider 代码。';
COMMENT ON COLUMN external_identity_credential.status IS
  '运行时凭据状态：ACTIVE、REAUTH_REQUIRED、DISABLED 或 UNBOUND。';
COMMENT ON COLUMN external_identity_credential.revision IS
  '凭据轮换与状态变更使用的乐观并发修订号。';
COMMENT ON COLUMN external_identity_credential.login_material_ciphertext IS
  '使用 credential purpose AAD 加密的 Provider 登录材料密文。';
COMMENT ON COLUMN external_identity_credential.login_material_nonce IS
  '登录材料 AES-GCM 随机 nonce。';
COMMENT ON COLUMN external_identity_credential.token_ciphertext IS
  '使用 credential purpose AAD 加密的 Provider Token 密文。';
COMMENT ON COLUMN external_identity_credential.token_nonce IS
  'Provider Token AES-GCM 随机 nonce。';
COMMENT ON COLUMN external_identity_credential.key_id IS
  '平台主密钥的非秘密稳定标识。';
COMMENT ON COLUMN external_identity_credential.algorithm IS
  '固定 AES-256-GCM 加密算法标识。';
COMMENT ON COLUMN external_identity_credential.verified_at IS
  '当前凭据最近一次本人验证通过时间。';
COMMENT ON COLUMN external_identity_credential.token_refreshed_at IS
  'Provider Token 最近一次自动轮换时间。';
COMMENT ON COLUMN external_identity_credential.last_used_at IS
  '当前凭据最近一次成功用于 Provider 调用的时间。';
COMMENT ON COLUMN external_identity_credential.reauth_required_at IS
  '凭据进入 REAUTH_REQUIRED 的时间。';
COMMENT ON COLUMN external_identity_credential.disabled_at IS
  '凭据被显式停用的时间。';
COMMENT ON COLUMN external_identity_credential.unbound_at IS
  '身份软解绑并清除密文的时间。';
COMMENT ON COLUMN external_identity_credential.last_error_code IS
  '最近凭据生命周期失败的稳定安全错误码。';
COMMENT ON COLUMN external_identity_credential.created_at IS
  '当前凭据首次创建时间。';
COMMENT ON COLUMN external_identity_credential.updated_at IS
  '当前凭据最近修改时间。';

COMMENT ON COLUMN ones_identity_verification_challenge.login_material_ciphertext IS
  '使用 challenge purpose AAD 加密的短期 ONES 登录材料。';
COMMENT ON COLUMN ones_identity_verification_challenge.login_material_nonce IS
  'Challenge 登录材料 AES-GCM 随机 nonce。';
COMMENT ON COLUMN ones_identity_verification_challenge.token_ciphertext IS
  '使用 challenge purpose AAD 加密的短期 ONES Token。';
COMMENT ON COLUMN ones_identity_verification_challenge.token_nonce IS
  'Challenge Token AES-GCM 随机 nonce。';
COMMENT ON COLUMN ones_identity_verification_challenge.credential_key_id IS
  'Challenge 密文所用平台主密钥的非秘密稳定标识。';
COMMENT ON COLUMN ones_identity_verification_challenge.credential_algorithm IS
  'Challenge 密文固定算法标识。';

COMMENT ON TABLE mcp_operation_audit IS
  'ONES MCP Tool、Provider attempt 与凭据生命周期的有界业务原文审计证据。';
COMMENT ON COLUMN mcp_operation_audit.id IS
  'MCP 操作审计记录 ID。';
COMMENT ON COLUMN mcp_operation_audit.correlation_id IS
  '串联 Tool、Provider attempt、凭据事件和平台审计的 correlation ID。';
COMMENT ON COLUMN mcp_operation_audit.job_id IS
  '产生该 MCP 操作的运行 Job ID。';
COMMENT ON COLUMN mcp_operation_audit.session_id IS
  '产生该 MCP 操作的 Agent Session ID。';
COMMENT ON COLUMN mcp_operation_audit.principal_jti IS
  'Principal JWT 的不可重放 jti；不保存 JWT 或签名。';
COMMENT ON COLUMN mcp_operation_audit.actor_user_id IS
  '该调用代表的平台内部用户 ID。';
COMMENT ON COLUMN mcp_operation_audit.actor_type IS
  '调用 actor 类型：user、agent 或 system。';
COMMENT ON COLUMN mcp_operation_audit.external_identity_id IS
  '调用时实时解析的外部身份 ID。';
COMMENT ON COLUMN mcp_operation_audit.credential_id IS
  '调用时使用的当前外部身份凭据 ID。';
COMMENT ON COLUMN mcp_operation_audit.credential_revision IS
  '该阶段观测或使用的凭据 revision。';
COMMENT ON COLUMN mcp_operation_audit.provider IS
  '受控 Provider 代码。';
COMMENT ON COLUMN mcp_operation_audit.team_id IS
  '调用时实时解析的 Provider Team ID。';
COMMENT ON COLUMN mcp_operation_audit.provider_email IS
  '受 audit:*:read 保护的 Provider 邮箱身份原文。';
COMMENT ON COLUMN mcp_operation_audit.provider_user_id IS
  '受 audit:*:read 保护的 Provider 用户 ID 原文。';
COMMENT ON COLUMN mcp_operation_audit.server_code IS
  '固定 MCP Server 代码。';
COMMENT ON COLUMN mcp_operation_audit.tool_identifier IS
  '冻结并授权的 MCP Tool identifier。';
COMMENT ON COLUMN mcp_operation_audit.operation IS
  '业务操作代码，例如 read 或 credential_refresh。';
COMMENT ON COLUMN mcp_operation_audit.event_kind IS
  '审计阶段类型：TOOL、PROVIDER 或 CREDENTIAL。';
COMMENT ON COLUMN mcp_operation_audit.attempt IS
  '同一 correlation 内该阶段的从零开始 attempt 编号。';
COMMENT ON COLUMN mcp_operation_audit.status IS
  '该阶段的稳定执行状态。';
COMMENT ON COLUMN mcp_operation_audit.error_code IS
  '失败或拒绝时的稳定安全错误码。';
COMMENT ON COLUMN mcp_operation_audit.duration_ms IS
  '该阶段的有界毫秒耗时。';
COMMENT ON COLUMN mcp_operation_audit.payload_schema_version IS
  'Tool 与 Provider 有界业务载荷序列化 schema 版本。';
COMMENT ON COLUMN mcp_operation_audit.tool_request_json IS
  '完整有界 Tool Input 业务原文，不得包含认证秘密。';
COMMENT ON COLUMN mcp_operation_audit.provider_request_json IS
  '固定 Provider 业务 document 与 variables，不得包含认证 Header。';
COMMENT ON COLUMN mcp_operation_audit.provider_response_json IS
  '通过 schema 与大小校验的 Provider 业务响应原文。';
COMMENT ON COLUMN mcp_operation_audit.tool_response_json IS
  '规范化且有界的 Tool Output 业务原文。';
COMMENT ON COLUMN mcp_operation_audit.audit_event_id IS
  '关联的通用平台 audit_event ID。';
COMMENT ON COLUMN mcp_operation_audit.agent_tool_call_id IS
  '关联的模型侧 agent_tool_call ID。';
COMMENT ON COLUMN mcp_operation_audit.created_at IS
  '该 MCP 操作审计记录创建时间及保留期基准。';
