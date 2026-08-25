-- Introduce Runtime protocol 1.4 tool-contract evidence without rewriting
-- immutable protocol 1.3 history. Non-terminal 1.3 Jobs must be drained or
-- explicitly cancelled before this release is applied.
-- migration: sqlite-foreign-keys-off

CREATE TABLE migration_120_runtime_protocol_guard (
  violation INTEGER NOT NULL CHECK (violation = 0)
);

INSERT INTO migration_120_runtime_protocol_guard
SELECT 1 WHERE EXISTS (
  SELECT 1
    FROM agent_job
   WHERE agent_runtime_protocol_version = '1.3'
     AND status NOT IN ('SUCCEEDED', 'FAILED', 'TIMEOUT')
);

DROP TABLE migration_120_runtime_protocol_guard;

ALTER TABLE agent_job
  ADD COLUMN control_plane_build_identity_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agent_job
  ADD COLUMN tool_contract_status TEXT NOT NULL DEFAULT 'NOT_OBSERVED'
  CHECK (tool_contract_status IN ('MATCH', 'DRIFT', 'NOT_OBSERVED'));
ALTER TABLE agent_job
  ADD COLUMN tool_contract_last_invocation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job
  ADD COLUMN tool_contract_observation_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job
  ADD COLUMN prompt_template_version TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job
  ADD COLUMN prompt_contract_hash TEXT NOT NULL DEFAULT '';

-- SQLite keeps historical terminal 1.3 rows and defaults all new rows to 1.4.
-- sqlite-only
ALTER TABLE agent_job
  RENAME COLUMN agent_runtime_protocol_version TO agent_runtime_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job
  ADD COLUMN agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.4'
  CHECK (agent_runtime_protocol_version IN ('1.3', '1.4'));
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
  ADD COLUMN source_protocol_version TEXT NOT NULL DEFAULT '1.4'
  CHECK (source_protocol_version IN ('1.3', '1.4'));
-- sqlite-only
UPDATE agent_job_execution_summary
   SET source_protocol_version = source_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job_execution_summary DROP COLUMN source_protocol_version_old;

-- SQLite must rebuild the event table to extend its event-type CHECK. Existing
-- protocol 1.3 rows are copied byte-for-byte and no historical payload is changed.
-- sqlite-only
CREATE TABLE agent_runtime_event_v14 (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'tool_contract_observed',
    'model_call', 'api_retry', 'tool_event', 'assistant_text', 'terminal'
  )),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);
-- sqlite-only
INSERT INTO agent_runtime_event_v14
  (id, job_id, invocation_id, request_digest, sequence, event_type,
   payload_json, created_at)
SELECT id, job_id, invocation_id, request_digest, sequence, event_type,
       payload_json, created_at
  FROM agent_runtime_event;
-- sqlite-only
DROP TABLE agent_runtime_event;
-- sqlite-only
ALTER TABLE agent_runtime_event_v14 RENAME TO agent_runtime_event;
-- sqlite-only
CREATE INDEX idx_agent_runtime_event_job
  ON agent_runtime_event(job_id, invocation_id, sequence);
-- sqlite-only
CREATE INDEX idx_agent_runtime_event_digest
  ON agent_runtime_event(request_digest);

-- PostgreSQL changes the named constraints in place.
-- postgres-only
ALTER TABLE agent_job DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job ALTER COLUMN agent_runtime_protocol_version SET DEFAULT '1.4';
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version IN ('1.3', '1.4'));

-- postgres-only
ALTER TABLE agent_job_execution_summary
  DROP CONSTRAINT agent_job_execution_summary_source_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job_execution_summary
  ALTER COLUMN source_protocol_version SET DEFAULT '1.4';
-- postgres-only
ALTER TABLE agent_job_execution_summary
  ADD CONSTRAINT agent_job_execution_summary_source_protocol_version_check
  CHECK (source_protocol_version IN ('1.3', '1.4'));

-- postgres-only
ALTER TABLE agent_runtime_event
  DROP CONSTRAINT agent_runtime_event_event_type_check;
-- postgres-only
ALTER TABLE agent_runtime_event
  ADD CONSTRAINT agent_runtime_event_event_type_check CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'tool_contract_observed',
    'model_call', 'api_retry', 'tool_event', 'assistant_text', 'terminal'
  ));

COMMENT ON COLUMN agent_job.control_plane_build_identity_json IS
  'Job创建时Control Plane安全构建身份';
COMMENT ON COLUMN agent_job.tool_contract_status IS
  '从不可变Runtime事件投影的MATCH DRIFT或NOT_OBSERVED';
COMMENT ON COLUMN agent_job.tool_contract_last_invocation_id IS
  '最后一次工具契约观测的Runtime invocation';
COMMENT ON COLUMN agent_job.tool_contract_observation_hash IS
  '最后一次安全工具契约观测的规范化SHA-256';
COMMENT ON COLUMN agent_job.prompt_template_version IS
  '最后一次观测使用的Prompt模板版本';
COMMENT ON COLUMN agent_job.prompt_contract_hash IS
  '最后一次Prompt工具声明合同SHA-256';
COMMENT ON COLUMN agent_job.agent_runtime_protocol_version IS
  '新Job固定使用1.4；终态1.3历史只读保留';
COMMENT ON COLUMN agent_job_execution_summary.source_protocol_version IS
  '执行摘要只接受历史1.3或当前1.4';
