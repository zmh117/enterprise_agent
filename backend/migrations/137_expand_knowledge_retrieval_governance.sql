-- 同库 knowledge 治理元数据及现有角色应用的 KB 允许范围；不回填授权或改原文档、分块、索引。
-- migration: sqlite-foreign-keys-off

-- 扩展固定 Server 域；逐列保留既有发布内容，不给旧发布增加任何 Tool。
-- sqlite-only
ALTER TABLE agent_publication_mcp_tool
  RENAME TO agent_publication_mcp_tool_before_knowledge_mcp;

-- sqlite-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp')),
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
  FROM agent_publication_mcp_tool_before_knowledge_mcp;

-- sqlite-only
ALTER TABLE business_application_revision_mcp_tool
  RENAME TO business_application_revision_mcp_tool_before_knowledge_mcp;

-- sqlite-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id, server_code, tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_revision_mcp_tool
  (application_revision_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_revision_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_revision_mcp_tool_before_knowledge_mcp;

-- sqlite-only
ALTER TABLE business_application_publication_mcp_tool
  RENAME TO business_application_publication_mcp_tool_before_knowledge_mcp;

-- sqlite-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id, server_code, tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_publication_mcp_tool
  (application_publication_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_publication_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_publication_mcp_tool_before_knowledge_mcp;

-- sqlite-only
DROP TABLE business_application_revision_mcp_tool_before_knowledge_mcp;

-- sqlite-only
DROP TABLE business_application_publication_mcp_tool_before_knowledge_mcp;

-- sqlite-only
DROP TABLE agent_publication_mcp_tool_before_knowledge_mcp;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  DROP CONSTRAINT agent_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  ADD CONSTRAINT agent_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp'));

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  DROP CONSTRAINT business_application_revision_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  ADD CONSTRAINT business_application_revision_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp'));

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  DROP CONSTRAINT business_application_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  ADD CONSTRAINT business_application_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp', 'knowledge-mcp'));


-- postgres-only
CREATE TABLE rbac_role_application_knowledge_base (
    application_access_id TEXT NOT NULL REFERENCES rbac_role_application_access(id) ON DELETE CASCADE,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(application_access_id, knowledge_base_id)
);

-- sqlite-only
CREATE TABLE rbac_role_application_knowledge_base (
    application_access_id TEXT NOT NULL REFERENCES rbac_role_application_access(id) ON DELETE CASCADE,
    knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(application_access_id, knowledge_base_id)
);

-- postgres-only
COMMENT ON TABLE rbac_role_application_knowledge_base IS '现有角色业务应用记录的知识库允许范围；无记录即未授权，不新增显式拒绝';
-- postgres-only
COMMENT ON COLUMN rbac_role_application_knowledge_base.application_access_id IS '所属角色业务应用访问记录';
-- postgres-only
COMMENT ON COLUMN rbac_role_application_knowledge_base.knowledge_base_id IS '明确逻辑知识库标识；不授予物理资源版本';
-- postgres-only
COMMENT ON COLUMN rbac_role_application_knowledge_base.created_at IS '允许范围保存时间';

-- postgres-only
CREATE TABLE knowledge.source_binding (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES knowledge.source(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    instance_code TEXT NOT NULL CHECK(length(instance_code) BETWEEN 1 AND 128),
    target_hash TEXT NOT NULL CHECK(length(target_hash)=64),
    team_id TEXT NOT NULL CHECK(length(team_id) BETWEEN 1 AND 128),
    state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','VERIFIED','REVOKED')),
    attestation_hash TEXT NOT NULL CHECK(length(attestation_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    document_count INTEGER NOT NULL CHECK(document_count>0),
    verification_hash TEXT CHECK(verification_hash IS NULL OR length(verification_hash)=64),
    checked_count INTEGER NOT NULL DEFAULT 0 CHECK(checked_count>=0 AND checked_count<=document_count),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    verified_by TEXT,
    verified_job_id TEXT,
    verified_at TIMESTAMPTZ,
    revoked_by TEXT,
    revoked_at TIMESTAMPTZ,
    UNIQUE(source_id,revision),
    CHECK((verification_hash IS NULL AND checked_count=0 AND verified_at IS NULL AND verified_by IS NULL AND verified_job_id IS NULL) OR (verification_hash IS NOT NULL AND checked_count>0 AND verified_at IS NOT NULL AND verified_by IS NOT NULL AND verified_job_id IS NOT NULL)),
    CHECK(state<>'VERIFIED' OR verification_hash IS NOT NULL),
    CHECK((state='REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL) OR (state<>'REVOKED' AND revoked_at IS NULL AND revoked_by IS NULL))
);

-- postgres-only
CREATE TABLE knowledge.retrieval_resource (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'enabled' CHECK(status IN ('enabled','disabled','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    state_revision INTEGER NOT NULL DEFAULT 1 CHECK(state_revision>0),
    draft_revision_id TEXT,
    published_revision_id TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

-- postgres-only
CREATE TABLE knowledge.retrieval_revision (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES knowledge.retrieval_resource(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    binding_id TEXT NOT NULL REFERENCES knowledge.source_binding(id),
    index_id TEXT NOT NULL REFERENCES knowledge.vector_index(id),
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_by TEXT,
    published_at TIMESTAMPTZ,
    CHECK((published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)),
    UNIQUE(resource_id,revision),
    UNIQUE(resource_id,id)
);

-- postgres-only
CREATE TABLE knowledge.retrieval_verification (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    resource_revision INTEGER NOT NULL CHECK(resource_revision>0),
    revision_id TEXT NOT NULL,
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    status TEXT NOT NULL CHECK(status IN ('VERIFIED','FAILED')),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    error_code TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY(resource_id,revision_id) REFERENCES knowledge.retrieval_revision(resource_id,id),
    UNIQUE(resource_id,resource_revision),
    CHECK((status='VERIFIED' AND error_code IS NULL) OR (status='FAILED' AND error_code IS NOT NULL))
);

-- postgres-only
ALTER TABLE knowledge.retrieval_resource ADD CONSTRAINT knowledge_resource_draft_fk FOREIGN KEY(id,draft_revision_id) REFERENCES knowledge.retrieval_revision(resource_id,id) DEFERRABLE INITIALLY DEFERRED;

-- postgres-only
ALTER TABLE knowledge.retrieval_resource ADD CONSTRAINT knowledge_resource_published_fk FOREIGN KEY(id,published_revision_id) REFERENCES knowledge.retrieval_revision(resource_id,id) DEFERRABLE INITIALLY DEFERRED;

-- postgres-only
CREATE UNIQUE INDEX knowledge_resource_enabled_base_idx ON knowledge.retrieval_resource (knowledge_base_id) WHERE status='enabled';

-- postgres-only
CREATE UNIQUE INDEX knowledge_source_verified_idx ON knowledge.source_binding (source_id) WHERE state='VERIFIED';

-- postgres-only
CREATE INDEX knowledge_resource_verification_idx ON knowledge.retrieval_verification (revision_id,created_at,id);

-- sqlite-only
CREATE TABLE "knowledge.source_binding" (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    instance_code TEXT NOT NULL CHECK(length(instance_code) BETWEEN 1 AND 128),
    target_hash TEXT NOT NULL CHECK(length(target_hash)=64),
    team_id TEXT NOT NULL CHECK(length(team_id) BETWEEN 1 AND 128),
    state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','VERIFIED','REVOKED')),
    attestation_hash TEXT NOT NULL CHECK(length(attestation_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    document_count INTEGER NOT NULL CHECK(document_count>0),
    verification_hash TEXT CHECK(verification_hash IS NULL OR length(verification_hash)=64),
    checked_count INTEGER NOT NULL DEFAULT 0 CHECK(checked_count>=0 AND checked_count<=document_count),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verified_by TEXT,
    verified_job_id TEXT,
    verified_at TEXT,
    revoked_by TEXT,
    revoked_at TEXT,
    UNIQUE(source_id,revision),
    CHECK((verification_hash IS NULL AND checked_count=0 AND verified_at IS NULL AND verified_by IS NULL AND verified_job_id IS NULL) OR (verification_hash IS NOT NULL AND checked_count>0 AND verified_at IS NOT NULL AND verified_by IS NOT NULL AND verified_job_id IS NOT NULL)),
    CHECK(state<>'VERIFIED' OR verification_hash IS NOT NULL),
    CHECK((state='REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL) OR (state<>'REVOKED' AND revoked_at IS NULL AND revoked_by IS NULL))
);

-- sqlite-only
CREATE TABLE "knowledge.retrieval_resource" (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'enabled' CHECK(status IN ('enabled','disabled','archived')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    state_revision INTEGER NOT NULL DEFAULT 1 CHECK(state_revision>0),
    draft_revision_id TEXT,
    published_revision_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(id,draft_revision_id) REFERENCES "knowledge.retrieval_revision"(resource_id,id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(id,published_revision_id) REFERENCES "knowledge.retrieval_revision"(resource_id,id) DEFERRABLE INITIALLY DEFERRED
);

-- sqlite-only
CREATE TABLE "knowledge.retrieval_revision" (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES "knowledge.retrieval_resource"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    binding_id TEXT NOT NULL REFERENCES "knowledge.source_binding"(id),
    index_id TEXT NOT NULL REFERENCES "knowledge.vector_index"(id),
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    CHECK((published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)),
    UNIQUE(resource_id,revision),
    UNIQUE(resource_id,id)
);

-- sqlite-only
CREATE TABLE "knowledge.retrieval_verification" (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    resource_revision INTEGER NOT NULL CHECK(resource_revision>0),
    revision_id TEXT NOT NULL,
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    status TEXT NOT NULL CHECK(status IN ('VERIFIED','FAILED')),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    error_code TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(resource_id,revision_id) REFERENCES "knowledge.retrieval_revision"(resource_id,id),
    UNIQUE(resource_id,resource_revision),
    CHECK((status='VERIFIED' AND error_code IS NULL) OR (status='FAILED' AND error_code IS NOT NULL))
);

-- sqlite-only
CREATE UNIQUE INDEX knowledge_resource_enabled_base_idx ON "knowledge.retrieval_resource" (knowledge_base_id) WHERE status='enabled';

-- sqlite-only
CREATE UNIQUE INDEX knowledge_source_verified_idx ON "knowledge.source_binding" (source_id) WHERE state='VERIFIED';

-- sqlite-only
CREATE INDEX knowledge_resource_verification_idx ON "knowledge.retrieval_verification" (revision_id,created_at,id);

-- postgres-only
COMMENT ON TABLE knowledge.source_binding IS '离线来源绑定修订；不改变来源存储身份或授予业务权限';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.id IS '绑定修订标识';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.source_id IS '离线来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.revision IS '同来源递增修订';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.instance_code IS '受信部署 ONES 实例编码';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.target_hash IS '受信固定 Provider 目标配置摘要；目标变更使核验失效';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.team_id IS '明确的 ONES Team 标识；不是显示名称';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.state IS '待核验、已核验或已撤销';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.attestation_hash IS '操作者完整批次来源确认的证据摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.corpus_hash IS '核验绑定的完整来源身份和版本清单摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.document_count IS '来源确认覆盖的完整文档数';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.verification_hash IS '技术交叉核验安全摘要；不包含原始响应';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.checked_count IS '技术交叉验证工作项数量；不代表全库授权';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.created_by IS '发起来源确认的操作人';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.created_at IS '修订创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.verified_by IS '核验操作人';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.verified_job_id IS '核验时本人业务应用 Job 标识；不保存 JWT';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.verified_at IS '完成技术核验时间';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.revoked_by IS '撤销或替换操作人';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.revoked_at IS '撤销时间';

-- postgres-only
COMMENT ON TABLE knowledge.retrieval_resource IS '知识检索逻辑资源；草稿和发布指针不授予用户读取权';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.id IS '资源稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.knowledge_base_id IS '授权逻辑知识库标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.code IS '资源管理编码';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.name IS '资源管理名称；不是业务文档标题';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.status IS '资源启用停用归档状态';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.revision IS '管理并发修订';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.state_revision IS '启停归档递增修订；停用后再启用仍使在途调用失效';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.draft_revision_id IS '当前草稿内容修订';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.published_revision_id IS '当前已发布内容修订；初始为空';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.created_by IS '资源创建人';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.created_at IS '资源创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_resource.updated_at IS '资源变更时间';

-- postgres-only
COMMENT ON TABLE knowledge.retrieval_revision IS '知识检索资源不可变配置版本；编辑创建新版本';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.id IS '配置修订标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.resource_id IS '所属逻辑资源';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.revision IS '资源内递增配置版本';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.binding_id IS '固定来源绑定修订';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.index_id IS '固定 READY 索引标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.profile_hash IS '固定 Embedding 模型配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.corpus_hash IS '固定向量语料清单摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.config_hash IS '本配置完整摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.created_by IS '配置操作人';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.created_at IS '配置创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.published_by IS '首次发布操作人；首次发布后不得覆盖';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.published_at IS '首次发布时间；配置内容始终不可变';

-- postgres-only
COMMENT ON TABLE knowledge.retrieval_verification IS '知识检索配置技术验证事实；不代替发布和业务授权';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.id IS '验证事实标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.resource_id IS '资源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.resource_revision IS '验证前管理修订；用于稳定排序和并发唯一约束';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.revision_id IS '本次验证的不可变配置版本';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.config_hash IS '被验证配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.status IS '技术验证结果';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.evidence_hash IS '固定安全技术检查结果摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.error_code IS '固定机器错误码；不存动态错误或响应';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.created_by IS '验证操作人';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_verification.created_at IS '技术验证时间';
