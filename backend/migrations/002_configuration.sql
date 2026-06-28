CREATE TABLE IF NOT EXISTS tool_definition (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  risk_level TEXT NOT NULL DEFAULT 'low',
  read_only INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration_connector (
  id TEXT PRIMARY KEY,
  connector_type TEXT NOT NULL,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasource_registry (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_code TEXT NOT NULL UNIQUE,
  connector_id TEXT REFERENCES integration_connector(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permission_policy (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_code TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_code TEXT NOT NULL,
  effect TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

