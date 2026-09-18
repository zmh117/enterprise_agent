-- Expand numeric quotas without changing sandbox-v2 or rewriting historical facts.
-- SQLite replaces inline checks while copying the original values exactly.
-- sqlite-only
ALTER TABLE agent_job_file_snapshot RENAME COLUMN sandbox_file_limit TO sandbox_file_limit_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot ADD COLUMN sandbox_file_limit INTEGER NOT NULL DEFAULT 128
  CHECK (sandbox_file_limit IN (64, 128));
-- sqlite-only
UPDATE agent_job_file_snapshot SET sandbox_file_limit = sandbox_file_limit_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot DROP COLUMN sandbox_file_limit_old;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot RENAME COLUMN sandbox_capacity_bytes TO sandbox_capacity_bytes_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot ADD COLUMN sandbox_capacity_bytes BIGINT NOT NULL DEFAULT 536870912
  CHECK (sandbox_capacity_bytes IN (234881024, 536870912));
-- sqlite-only
UPDATE agent_job_file_snapshot SET sandbox_capacity_bytes = sandbox_capacity_bytes_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot DROP COLUMN sandbox_capacity_bytes_old;

-- postgres-only
ALTER TABLE agent_job_file_snapshot DROP CONSTRAINT agent_job_file_snapshot_sandbox_file_limit_check;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ALTER COLUMN sandbox_file_limit SET DEFAULT 128;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ADD CONSTRAINT agent_job_file_snapshot_sandbox_file_limit_check
  CHECK (sandbox_file_limit IN (64, 128));
-- postgres-only
ALTER TABLE agent_job_file_snapshot DROP CONSTRAINT agent_job_file_snapshot_sandbox_capacity_bytes_check;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ALTER COLUMN sandbox_capacity_bytes SET DEFAULT 536870912;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ADD CONSTRAINT agent_job_file_snapshot_sandbox_capacity_bytes_check
  CHECK (sandbox_capacity_bytes IN (234881024, 536870912));
