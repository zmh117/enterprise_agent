-- Contract migration. Existing databases require a separately authorized,
-- content-safe approval record at exact head 102. Fresh empty installations
-- may contract in the same initial migration run.
-- migration: schema-consolidation-contract
-- job_dispatch_cutover_quarantine is intentionally retained: its tracked
-- retirement decision is blocked. A future signed approval requires a new,
-- forward-only migration. This immutable contract must never be edited later.

ALTER TABLE agent_session DROP COLUMN dingding_conversation_id;

ALTER TABLE agent_session DROP COLUMN dingding_user_id;

ALTER TABLE agent_session DROP COLUMN source;

ALTER TABLE agent_job DROP COLUMN user_id;

ALTER TABLE agent_job DROP COLUMN source;

ALTER TABLE agent_job DROP COLUMN user_message;

ALTER TABLE agent_workflow_template DROP COLUMN graph_json;
