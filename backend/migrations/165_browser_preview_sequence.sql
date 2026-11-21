-- Runtime 1.5 browser previews can occupy 256 additional sequence numbers.
-- postgres-only
ALTER TABLE agent_model_call
  DROP CONSTRAINT agent_model_call_runtime_sequence_check,
  ADD CONSTRAINT agent_model_call_runtime_sequence_check CHECK (runtime_sequence BETWEEN 1 AND 2304);

-- sqlite-only
CREATE TABLE agent_model_call_new (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
  invocation_id TEXT NOT NULL CHECK (length(invocation_id) BETWEEN 1 AND 128),
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_sequence BIGINT NOT NULL CHECK (runtime_sequence BETWEEN 1 AND 2304),
  provider_request_id TEXT CHECK (
    provider_request_id IS NULL OR length(provider_request_id) <= 200
  ),
  provider_message_id TEXT CHECK (
    provider_message_id IS NULL OR length(provider_message_id) <= 200
  ),
  model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 200),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
  started_at TEXT,
  completed_at TEXT NOT NULL,
  duration_ms BIGINT CHECK (duration_ms IS NULL OR duration_ms >= 0),
  duration_source TEXT NOT NULL
    CHECK (duration_source IN ('SDK_OBSERVED', 'UNAVAILABLE')),
  input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
  cache_creation_input_tokens BIGINT
    CHECK (cache_creation_input_tokens IS NULL OR cache_creation_input_tokens >= 0),
  cache_read_input_tokens BIGINT
    CHECK (cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0),
  stop_reason TEXT CHECK (stop_reason IS NULL OR length(stop_reason) <= 128),
  error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 128),
  error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 2048),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (job_id, invocation_id, runtime_sequence),
  CHECK (
    (duration_source = 'UNAVAILABLE' AND duration_ms IS NULL AND started_at IS NULL)
    OR duration_source = 'SDK_OBSERVED'
  )
);
-- sqlite-only
INSERT INTO agent_model_call_new (id, job_id, invocation_id, request_digest, runtime_sequence, provider_request_id, provider_message_id, model_id, status, started_at, completed_at, duration_ms, duration_source, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, stop_reason, error_code, error_summary, created_at, updated_at)
SELECT id, job_id, invocation_id, request_digest, runtime_sequence, provider_request_id, provider_message_id, model_id, status, started_at, completed_at, duration_ms, duration_source, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, stop_reason, error_code, error_summary, created_at, updated_at FROM agent_model_call;
-- sqlite-only
DROP TABLE agent_model_call;
-- sqlite-only
ALTER TABLE agent_model_call_new RENAME TO agent_model_call;
-- sqlite-only
CREATE INDEX idx_agent_model_call_job_sequence
  ON agent_model_call(job_id, runtime_sequence, id);
-- sqlite-only
CREATE INDEX idx_agent_model_call_model_completed
  ON agent_model_call(model_id, completed_at, id);
-- sqlite-only
CREATE INDEX idx_agent_model_call_status_completed
  ON agent_model_call(status, completed_at, id);
