-- Add complete, invocation-scoped Agent context/runtime audits and introduce
-- Runtime protocol 1.5 without rewriting immutable 1.3/1.4 history.
-- migration: sqlite-foreign-keys-off

-- SQLite keeps historical rows and defaults newly created Jobs to v1.5.
-- sqlite-only
ALTER TABLE agent_job
  RENAME COLUMN agent_runtime_protocol_version TO agent_runtime_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job
  ADD COLUMN agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.5'
  CHECK (agent_runtime_protocol_version IN ('1.3', '1.4', '1.5'));
-- sqlite-only
UPDATE agent_job
   SET agent_runtime_protocol_version = agent_runtime_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job DROP COLUMN agent_runtime_protocol_version_old;

-- sqlite-only
ALTER TABLE agent_job_execution_summary
  RENAME COLUMN source_protocol_version TO source_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job_execution_summary
  ADD COLUMN source_protocol_version TEXT NOT NULL DEFAULT '1.5'
  CHECK (source_protocol_version IN ('1.3', '1.4', '1.5'));
-- sqlite-only
UPDATE agent_job_execution_summary
   SET source_protocol_version = source_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job_execution_summary DROP COLUMN source_protocol_version_old;

-- PostgreSQL changes the named constraints in place.
-- postgres-only
ALTER TABLE agent_job DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job ALTER COLUMN agent_runtime_protocol_version SET DEFAULT '1.5';
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version IN ('1.3', '1.4', '1.5'));

-- postgres-only
ALTER TABLE agent_job_execution_summary
  DROP CONSTRAINT agent_job_execution_summary_source_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job_execution_summary
  ALTER COLUMN source_protocol_version SET DEFAULT '1.5';
-- postgres-only
ALTER TABLE agent_job_execution_summary
  ADD CONSTRAINT agent_job_execution_summary_source_protocol_version_check
  CHECK (source_protocol_version IN ('1.3', '1.4', '1.5'));

CREATE TABLE agent_run_audit (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
  invocation_id TEXT NOT NULL CHECK (length(invocation_id) BETWEEN 1 AND 128),
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  attempt_no BIGINT NOT NULL CHECK (attempt_no BETWEEN 1 AND 32),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'CANCELLED')),
  audit_sha256 TEXT NOT NULL CHECK (length(audit_sha256) = 64),
  context_manifest_json TEXT NOT NULL DEFAULT '{}',
  system_prompt TEXT NOT NULL DEFAULT '',
  user_prompt TEXT NOT NULL DEFAULT '',
  tool_definitions_json TEXT NOT NULL DEFAULT '[]',
  permission_snapshot_json TEXT NOT NULL DEFAULT '{}',
  init_snapshot_json TEXT NOT NULL DEFAULT '{}',
  sdk_messages_json TEXT NOT NULL DEFAULT '[]',
  api_requests_json TEXT NOT NULL DEFAULT '[]',
  api_responses_json TEXT NOT NULL DEFAULT '[]',
  tool_executions_json TEXT NOT NULL DEFAULT '[]',
  model_requests_json TEXT NOT NULL DEFAULT '[]',
  usage_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  raw_api_capture_status TEXT NOT NULL DEFAULT 'unavailable'
    CHECK (raw_api_capture_status IN ('captured', 'unavailable', 'not_applicable')),
  provider_thinking_disclosure TEXT NOT NULL DEFAULT '',
  error_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id)
);

CREATE INDEX idx_agent_run_audit_job_attempt
  ON agent_run_audit(job_id, attempt_no, invocation_id);
CREATE INDEX idx_agent_run_audit_status_created
  ON agent_run_audit(status, created_at, job_id);

COMMENT ON TABLE agent_run_audit IS
  'Runtime protocol 1.5 invocation级完整上下文与模型I/O审计；正文按用户确认不做应用层脱敏或截断。';
COMMENT ON COLUMN agent_run_audit.id IS
  '运行审计记录稳定标识。';
COMMENT ON COLUMN agent_run_audit.job_id IS
  '所属Agent Job标识，随Job级联删除。';
COMMENT ON COLUMN agent_run_audit.invocation_id IS
  'Runtime invocation稳定身份；恢复重放使用同一身份并要求内容一致。';
COMMENT ON COLUMN agent_run_audit.request_digest IS
  'Runtime请求规范摘要，用于调用身份与重放校验。';
COMMENT ON COLUMN agent_run_audit.attempt_no IS
  'Job内从1开始的执行尝试序号。';
COMMENT ON COLUMN agent_run_audit.status IS
  '该Runtime调用的终态。';
COMMENT ON COLUMN agent_run_audit.audit_sha256 IS
  'Runtime分块重组后的规范JSON SHA-256，用于幂等与冲突校验。';
COMMENT ON COLUMN agent_run_audit.context_manifest_json IS
  '模型实际收到的上下文来源、完整正文、字符估算与上游截断事实。';
COMMENT ON COLUMN agent_run_audit.system_prompt IS
  '该调用实际组装的完整System Prompt。';
COMMENT ON COLUMN agent_run_audit.user_prompt IS
  '该调用实际发送的完整用户Prompt。';
COMMENT ON COLUMN agent_run_audit.tool_definitions_json IS
  '冻结工具事实及原始模型请求中实际加载的完整工具Schema。';
COMMENT ON COLUMN agent_run_audit.permission_snapshot_json IS
  '该调用的工具权限与批准策略快照。';
COMMENT ON COLUMN agent_run_audit.init_snapshot_json IS
  'Claude Agent SDK初始化消息原文。';
COMMENT ON COLUMN agent_run_audit.sdk_messages_json IS
  'Claude Agent SDK暴露的完整消息流。';
COMMENT ON COLUMN agent_run_audit.api_requests_json IS
  'Claude Code OTel raw body文件中的完整Messages API请求正文，不包含Runtime主动附加的认证Header。';
COMMENT ON COLUMN agent_run_audit.api_responses_json IS
  'Claude Code OTel raw body文件中的完整Messages API响应正文。';
COMMENT ON COLUMN agent_run_audit.tool_executions_json IS
  'SDK消息中模型可见的完整Tool use/result输入输出；安全Tool主账仍由agent_tool_call承担。';
COMMENT ON COLUMN agent_run_audit.model_requests_json IS
  '按模型消息观测的请求身份、模型、Usage与上下文Token。';
COMMENT ON COLUMN agent_run_audit.usage_json IS
  'SDK Result与原始API请求度量原文。';
COMMENT ON COLUMN agent_run_audit.summary_json IS
  '用于Job调优展示的请求、Token、缓存、成本和工具聚合。';
COMMENT ON COLUMN agent_run_audit.raw_api_capture_status IS
  '原始API正文采集状态。';
COMMENT ON COLUMN agent_run_audit.provider_thinking_disclosure IS
  '上游Provider思考内容可见性边界说明。';
COMMENT ON COLUMN agent_run_audit.error_json IS
  '失败调用的Runtime异常类别与原始消息。';
COMMENT ON COLUMN agent_run_audit.started_at IS
  'Runtime调用开始时间。';
COMMENT ON COLUMN agent_run_audit.finished_at IS
  'Runtime调用终止时间。';
COMMENT ON COLUMN agent_run_audit.created_at IS
  '控制面持久化该审计的时间。';
COMMENT ON COLUMN agent_job.agent_runtime_protocol_version IS
  '新Job固定使用1.5；终态1.3/1.4历史只读保留。';
COMMENT ON COLUMN agent_job_execution_summary.source_protocol_version IS
  '执行摘要接受历史1.3/1.4或当前1.5。';
