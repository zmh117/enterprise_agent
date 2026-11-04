-- 知识网页运维；不修改已有集合或发布状态。
-- postgres-only
ALTER TABLE knowledge.sync_binding ADD COLUMN schedule_enabled INTEGER NOT NULL DEFAULT 1 CHECK(schedule_enabled IN (0,1));
-- postgres-only
CREATE TABLE knowledge.ops_operation (
    id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('build','up','stop','sync','backfill')),
    binding_id TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    actor_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','RETRY_WAIT','SUCCEEDED','PARTIAL','FAILED','INTERRUPTED')),
    stage TEXT NOT NULL,
    run_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    retry_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
-- postgres-only
CREATE TABLE knowledge.ops_event (
    id TEXT PRIMARY KEY,
    operation_id TEXT,
    service TEXT NOT NULL,
    code TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
-- postgres-only
CREATE TABLE knowledge.ops_runtime (
    id TEXT PRIMARY KEY CHECK(id IN ('controller','sync','deployment')),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    heartbeat_at TEXT NOT NULL
);
-- postgres-only
CREATE INDEX knowledge_ops_queue_idx ON knowledge.ops_operation(state,kind,created_at,id);
-- postgres-only
CREATE INDEX knowledge_ops_binding_idx ON knowledge.ops_operation(binding_id,created_at,id);
-- postgres-only
CREATE INDEX knowledge_ops_events_idx ON knowledge.ops_event(created_at,id);
-- postgres-only
CREATE INDEX knowledge_ops_task_events_idx ON knowledge.ops_event(operation_id,created_at,id);
-- sqlite-only
ALTER TABLE "knowledge.sync_binding" ADD COLUMN schedule_enabled INTEGER NOT NULL DEFAULT 1 CHECK(schedule_enabled IN (0,1));
-- sqlite-only
CREATE TABLE "knowledge.ops_operation" (
    id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('build','up','stop','sync','backfill')),
    binding_id TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    actor_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','RETRY_WAIT','SUCCEEDED','PARTIAL','FAILED','INTERRUPTED')),
    stage TEXT NOT NULL,
    run_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    retry_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
-- sqlite-only
CREATE TABLE "knowledge.ops_event" (
    id TEXT PRIMARY KEY,
    operation_id TEXT,
    service TEXT NOT NULL,
    code TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
-- sqlite-only
CREATE TABLE "knowledge.ops_runtime" (
    id TEXT PRIMARY KEY CHECK(id IN ('controller','sync','deployment')),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    heartbeat_at TEXT NOT NULL
);
-- sqlite-only
CREATE INDEX knowledge_ops_queue_idx ON "knowledge.ops_operation"(state,kind,created_at,id);
-- sqlite-only
CREATE INDEX knowledge_ops_binding_idx ON "knowledge.ops_operation"(binding_id,created_at,id);
-- sqlite-only
CREATE INDEX knowledge_ops_events_idx ON "knowledge.ops_event"(created_at,id);
-- sqlite-only
CREATE INDEX knowledge_ops_task_events_idx ON "knowledge.ops_event"(operation_id,created_at,id);
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.schedule_enabled IS '自动调度开关；关闭不打断当前任务或禁止显式补采';
-- postgres-only
COMMENT ON TABLE knowledge.ops_operation IS '知识库运维持久状态：ops_operation';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.id IS '运维任务唯一标识';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.request_key IS '客户端幂等请求标识';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.kind IS '固定允许的操作类型';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.binding_id IS '采集计划标识；部署操作为空';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.parameters_json IS '固定参数，只含日期和配置修订';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.actor_id IS '操作人标识或本机运维身份';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.state IS '持久执行状态';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.stage IS '安全阶段码';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.run_id IS '关联增量采集运行标识';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.attempts IS '实际执行次数';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.retry_at IS '瞬态失败下次重试时间';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.error_code IS '固定安全错误码';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.created_at IS '请求创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.updated_at IS '最近状态更新时间';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.started_at IS '最近执行开始时间';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_operation.finished_at IS '终态时间';
-- postgres-only
COMMENT ON TABLE knowledge.ops_event IS '知识库运维持久状态：ops_event';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.id IS '安全事件唯一标识';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.operation_id IS '关联任务；服务事件可为空';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.service IS '固定服务或同步计划事件类别';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.code IS '允许的安全事件码';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.details_json IS '允许字段的计数和标识，不含原始输出';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_event.created_at IS '事件创建时间';
-- postgres-only
COMMENT ON TABLE knowledge.ops_runtime IS '知识库运维持久状态：ops_runtime';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_runtime.id IS '执行器或部署状态类别';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_runtime.snapshot_json IS '安全服务快照及已构建和已应用版本';
-- postgres-only
COMMENT ON COLUMN knowledge.ops_runtime.heartbeat_at IS '最近状态观察时间';
