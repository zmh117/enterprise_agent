ALTER TABLE agent_job ADD COLUMN last_error_code TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN last_error_at TEXT;
ALTER TABLE agent_job ADD COLUMN next_retry_at TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_job_retry_due
    ON agent_job (status, next_retry_at);

CREATE INDEX IF NOT EXISTS idx_agent_job_legacy_retry_recovery
    ON agent_job (status, retry_count, locked_at)
    WHERE result IS NULL;
