-- 完整工作副本检出不触发知识构建，任务只保存目录元数据。
-- postgres-only
CREATE TABLE knowledge.code_checkout_job (
 id TEXT PRIMARY KEY,
 request_key TEXT NOT NULL UNIQUE,
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 kind TEXT NOT NULL CHECK(kind IN ('browse','checkout')),
 state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','INTERRUPTED')),
 request_json TEXT NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}',
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
-- sqlite-only
CREATE TABLE "knowledge.code_checkout_job" (
 id TEXT PRIMARY KEY,
 request_key TEXT NOT NULL UNIQUE,
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 kind TEXT NOT NULL CHECK(kind IN ('browse','checkout')),
 state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','INTERRUPTED')),
 request_json TEXT NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}',
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
-- postgres-only
CREATE INDEX code_checkout_pending_idx ON knowledge.code_checkout_job(state,created_at,id);
-- sqlite-only
CREATE INDEX code_checkout_pending_idx ON "knowledge.code_checkout_job"(state,created_at,id);
-- postgres-only
COMMENT ON TABLE knowledge.code_checkout_job IS '管理员 SVN 目录浏览和完整工作副本检出的持久任务';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.id IS '任务唯一标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.request_key IS '管理员请求幂等键';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.actor_id IS '发起管理员，执行前重新授权';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.kind IS '目录浏览或完整检出';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.state IS '排队、执行、完成、失败或中断';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.request_json IS '登记摘要、固定版本、选择目录和目标子目录，不含凭据';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.result_json IS '有界目录元数据或实际检出位置，不含文件正文';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.error_code IS '安全错误码';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.created_at IS '任务创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout_job.updated_at IS '最近状态更新时间';
-- 158 重命名后的既有列补齐当前注释合同，不改动其数据或迁移校验和。
-- postgres-only
COMMENT ON COLUMN business_application_revision_trigger.execution_user_id IS '当前应用触发器绑定的执行人员';
