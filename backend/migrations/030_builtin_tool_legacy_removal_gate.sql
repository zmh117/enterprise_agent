CREATE TABLE IF NOT EXISTS builtin_tool_legacy_removal_observation (
  id TEXT PRIMARY KEY,
  migration_version TEXT NOT NULL,
  report_hash TEXT NOT NULL CHECK (length(report_hash) = 64),
  new_legacy_writes_observed INTEGER NOT NULL CHECK (new_legacy_writes_observed >= 0),
  active_agent_references INTEGER NOT NULL CHECK (active_agent_references >= 0),
  active_application_references INTEGER NOT NULL
    CHECK (active_application_references >= 0),
  recoverable_job_references INTEGER NOT NULL
    CHECK (recoverable_job_references >= 0),
  zero_references INTEGER NOT NULL CHECK (zero_references IN (0, 1)),
  correlation_id TEXT NOT NULL,
  observed_by TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(migration_version, correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_removal_observation_sequence
  ON builtin_tool_legacy_removal_observation(
    migration_version,
    observed_at DESC,
    id DESC
  );

CREATE TABLE IF NOT EXISTS builtin_tool_legacy_removal_acceptance (
  id TEXT PRIMARY KEY,
  migration_version TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  snapshot_id TEXT NOT NULL REFERENCES agent_job_builtin_tool_snapshot(id),
  tool_call_id TEXT NOT NULL REFERENCES agent_tool_call(id),
  delivery_attempt_id TEXT NOT NULL REFERENCES delivery_attempt(id),
  acceptance_hash TEXT NOT NULL CHECK (length(acceptance_hash) = 64),
  correlation_id TEXT NOT NULL,
  verified_by TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  UNIQUE(migration_version, job_id, tool_call_id, delivery_attempt_id),
  UNIQUE(migration_version, acceptance_hash)
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_removal_acceptance_verified
  ON builtin_tool_legacy_removal_acceptance(migration_version, verified_at DESC);

CREATE TABLE IF NOT EXISTS builtin_tool_legacy_removal_gate (
  id TEXT PRIMARY KEY,
  migration_version TEXT NOT NULL,
  observation_id TEXT NOT NULL
    REFERENCES builtin_tool_legacy_removal_observation(id),
  acceptance_id TEXT REFERENCES builtin_tool_legacy_removal_acceptance(id),
  consecutive_zero_count INTEGER NOT NULL CHECK (consecutive_zero_count >= 0),
  required_zero_count INTEGER NOT NULL CHECK (required_zero_count >= 2),
  decision TEXT NOT NULL CHECK (decision IN ('BLOCKED', 'READY')),
  reason_code TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  evaluated_by TEXT NOT NULL,
  evaluated_at TEXT NOT NULL,
  UNIQUE(migration_version, correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_removal_gate_decision
  ON builtin_tool_legacy_removal_gate(migration_version, decision, evaluated_at DESC);

COMMENT ON TABLE builtin_tool_legacy_removal_observation IS
  'Immutable bounded zero-reference observations used by the legacy-v1 removal gate';
COMMENT ON TABLE builtin_tool_legacy_removal_acceptance IS
  'Persisted exact Runtime-to-Tool-Call-to-Delivery acceptance evidence without payload or Secret';
COMMENT ON TABLE builtin_tool_legacy_removal_gate IS
  'Removal decision requiring consecutive zero observations and verified real-chain evidence';
