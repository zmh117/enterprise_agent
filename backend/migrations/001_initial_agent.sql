CREATE TABLE IF NOT EXISTS agent_session (
  id TEXT PRIMARY KEY,
  dingding_conversation_id TEXT NOT NULL,
  dingding_user_id TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'dingding',
  project_code TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_job (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  project_code TEXT NOT NULL DEFAULT 'default',
  source TEXT NOT NULL DEFAULT 'dingding',
  user_message TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retry_count INTEGER NOT NULL DEFAULT 3,
  result TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  locked_at TEXT,
  locked_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_job_status ON agent_job(status);
CREATE INDEX IF NOT EXISTS idx_agent_job_session ON agent_job(session_id);

CREATE TABLE IF NOT EXISTS agent_message (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  job_id TEXT REFERENCES agent_job(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_step (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  step_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES agent_job(id),
  event_type TEXT NOT NULL,
  actor_id TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_tool_call (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  tool_name TEXT NOT NULL,
  request_payload TEXT NOT NULL,
  response_summary TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'low',
  audit_id TEXT REFERENCES audit_event(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_artifact (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  artifact_type TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  file_path TEXT,
  created_at TEXT NOT NULL
);

