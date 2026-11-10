-- Page-managed SVN connections contain references only, never credential values.
-- postgres-only
CREATE TABLE knowledge.code_svn_connection (
 id TEXT PRIMARY KEY,
 resource_id TEXT NOT NULL REFERENCES knowledge.retrieval_resource(id),
 public_url TEXT NOT NULL,
 secret_ref TEXT NOT NULL,
 repository_uuid TEXT,
 branch_path TEXT,
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CHECK ((repository_uuid IS NULL) = (branch_path IS NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_svn_connection" (
 id TEXT PRIMARY KEY,
 resource_id TEXT NOT NULL REFERENCES "knowledge.retrieval_resource"(id),
 public_url TEXT NOT NULL,
 secret_ref TEXT NOT NULL,
 repository_uuid TEXT,
 branch_path TEXT,
 created_by TEXT NOT NULL,
 created_at TEXT NOT NULL,
 CHECK ((repository_uuid IS NULL) = (branch_path IS NULL))
);
-- postgres-only
CREATE TABLE knowledge.code_resource_environment (
 revision_id TEXT NOT NULL REFERENCES knowledge.code_resource_config(revision_id),
 environment_id TEXT NOT NULL REFERENCES platform_environment(id),
 PRIMARY KEY(revision_id,environment_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_resource_environment" (
 revision_id TEXT NOT NULL REFERENCES "knowledge.code_resource_config"(revision_id),
 environment_id TEXT NOT NULL REFERENCES platform_environment(id),
 PRIMARY KEY(revision_id,environment_id)
);
-- postgres-only
CREATE INDEX code_svn_connection_resource ON knowledge.code_svn_connection(resource_id,created_at);
-- sqlite-only
CREATE INDEX code_svn_connection_resource ON "knowledge.code_svn_connection"(resource_id,created_at);
-- postgres-only
COMMENT ON TABLE knowledge.code_svn_connection IS '代码知识资源的不可变 SVN 连接配置与首次核实的仓库身份';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.id IS '连接稳定标识，改变地址或凭据时创建新连接';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.resource_id IS '连接所属代码知识资源，不可跨资源借用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.public_url IS '不含认证材料的 HTTPS 仓库或分支地址';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.secret_ref IS '凭据中心加密账号密码引用，不存明文';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.repository_uuid IS '首次连接核实并固定的仓库 UUID';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.branch_path IS '首次连接核实并固定的仓库内分支路径';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.created_by IS '配置连接的内部管理员标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_connection.created_at IS '连接创建时间';
-- postgres-only
COMMENT ON TABLE knowledge.code_resource_environment IS '代码知识库配置修订与既有业务环境的多对多项目归属';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_environment.revision_id IS '代码知识库不可变配置修订';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_environment.environment_id IS '共用代码的业务环境，不自动扩张知识库或数据权限';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.physical_key IS '受管 SVN 元数据中的持久检出标识；设备号和 inode 仅作单次执行替换检查';
