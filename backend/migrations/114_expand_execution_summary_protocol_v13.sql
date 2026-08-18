-- Keep the derived execution summary compatible with the current Runtime
-- protocol. Migration 111 widened agent_job to 1.3 but the independently
-- persisted summary CHECK introduced by migration 106 remained capped at 1.2.
-- migration: sqlite-foreign-keys-off

-- SQLite cannot replace a column CHECK constraint in place.
-- sqlite-only
CREATE TABLE agent_job_execution_summary_protocol_v13 (
  job_id TEXT PRIMARY KEY REFERENCES agent_job(id) ON DELETE CASCADE,
  accounting_status TEXT NOT NULL
    CHECK (accounting_status IN ('COMPLETE', 'PARTIAL', 'UNAVAILABLE')),
  observed_model_turn_count BIGINT NOT NULL DEFAULT 0
    CHECK (observed_model_turn_count >= 0),
  api_retry_count BIGINT NOT NULL DEFAULT 0 CHECK (api_retry_count >= 0),
  runtime_invocation_count BIGINT NOT NULL DEFAULT 0
    CHECK (runtime_invocation_count >= 0),
  total_duration_ms BIGINT CHECK (total_duration_ms IS NULL OR total_duration_ms >= 0),
  total_api_duration_ms BIGINT
    CHECK (total_api_duration_ms IS NULL OR total_api_duration_ms >= 0),
  input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
  cache_creation_input_tokens BIGINT
    CHECK (cache_creation_input_tokens IS NULL OR cache_creation_input_tokens >= 0),
  cache_read_input_tokens BIGINT
    CHECK (cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0),
  model_usage_json TEXT NOT NULL DEFAULT '[]',
  estimated_cost_usd NUMERIC(20, 12)
    CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
  execution_status TEXT NOT NULL DEFAULT 'UNKNOWN'
    CHECK (execution_status IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'UNKNOWN')),
  execution_failure_stage TEXT CHECK (
    execution_failure_stage IS NULL OR execution_failure_stage IN (
      'RUNTIME_START', 'RUNTIME_PROTOCOL', 'MCP_CONNECTION', 'MODEL_API',
      'TOOL_PERMISSION', 'TOOL_EXECUTION', 'UNKNOWN'
    )
  ),
  failure_code TEXT CHECK (failure_code IS NULL OR length(failure_code) <= 128),
  failure_summary TEXT CHECK (failure_summary IS NULL OR length(failure_summary) <= 2048),
  retry_exhausted INTEGER NOT NULL DEFAULT 0 CHECK (retry_exhausted IN (0, 1)),
  source_protocol_version TEXT NOT NULL
    CHECK (source_protocol_version IN ('1.0', '1.1', '1.2', '1.3')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
INSERT INTO agent_job_execution_summary_protocol_v13 (
  job_id, accounting_status, observed_model_turn_count, api_retry_count,
  runtime_invocation_count, total_duration_ms, total_api_duration_ms,
  input_tokens, output_tokens, cache_creation_input_tokens,
  cache_read_input_tokens, model_usage_json, estimated_cost_usd,
  execution_status, execution_failure_stage, failure_code, failure_summary,
  retry_exhausted, source_protocol_version, created_at, updated_at
)
SELECT
  job_id, accounting_status, observed_model_turn_count, api_retry_count,
  runtime_invocation_count, total_duration_ms, total_api_duration_ms,
  input_tokens, output_tokens, cache_creation_input_tokens,
  cache_read_input_tokens, model_usage_json, estimated_cost_usd,
  execution_status, execution_failure_stage, failure_code, failure_summary,
  retry_exhausted, source_protocol_version, created_at, updated_at
FROM agent_job_execution_summary;

-- sqlite-only
DROP TABLE agent_job_execution_summary;

-- sqlite-only
ALTER TABLE agent_job_execution_summary_protocol_v13
  RENAME TO agent_job_execution_summary;

-- postgres-only
ALTER TABLE agent_job_execution_summary
  DROP CONSTRAINT agent_job_execution_summary_source_protocol_version_check;

-- postgres-only
ALTER TABLE agent_job_execution_summary
  ADD CONSTRAINT agent_job_execution_summary_source_protocol_version_check
  CHECK (source_protocol_version IN ('1.0', '1.1', '1.2', '1.3'));
