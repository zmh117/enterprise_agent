-- Preserve Runtime protocol 1.5 source sequence while keeping audit chunk
-- content out of the safe agent_runtime_event projection.
-- migration: sqlite-foreign-keys-off

-- SQLite must rebuild the table to extend its event-type CHECK. Existing rows
-- are copied without changing their identity, sequence, type, or payload.
-- sqlite-only
CREATE TABLE agent_runtime_event_v15_audit_projection (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'tool_contract_observed',
    'model_call', 'api_retry', 'audit_chunk', 'tool_event', 'assistant_text',
    'terminal'
  )),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);
-- sqlite-only
INSERT INTO agent_runtime_event_v15_audit_projection
  (id, job_id, invocation_id, request_digest, sequence, event_type,
   payload_json, created_at)
SELECT id, job_id, invocation_id, request_digest, sequence, event_type,
       payload_json, created_at
  FROM agent_runtime_event;
-- sqlite-only
DROP TABLE agent_runtime_event;
-- sqlite-only
ALTER TABLE agent_runtime_event_v15_audit_projection RENAME TO agent_runtime_event;
-- sqlite-only
CREATE INDEX idx_agent_runtime_event_job
  ON agent_runtime_event(job_id, invocation_id, sequence);
-- sqlite-only
CREATE INDEX idx_agent_runtime_event_digest
  ON agent_runtime_event(request_digest);

-- PostgreSQL changes the named constraint in place.
-- postgres-only
ALTER TABLE agent_runtime_event
  DROP CONSTRAINT agent_runtime_event_event_type_check;
-- postgres-only
ALTER TABLE agent_runtime_event
  ADD CONSTRAINT agent_runtime_event_event_type_check CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'tool_contract_observed',
    'model_call', 'api_retry', 'audit_chunk', 'tool_event', 'assistant_text',
    'terminal'
  ));

COMMENT ON COLUMN agent_runtime_event.event_type IS
  'Runtime事件类型；audit_chunk仅保存不含content的连续性结构元数据。';
COMMENT ON COLUMN agent_runtime_event.payload_json IS
  '仅保存安全payload；audit_chunk排除Base64 content并只保留完整性元数据。';
