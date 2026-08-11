-- Baseline v1: final schema equivalent to the immutable legacy 001-042 chain.
-- Schema only: identity bootstrap and local fixtures are deliberately separate.

-- sqlite-only
CREATE TABLE agent_session (
  id TEXT PRIMARY KEY,
  dingding_conversation_id TEXT NOT NULL,
  dingding_user_id TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'dingding',
  project_code TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, source_channel TEXT NOT NULL DEFAULT 'dingding', source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default', external_conversation_id TEXT NOT NULL DEFAULT '', requester_id TEXT NOT NULL DEFAULT '', requester_display_name TEXT NOT NULL DEFAULT '', routing_context_json TEXT NOT NULL DEFAULT '{}', reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}', session_key TEXT NOT NULL DEFAULT '', conversation_type TEXT NOT NULL DEFAULT 'direct', bot_identity TEXT NOT NULL DEFAULT '', summary_text TEXT NOT NULL DEFAULT '', summary_through_sequence INTEGER NOT NULL DEFAULT 0, summary_version INTEGER NOT NULL DEFAULT 0, message_sequence INTEGER NOT NULL DEFAULT 0, last_message_at TEXT, external_identity_id TEXT, business_application_id TEXT, business_application_code TEXT NOT NULL DEFAULT '', conversation_mode TEXT NOT NULL DEFAULT 'legacy', recent_message_limit INTEGER, session_policy_json TEXT NOT NULL DEFAULT '{}', application_publication_id TEXT, execution_scope_hash TEXT, isolation_key_version INTEGER NOT NULL DEFAULT 2, history_read_only INTEGER NOT NULL DEFAULT 0);

-- sqlite-only
CREATE TABLE agent_job (
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
, source_channel TEXT NOT NULL DEFAULT 'dingding', source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default', external_event_id TEXT NOT NULL DEFAULT '', requester_id TEXT NOT NULL DEFAULT '', routing_context_json TEXT NOT NULL DEFAULT '{}', reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}', internal_user_id TEXT, external_identity_id TEXT, agent_definition_id TEXT, agent_publication_id TEXT, agent_revision INTEGER, agent_config_hash TEXT NOT NULL DEFAULT '', webhook_event_id TEXT REFERENCES webhook_event(id), webhook_trigger_id TEXT REFERENCES webhook_trigger_definition(id), webhook_trigger_publication_id TEXT REFERENCES webhook_trigger_publication(id), last_error_code TEXT NOT NULL DEFAULT '', last_error_at TEXT, next_retry_at TEXT, business_application_id TEXT, business_application_code TEXT NOT NULL DEFAULT '', business_application_publication_id TEXT, business_application_deployment_id TEXT, business_application_route_id TEXT, business_application_config_hash TEXT NOT NULL DEFAULT '', business_application_runtime_status TEXT NOT NULL DEFAULT '', business_application_route_decision_json TEXT NOT NULL DEFAULT '{}', execution_policy_json TEXT, execution_policy_tool_call_count INTEGER NOT NULL DEFAULT 0, execution_policy_exhausted INTEGER NOT NULL DEFAULT 0, model_runtime_provenance_json TEXT, agent_runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (agent_runtime_kind IN ('python-v1', 'typescript-v1')), agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.0'
    CHECK (agent_runtime_protocol_version = '1.0'));

-- sqlite-only
CREATE TABLE agent_message (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  job_id TEXT REFERENCES agent_job(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
, external_message_id TEXT NOT NULL DEFAULT '', sender_id TEXT NOT NULL DEFAULT '', sender_display_name TEXT NOT NULL DEFAULT '', message_type TEXT NOT NULL DEFAULT 'text', sequence_no INTEGER NOT NULL DEFAULT 0, content_status TEXT NOT NULL DEFAULT 'READY', safe_metadata_json TEXT NOT NULL DEFAULT '{}');

-- sqlite-only
CREATE TABLE agent_step (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  step_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE audit_event (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES agent_job(id),
  event_type TEXT NOT NULL,
  actor_id TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_tool_call (
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

-- sqlite-only
CREATE TABLE agent_artifact (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  artifact_type TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  file_path TEXT,
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE integration_connector (
  id TEXT PRIMARY KEY,
  connector_type TEXT NOT NULL,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, allow_ingress INTEGER NOT NULL DEFAULT 0, allow_delivery INTEGER NOT NULL DEFAULT 0, secret_ref TEXT NOT NULL DEFAULT '', endpoint_ref TEXT NOT NULL DEFAULT '', host_allowlist TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1, deleted integer not null default 0, dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id));

-- sqlite-only
CREATE TABLE delivery_attempt (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  route_type TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  target_summary TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
, delivery_outbox_id TEXT REFERENCES delivery_outbox(id), replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0), attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0), correlation_id TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '');

-- sqlite-only
CREATE TABLE delivery_chunk (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES delivery_attempt(id),
  chunk_index INTEGER NOT NULL,
  chunk_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  error_message TEXT,
  created_at TEXT NOT NULL
, delivery_outbox_id TEXT REFERENCES delivery_outbox(id), replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0), attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0), idempotency_key TEXT NOT NULL DEFAULT '', payload_hash TEXT NOT NULL DEFAULT '', sent_at TEXT);

-- sqlite-only
CREATE TABLE platform_environment (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_base (
  id TEXT PRIMARY KEY,
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  engine TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(environment_id, code)
);

-- sqlite-only
CREATE TABLE platform_workshop (
  id TEXT PRIMARY KEY,
  base_id TEXT NOT NULL REFERENCES platform_base(id),
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  table_prefix TEXT NOT NULL DEFAULT '',
  redis_key_prefix TEXT NOT NULL DEFAULT '',
  loki_labels_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(base_id, code)
);

-- sqlite-only
CREATE TABLE platform_secret_reference (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  ref TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_config_audit (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_workflow_template (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  entry_node_key TEXT NOT NULL DEFAULT '',
  graph_schema_version INTEGER NOT NULL DEFAULT 1,
  graph_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_workflow_node (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  node_key TEXT NOT NULL,
  node_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  position_json TEXT NOT NULL DEFAULT '{}',
  config_json TEXT NOT NULL DEFAULT '{}',
  ui_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, node_key)
);

-- sqlite-only
CREATE TABLE agent_workflow_edge (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  edge_key TEXT NOT NULL,
  source_node_key TEXT NOT NULL,
  target_node_key TEXT NOT NULL,
  source_port TEXT NOT NULL DEFAULT '',
  target_port TEXT NOT NULL DEFAULT '',
  condition_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, edge_key)
);

-- sqlite-only
CREATE TABLE agent_workflow_publication (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  version INTEGER NOT NULL,
  graph_snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(template_id, version)
);

-- sqlite-only
CREATE TABLE platform_secret (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL DEFAULT 'encrypted_db',
  ref TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  active_version INTEGER NOT NULL DEFAULT 0,
  masked_summary TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_secret_version (
  id TEXT PRIMARY KEY,
  secret_id TEXT NOT NULL REFERENCES platform_secret(id),
  version INTEGER NOT NULL,
  ciphertext TEXT NOT NULL,
  nonce TEXT NOT NULL,
  key_id TEXT NOT NULL DEFAULT '',
  algorithm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(secret_id, version)
);

-- sqlite-only
CREATE TABLE platform_runtime_config_definition (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  value_type TEXT NOT NULL,
  default_json TEXT NOT NULL DEFAULT 'null',
  sensitive INTEGER NOT NULL DEFAULT 0,
  bootstrap_only INTEGER NOT NULL DEFAULT 0,
  service_names_json TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_runtime_config_value (
  id TEXT PRIMARY KEY,
  definition_id TEXT NOT NULL REFERENCES platform_runtime_config_definition(id),
  key TEXT NOT NULL,
  scope_type TEXT NOT NULL DEFAULT 'global',
  scope_code TEXT NOT NULL DEFAULT '*',
  service_name TEXT NOT NULL DEFAULT '',
  value_json TEXT NOT NULL DEFAULT 'null',
  secret_ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(key, scope_type, scope_code, service_name)
);

-- sqlite-only
CREATE TABLE message_attachment (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES agent_message(id),
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  ordinal INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  declared_mime TEXT NOT NULL DEFAULT '',
  detected_mime TEXT NOT NULL DEFAULT '',
  declared_size INTEGER,
  size_bytes INTEGER,
  sha256 TEXT NOT NULL DEFAULT '',
  object_bucket TEXT NOT NULL DEFAULT '',
  object_key TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  failure_code TEXT NOT NULL DEFAULT '',
  retry_count INTEGER NOT NULL DEFAULT 0,
  source_credential_ciphertext TEXT NOT NULL DEFAULT '',
  source_credential_type TEXT NOT NULL DEFAULT '',
  source_credential_expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  expires_at TEXT,
  UNIQUE(message_id, ordinal)
);

-- sqlite-only
CREATE TABLE attachment_content (
  id TEXT PRIMARY KEY,
  attachment_id TEXT NOT NULL UNIQUE REFERENCES message_attachment(id),
  plain_text TEXT NOT NULL,
  segments_json TEXT NOT NULL DEFAULT '[]',
  parser_version TEXT NOT NULL,
  char_count INTEGER NOT NULL DEFAULT 0,
  truncated INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE app_user (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, account_type TEXT NOT NULL DEFAULT 'human'
  CHECK (account_type IN ('human', 'service')));

-- sqlite-only
CREATE TABLE user_password_credential (
  user_id TEXT PRIMARY KEY REFERENCES app_user(id),
  password_hash TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  password_changed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE user_external_identity (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  provider TEXT NOT NULL,
  tenant_code TEXT NOT NULL,
  external_subject_id TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  union_id TEXT NOT NULL DEFAULT '',
  open_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  verified_at TEXT,
  last_seen_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id), display_name_observed_at TEXT, display_name_event_id TEXT NOT NULL DEFAULT '', display_name_source_connector_id TEXT NOT NULL DEFAULT '',
  UNIQUE(provider, tenant_code, external_subject_id)
);

-- sqlite-only
CREATE TABLE user_session (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  token_hash TEXT NOT NULL UNIQUE,
  csrf_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  idle_expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  revoked_at TEXT,
  user_agent_summary TEXT NOT NULL DEFAULT '',
  remote_address_summary TEXT NOT NULL DEFAULT ''
);

-- sqlite-only
CREATE TABLE rbac_role (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, origin TEXT NOT NULL DEFAULT 'custom'
  CHECK (origin IN ('system', 'custom')), protected INTEGER NOT NULL DEFAULT 0
  CHECK (protected IN (0, 1)), purpose_tags_json TEXT NOT NULL DEFAULT '[]', metadata_revision INTEGER NOT NULL DEFAULT 1, admin_revision INTEGER NOT NULL DEFAULT 1, business_revision INTEGER NOT NULL DEFAULT 1, membership_revision INTEGER NOT NULL DEFAULT 1);

-- sqlite-only
CREATE TABLE rbac_user_role (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, expires_at TEXT, assigned_by TEXT NOT NULL DEFAULT '', assignment_source TEXT NOT NULL DEFAULT 'manual',
  UNIQUE(user_id, role_id)
);

-- sqlite-only
CREATE TABLE identity_migration_audit (
  id TEXT PRIMARY KEY,
  legacy_subject_type TEXT NOT NULL,
  legacy_subject_code TEXT NOT NULL,
  tenant_code TEXT NOT NULL DEFAULT '',
  internal_user_id TEXT REFERENCES app_user(id),
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'enabled',
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, classification TEXT NOT NULL DEFAULT 'business'
    CHECK (classification IN ('business', 'internal_diagnostic')), runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')));

-- sqlite-only
CREATE TABLE agent_revision (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agent_definition(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL DEFAULT '',
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(agent_id, revision)
);

-- sqlite-only
CREATE TABLE agent_publication (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agent_definition(id),
  revision_id TEXT NOT NULL REFERENCES agent_revision(id),
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL, runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')),
  UNIQUE(agent_id, revision)
);

-- sqlite-only
CREATE TABLE agent_skill_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  skill_code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, skill_code)
);

-- sqlite-only
CREATE TABLE agent_channel_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  direction TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, direction, connector_id)
);

-- sqlite-only
CREATE TABLE webhook_trigger_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  public_id TEXT NOT NULL UNIQUE,
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  service_account_id TEXT NOT NULL REFERENCES app_user(id),
  status TEXT NOT NULL DEFAULT 'disabled'
    CHECK (status IN ('enabled', 'disabled')),
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE webhook_trigger_revision (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  schema_version INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL,
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

-- sqlite-only
CREATE TABLE webhook_trigger_publication (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  revision_id TEXT NOT NULL REFERENCES webhook_trigger_revision(id),
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  agent_revision INTEGER NOT NULL,
  agent_config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'revoked')),
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

-- sqlite-only
CREATE TABLE webhook_event (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  trigger_publication_id TEXT NOT NULL REFERENCES webhook_trigger_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  service_account_id TEXT NOT NULL REFERENCES app_user(id),
  external_event_id TEXT NOT NULL DEFAULT '',
  dedup_key TEXT,
  payload_hash TEXT NOT NULL,
  request_bytes INTEGER NOT NULL DEFAULT 0,
  safe_summary_json TEXT NOT NULL DEFAULT '{}',
  normalized_event_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  job_id TEXT REFERENCES agent_job(id),
  status TEXT NOT NULL
    CHECK (status IN (
      'REJECTED_AUTH', 'REJECTED', 'IGNORED', 'ACCEPTED', 'DISPATCH_PENDING',
      'JOB_CREATED', 'DISPATCH_FAILED'
    )),
  auth_result TEXT NOT NULL DEFAULT '',
  filter_result TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  dispatched_at TEXT,
  completed_at TEXT,
  UNIQUE(trigger_id, dedup_key)
);

-- sqlite-only
CREATE TABLE webhook_replay_nonce (
  trigger_id TEXT NOT NULL REFERENCES webhook_trigger_definition(id),
  nonce_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(trigger_id, nonce_hash)
);

-- sqlite-only
CREATE TABLE webhook_outbox (
  id TEXT PRIMARY KEY,
  webhook_event_id TEXT NOT NULL UNIQUE REFERENCES webhook_event(id),
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'publishing', 'published', 'dead')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  published_at TEXT,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE business_application (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL,
  owner_user_id TEXT REFERENCES app_user(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE business_application_revision (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  agent_publication_id TEXT REFERENCES agent_publication(id),
  workflow_publication_id TEXT REFERENCES agent_workflow_publication(id),
  session_policy_json TEXT NOT NULL DEFAULT '{}',
  execution_policy_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{"valid":false,"errors":[]}',
  config_hash TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, revision)
);

-- sqlite-only
CREATE TABLE business_application_revision_trigger (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  trigger_type TEXT NOT NULL
    CHECK (trigger_type IN ('dingtalk_private', 'dingtalk_group', 'webhook')),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  routing_key TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  actor_policy TEXT NOT NULL
    CHECK (actor_policy IN ('CURRENT_SENDER', 'SERVICE_ACCOUNT')),
  service_account_user_id TEXT REFERENCES app_user(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order),
  UNIQUE(revision_id, trigger_type, connector_id, normalized_routing_key)
);

-- sqlite-only
CREATE TABLE business_application_revision_delivery (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  delivery_type TEXT NOT NULL
    CHECK (delivery_type IN (
      'reply_original', 'dingtalk_private', 'dingtalk_group', 'webhook_callback'
    )),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order)
);

-- sqlite-only
CREATE TABLE business_application_publication (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  UNIQUE(application_id, revision),
  UNIQUE(revision_id)
);

-- sqlite-only
CREATE TABLE business_application_deployment (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES business_application(id),
  environment TEXT NOT NULL,
  publication_id TEXT REFERENCES business_application_publication(id),
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  activated_by TEXT NOT NULL DEFAULT '',
  activated_at TEXT,
  deactivated_by TEXT NOT NULL DEFAULT '',
  deactivated_at TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, environment)
);

-- sqlite-only
CREATE TABLE business_application_active_route (
  id TEXT PRIMARY KEY,
  deployment_id TEXT NOT NULL REFERENCES business_application_deployment(id),
  application_id TEXT NOT NULL REFERENCES business_application(id),
  publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
  environment TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(environment, trigger_type, connector_id, normalized_routing_key),
  UNIQUE(deployment_id, trigger_type, connector_id, normalized_routing_key)
);

-- sqlite-only
CREATE TABLE model_connection (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL
    CHECK (protocol IN ('anthropic_compatible')),
  current_revision_id TEXT,
  status TEXT NOT NULL DEFAULT 'rotation_required'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE model_connection_revision (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES model_connection(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  config_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  api_key_secret_id TEXT REFERENCES platform_secret(id),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(connection_id, revision)
);

-- sqlite-only
CREATE TABLE channel_connector_runtime (
    connector_id text primary key references integration_connector(id),
    runtime_id text not null default '',
    runtime_status text not null default 'STOPPED'
        check (runtime_status in (
            'STOPPED', 'STARTING', 'CONNECTED', 'REGISTERED',
            'RECONNECTING', 'AUTH_FAILED', 'ERROR'
        )),
    loaded_revision integer,
    connected integer not null default 0,
    registered integer not null default 0,
    connected_at text,
    disconnected_at text,
    last_message_at text,
    last_heartbeat_at text,
    last_error_code text not null default '',
    last_error_summary text not null default '',
    updated_at text not null
);

-- sqlite-only
CREATE TABLE channel_runtime_lease (
    lease_name text primary key,
    runtime_id text not null,
    lease_token text not null,
    expires_at text not null,
    updated_at text not null
);

-- sqlite-only
CREATE TABLE channel_ingress_event (
    id text primary key,
    source_type text not null,
    connector_id text not null references integration_connector(id),
    external_event_id text not null,
    correlation_id text not null,
    payload_hash text not null,
    safe_summary_json text not null default '{}',
    normalized_event_json text not null default '{}',
    reply_credential_ciphertext text not null default '',
    status text not null default 'ACCEPTED'
        check (status in (
            'ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING',
            'JOB_CREATED', 'REJECTED', 'DISPATCH_FAILED'
        )),
    job_id text references agent_job(id),
    error_code text not null default '',
    error_summary text not null default '',
    request_bytes integer not null default 0,
    received_at text not null,
    dispatched_at text,
    completed_at text,
    unique (connector_id, external_event_id)
);

-- sqlite-only
CREATE TABLE channel_ingress_outbox (
    id text primary key,
    channel_event_id text not null unique references channel_ingress_event(id),
    correlation_id text not null,
    status text not null default 'pending'
        check (status in ('pending', 'publishing', 'published', 'dead')),
    attempt_count integer not null default 0,
    next_attempt_at text not null,
    claimed_by text not null default '',
    claimed_at text,
    last_error_summary text not null default '',
    created_at text not null,
    published_at text,
    updated_at text not null
);

-- sqlite-only
CREATE TABLE dingtalk_identity_candidate (
    id text primary key,
    tenant_code text not null,
    external_subject_id text not null,
    display_name text not null default '',
    first_seen_at text not null,
    last_seen_at text not null,
    observation_count integer not null default 0
        check (observation_count >= 0),
    revision integer not null default 1
        check (revision >= 1),
    created_at text not null,
    updated_at text not null, dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id),
    unique (tenant_code, external_subject_id)
);

-- sqlite-only
CREATE TABLE dingtalk_identity_candidate_message (
    id text primary key,
    candidate_id text not null
        references dingtalk_identity_candidate(id) on delete cascade,
    source_ingress_event_id text not null unique
        references channel_ingress_event(id),
    connector_id text not null
        references integration_connector(id),
    robot_code text not null default '',
    conversation_type text not null
        check (conversation_type in ('direct', 'group')),
    conversation_id text not null default '',
    message_kind text not null default 'unsupported',
    safe_text text not null default '',
    text_truncated integer not null default 0
        check (text_truncated in (0, 1)),
    attachment_type text not null default '',
    attachment_name text not null default '',
    attachment_size integer,
    occurred_at text not null,
    received_at text not null,
    created_at text not null
);

-- sqlite-only
CREATE TABLE rbac_role_admin_capability (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  capability_code TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_code TEXT NOT NULL DEFAULT '*',
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, capability_code, resource_type, resource_code)
);

-- sqlite-only
CREATE TABLE rbac_role_application_access (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  application_id TEXT NOT NULL REFERENCES business_application(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, application_id)
);

-- sqlite-only
CREATE TABLE rbac_role_application_scope (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL REFERENCES rbac_role_application_access(id),
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  scope_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, scope_key)
);

-- sqlite-only
CREATE TABLE job_dispatch_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED', 'DEAD')),
  attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 8
    CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0
    CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 3
    CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  published_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (attempt_count <= max_attempts),
  CHECK (replay_count <= max_replay_count)
);

-- sqlite-only
CREATE TABLE job_dispatch_cutover_quarantine (
  id TEXT PRIMARY KEY,
  source_queue TEXT NOT NULL,
  message_digest TEXT NOT NULL,
  job_id TEXT,
  reason_code TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  observed_by TEXT NOT NULL,
  UNIQUE (source_queue, message_digest)
);

-- sqlite-only
CREATE TABLE delivery_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  result_artifact_id TEXT NOT NULL REFERENCES agent_artifact(id),
  application_publication_id TEXT NOT NULL DEFAULT '',
  delivery_binding_json TEXT NOT NULL,
  target_summary TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN (
      'PENDING',
      'RUNNING',
      'RETRY_WAIT',
      'SUCCEEDED',
      'FAILED',
      'DEAD',
      'SKIPPED'
    )
  ),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0 CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 0 CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claim_token TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  claim_expires_at TEXT,
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  finished_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(job_id, result_artifact_id)
);

-- sqlite-only
CREATE TABLE platform_secret_change_event (
  id TEXT PRIMARY KEY,
  secret_id TEXT NOT NULL REFERENCES platform_secret(id),
  secret_revision INTEGER NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT,
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  processed_at TEXT,
  UNIQUE(secret_id, secret_revision, action)
);

-- sqlite-only
CREATE TABLE platform_resource_draft (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL UNIQUE REFERENCES platform_resource(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  config_json TEXT NOT NULL DEFAULT '{}',
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_resource_verification (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  draft_id TEXT REFERENCES platform_resource_draft(id) ON DELETE SET NULL,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL
    CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  provider_contract_version TEXT NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(resource_id, draft_revision, content_hash)
);

-- sqlite-only
CREATE TABLE platform_resource_revision (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  provider_contract_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL REFERENCES platform_resource_verification(id),
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(resource_id, revision),
  UNIQUE(resource_id, id)
);

-- sqlite-only
CREATE TABLE resource_reset_operation (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL
    CHECK (
      status IN (
        'REPORTED',
        'PREPARING',
        'PREPARED',
        'CONFIRMED',
        'APPLYING',
        'APPLIED',
        'VERIFIED',
        'ABORTED',
        'FAILED'
      )
    ),
  target_kinds_json TEXT NOT NULL DEFAULT '[]',
  inventory_digest TEXT NOT NULL DEFAULT '',
  database_fingerprint TEXT NOT NULL DEFAULT '',
  backup_reference TEXT NOT NULL DEFAULT '',
  impact_summary_json TEXT NOT NULL DEFAULT '{}',
  prepared_by TEXT NOT NULL DEFAULT '',
  prepared_at TEXT,
  confirmed_by TEXT NOT NULL DEFAULT '',
  confirmed_at TEXT,
  applied_by TEXT NOT NULL DEFAULT '',
  applied_at TEXT,
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  correlation_id TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE dingtalk_enterprise (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
  corp_id TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
    CHECK (status IN (
      'PENDING_VERIFICATION', 'ACTIVE', 'DISABLED', 'ARCHIVED'
    )),
  verification_event_id TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (corp_id IS NULL OR length(trim(corp_id)) BETWEEN 1 AND 128),
  CHECK (status <> 'ACTIVE' OR (corp_id IS NOT NULL AND verified_at IS NOT NULL))
);

-- sqlite-only
CREATE TABLE dingtalk_identity_application_observation (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  last_ingress_event_id TEXT NOT NULL REFERENCES channel_ingress_event(id),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(external_identity_id, connector_id)
);

-- sqlite-only
CREATE TABLE dingtalk_identity_nickname_audit (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  source_ingress_event_id TEXT NOT NULL UNIQUE REFERENCES channel_ingress_event(id),
  previous_nickname TEXT NOT NULL DEFAULT '',
  current_nickname TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE platform_resource (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  resource_kind TEXT NOT NULL
    CHECK (resource_kind IN ('database', 'redis', 'loki')),
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('global', 'environment', 'base', 'workshop')),
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, placement TEXT CHECK (placement IN ('cloud', 'edge')),
  CHECK (
    (scope_type = 'global' AND environment_id IS NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'environment' AND environment_id IS NOT NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'base' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'workshop' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NOT NULL)
  )
);

-- sqlite-only
CREATE TABLE loki_resource_draft_test_session (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  draft_id TEXT NOT NULL REFERENCES platform_resource_draft(id) ON DELETE CASCADE,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  actor_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'EXPIRED')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(id, resource_id, draft_id, content_hash)
);

-- sqlite-only
CREATE TABLE resource_reset_target (
  operation_id TEXT NOT NULL REFERENCES resource_reset_operation(id),
  target_type TEXT NOT NULL
    CHECK (
      target_type IN (
        'resource',
        'draft',
        'verification',
        'revision',
        'legacy_binding',
        'application_binding',
        'handler_resource_binding',
        'builtin_tool_resource_mapping',
        'builtin_tool_draft_resource_mapping',
        'builtin_tool_resolution',
        'resource_runtime_state',
        'application_runtime_state',
        'activation'
      )
    ),
  target_id TEXT NOT NULL,
  target_revision INTEGER NOT NULL DEFAULT 0 CHECK (target_revision >= 0),
  target_code TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL CHECK (action IN ('DELETE', 'INVALIDATE', 'BLOCK')),
  item_digest TEXT NOT NULL CHECK (length(item_digest) = 64),
  apply_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (apply_status IN ('PENDING', 'APPLIED', 'SKIPPED', 'FAILED')),
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(operation_id, target_type, target_id)
);

-- sqlite-only
CREATE TABLE agent_runtime_event (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL
    CHECK (event_type IN ('execution_started', 'tool_event', 'assistant_text', 'terminal')),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);

-- sqlite-only
CREATE TABLE agent_runtime_terminal_ledger (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL,
  events_json TEXT NOT NULL,
  terminal_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_runtime_invocation_claim (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_kind TEXT NOT NULL
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')),
  owner_instance_id TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE agent_runtime_invocation_event (
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (invocation_id, sequence)
);

-- sqlite-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order)
);

-- sqlite-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      tool_identifier
    )
);

-- sqlite-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      tool_identifier
    )
);

-- sqlite-only
CREATE TABLE agent_job_mcp_tool_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  application_publication_id TEXT
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  authorization_hash TEXT NOT NULL CHECK (length(authorization_hash) = 64),
  created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE rbac_role_application_mcp_tool (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL
    REFERENCES rbac_role_application_access(id),
  tool_identifier TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, tool_identifier)
);

-- sqlite-only
CREATE TABLE ones_identity_verification_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  external_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  teams_json TEXT NOT NULL DEFAULT '[]',
  verified_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

-- postgres-only
CREATE TABLE agent_session (
  id TEXT PRIMARY KEY,
  dingding_conversation_id TEXT NOT NULL,
  dingding_user_id TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'dingding',
  project_code TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, source_channel TEXT NOT NULL DEFAULT 'dingding', source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default', external_conversation_id TEXT NOT NULL DEFAULT '', requester_id TEXT NOT NULL DEFAULT '', requester_display_name TEXT NOT NULL DEFAULT '', routing_context_json TEXT NOT NULL DEFAULT '{}', reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}', session_key TEXT NOT NULL DEFAULT '', conversation_type TEXT NOT NULL DEFAULT 'direct', bot_identity TEXT NOT NULL DEFAULT '', summary_text TEXT NOT NULL DEFAULT '', summary_through_sequence INTEGER NOT NULL DEFAULT 0, summary_version INTEGER NOT NULL DEFAULT 0, message_sequence INTEGER NOT NULL DEFAULT 0, last_message_at TEXT, external_identity_id TEXT, business_application_id TEXT, business_application_code TEXT NOT NULL DEFAULT '', conversation_mode TEXT NOT NULL DEFAULT 'legacy', recent_message_limit INTEGER, session_policy_json TEXT NOT NULL DEFAULT '{}', application_publication_id TEXT, execution_scope_hash TEXT, isolation_key_version INTEGER NOT NULL DEFAULT 2, history_read_only INTEGER NOT NULL DEFAULT 0);

-- postgres-only
CREATE TABLE agent_job (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
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
, source_channel TEXT NOT NULL DEFAULT 'dingding', source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default', external_event_id TEXT NOT NULL DEFAULT '', requester_id TEXT NOT NULL DEFAULT '', routing_context_json TEXT NOT NULL DEFAULT '{}', reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}', internal_user_id TEXT, external_identity_id TEXT, agent_definition_id TEXT, agent_publication_id TEXT, agent_revision INTEGER, agent_config_hash TEXT NOT NULL DEFAULT '', webhook_event_id TEXT, webhook_trigger_id TEXT, webhook_trigger_publication_id TEXT, last_error_code TEXT NOT NULL DEFAULT '', last_error_at TEXT, next_retry_at TEXT, business_application_id TEXT, business_application_code TEXT NOT NULL DEFAULT '', business_application_publication_id TEXT, business_application_deployment_id TEXT, business_application_route_id TEXT, business_application_config_hash TEXT NOT NULL DEFAULT '', business_application_runtime_status TEXT NOT NULL DEFAULT '', business_application_route_decision_json TEXT NOT NULL DEFAULT '{}', execution_policy_json TEXT, execution_policy_tool_call_count INTEGER NOT NULL DEFAULT 0, execution_policy_exhausted INTEGER NOT NULL DEFAULT 0, model_runtime_provenance_json TEXT, agent_runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (agent_runtime_kind IN ('python-v1', 'typescript-v1')), agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.0'
    CHECK (agent_runtime_protocol_version = '1.0'));

-- postgres-only
CREATE TABLE agent_message (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  job_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
, external_message_id TEXT NOT NULL DEFAULT '', sender_id TEXT NOT NULL DEFAULT '', sender_display_name TEXT NOT NULL DEFAULT '', message_type TEXT NOT NULL DEFAULT 'text', sequence_no INTEGER NOT NULL DEFAULT 0, content_status TEXT NOT NULL DEFAULT 'READY', safe_metadata_json TEXT NOT NULL DEFAULT '{}');

-- postgres-only
CREATE TABLE agent_step (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  step_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE audit_event (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  event_type TEXT NOT NULL,
  actor_id TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_tool_call (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  request_payload TEXT NOT NULL,
  response_summary TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'low',
  audit_id TEXT,
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_artifact (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  file_path TEXT,
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE integration_connector (
  id TEXT PRIMARY KEY,
  connector_type TEXT NOT NULL,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, allow_ingress INTEGER NOT NULL DEFAULT 0, allow_delivery INTEGER NOT NULL DEFAULT 0, secret_ref TEXT NOT NULL DEFAULT '', endpoint_ref TEXT NOT NULL DEFAULT '', host_allowlist TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1, deleted integer not null default 0, dingtalk_enterprise_id TEXT);

-- postgres-only
CREATE TABLE delivery_attempt (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  route_type TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  target_summary TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
, delivery_outbox_id TEXT, replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0), attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0), correlation_id TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '');

-- postgres-only
CREATE TABLE delivery_chunk (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  chunk_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  error_message TEXT,
  created_at TEXT NOT NULL
, delivery_outbox_id TEXT, replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0), attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0), idempotency_key TEXT NOT NULL DEFAULT '', payload_hash TEXT NOT NULL DEFAULT '', sent_at TEXT);

-- postgres-only
CREATE TABLE platform_environment (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_base (
  id TEXT PRIMARY KEY,
  environment_id TEXT NOT NULL,
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  engine TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(environment_id, code)
);

-- postgres-only
CREATE TABLE platform_workshop (
  id TEXT PRIMARY KEY,
  base_id TEXT NOT NULL,
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  table_prefix TEXT NOT NULL DEFAULT '',
  redis_key_prefix TEXT NOT NULL DEFAULT '',
  loki_labels_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(base_id, code)
);

-- postgres-only
CREATE TABLE platform_secret_reference (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  ref TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_config_audit (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_workflow_template (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  entry_node_key TEXT NOT NULL DEFAULT '',
  graph_schema_version INTEGER NOT NULL DEFAULT 1,
  graph_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_workflow_node (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  node_key TEXT NOT NULL,
  node_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  position_json TEXT NOT NULL DEFAULT '{}',
  config_json TEXT NOT NULL DEFAULT '{}',
  ui_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, node_key)
);

-- postgres-only
CREATE TABLE agent_workflow_edge (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  edge_key TEXT NOT NULL,
  source_node_key TEXT NOT NULL,
  target_node_key TEXT NOT NULL,
  source_port TEXT NOT NULL DEFAULT '',
  target_port TEXT NOT NULL DEFAULT '',
  condition_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, edge_key)
);

-- postgres-only
CREATE TABLE agent_workflow_publication (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  graph_snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(template_id, version)
);

-- postgres-only
CREATE TABLE platform_secret (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL DEFAULT 'encrypted_db',
  ref TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  active_version INTEGER NOT NULL DEFAULT 0,
  masked_summary TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_secret_version (
  id TEXT PRIMARY KEY,
  secret_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  ciphertext TEXT NOT NULL,
  nonce TEXT NOT NULL,
  key_id TEXT NOT NULL DEFAULT '',
  algorithm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(secret_id, version)
);

-- postgres-only
CREATE TABLE platform_runtime_config_definition (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  value_type TEXT NOT NULL,
  default_json TEXT NOT NULL DEFAULT 'null',
  sensitive INTEGER NOT NULL DEFAULT 0,
  bootstrap_only INTEGER NOT NULL DEFAULT 0,
  service_names_json TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_runtime_config_value (
  id TEXT PRIMARY KEY,
  definition_id TEXT NOT NULL,
  key TEXT NOT NULL,
  scope_type TEXT NOT NULL DEFAULT 'global',
  scope_code TEXT NOT NULL DEFAULT '*',
  service_name TEXT NOT NULL DEFAULT '',
  value_json TEXT NOT NULL DEFAULT 'null',
  secret_ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(key, scope_type, scope_code, service_name)
);

-- postgres-only
CREATE TABLE message_attachment (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  declared_mime TEXT NOT NULL DEFAULT '',
  detected_mime TEXT NOT NULL DEFAULT '',
  declared_size INTEGER,
  size_bytes INTEGER,
  sha256 TEXT NOT NULL DEFAULT '',
  object_bucket TEXT NOT NULL DEFAULT '',
  object_key TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  failure_code TEXT NOT NULL DEFAULT '',
  retry_count INTEGER NOT NULL DEFAULT 0,
  source_credential_ciphertext TEXT NOT NULL DEFAULT '',
  source_credential_type TEXT NOT NULL DEFAULT '',
  source_credential_expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  expires_at TEXT,
  UNIQUE(message_id, ordinal)
);

-- postgres-only
CREATE TABLE attachment_content (
  id TEXT PRIMARY KEY,
  attachment_id TEXT NOT NULL UNIQUE,
  plain_text TEXT NOT NULL,
  segments_json TEXT NOT NULL DEFAULT '[]',
  parser_version TEXT NOT NULL,
  char_count INTEGER NOT NULL DEFAULT 0,
  truncated INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE app_user (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, account_type TEXT NOT NULL DEFAULT 'human'
  CHECK (account_type IN ('human', 'service')));

-- postgres-only
CREATE TABLE user_password_credential (
  user_id TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  password_changed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE user_external_identity (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  tenant_code TEXT NOT NULL,
  external_subject_id TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  union_id TEXT NOT NULL DEFAULT '',
  open_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  verified_at TEXT,
  last_seen_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, dingtalk_enterprise_id TEXT, display_name_observed_at TEXT, display_name_event_id TEXT NOT NULL DEFAULT '', display_name_source_connector_id TEXT NOT NULL DEFAULT '',
  UNIQUE(provider, tenant_code, external_subject_id)
);

-- postgres-only
CREATE TABLE user_session (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  csrf_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  idle_expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  revoked_at TEXT,
  user_agent_summary TEXT NOT NULL DEFAULT '',
  remote_address_summary TEXT NOT NULL DEFAULT ''
);

-- postgres-only
CREATE TABLE rbac_role (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, origin TEXT NOT NULL DEFAULT 'custom'
  CHECK (origin IN ('system', 'custom')), protected INTEGER NOT NULL DEFAULT 0
  CHECK (protected IN (0, 1)), purpose_tags_json TEXT NOT NULL DEFAULT '[]', metadata_revision INTEGER NOT NULL DEFAULT 1, admin_revision INTEGER NOT NULL DEFAULT 1, business_revision INTEGER NOT NULL DEFAULT 1, membership_revision INTEGER NOT NULL DEFAULT 1);

-- postgres-only
CREATE TABLE rbac_user_role (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, expires_at TEXT, assigned_by TEXT NOT NULL DEFAULT '', assignment_source TEXT NOT NULL DEFAULT 'manual',
  UNIQUE(user_id, role_id)
);

-- postgres-only
CREATE TABLE identity_migration_audit (
  id TEXT PRIMARY KEY,
  legacy_subject_type TEXT NOT NULL,
  legacy_subject_code TEXT NOT NULL,
  tenant_code TEXT NOT NULL DEFAULT '',
  internal_user_id TEXT,
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'enabled',
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, classification TEXT NOT NULL DEFAULT 'business'
    CHECK (classification IN ('business', 'internal_diagnostic')), runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')));

-- postgres-only
CREATE TABLE agent_revision (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL DEFAULT '',
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(agent_id, revision)
);

-- postgres-only
CREATE TABLE agent_publication (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL, runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')),
  UNIQUE(agent_id, revision)
);

-- postgres-only
CREATE TABLE agent_skill_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL,
  skill_code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, skill_code)
);

-- postgres-only
CREATE TABLE agent_channel_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, direction, connector_id)
);

-- postgres-only
CREATE TABLE webhook_trigger_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  public_id TEXT NOT NULL UNIQUE,
  connector_id TEXT NOT NULL,
  service_account_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'disabled'
    CHECK (status IN ('enabled', 'disabled')),
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE webhook_trigger_revision (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  schema_version INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL,
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

-- postgres-only
CREATE TABLE webhook_trigger_publication (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL,
  agent_revision INTEGER NOT NULL,
  agent_config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'revoked')),
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(trigger_id, revision)
);

-- postgres-only
CREATE TABLE webhook_event (
  id TEXT PRIMARY KEY,
  trigger_id TEXT NOT NULL,
  trigger_publication_id TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL,
  service_account_id TEXT NOT NULL,
  external_event_id TEXT NOT NULL DEFAULT '',
  dedup_key TEXT,
  payload_hash TEXT NOT NULL,
  request_bytes INTEGER NOT NULL DEFAULT 0,
  safe_summary_json TEXT NOT NULL DEFAULT '{}',
  normalized_event_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  job_id TEXT,
  status TEXT NOT NULL
    CHECK (status IN (
      'REJECTED_AUTH', 'REJECTED', 'IGNORED', 'ACCEPTED', 'DISPATCH_PENDING',
      'JOB_CREATED', 'DISPATCH_FAILED'
    )),
  auth_result TEXT NOT NULL DEFAULT '',
  filter_result TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  dispatched_at TEXT,
  completed_at TEXT,
  UNIQUE(trigger_id, dedup_key)
);

-- postgres-only
CREATE TABLE webhook_replay_nonce (
  trigger_id TEXT NOT NULL,
  nonce_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(trigger_id, nonce_hash)
);

-- postgres-only
CREATE TABLE webhook_outbox (
  id TEXT PRIMARY KEY,
  webhook_event_id TEXT NOT NULL UNIQUE,
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'publishing', 'published', 'dead')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  published_at TEXT,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE business_application (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL,
  owner_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE business_application_revision (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'validated', 'published')),
  agent_publication_id TEXT,
  workflow_publication_id TEXT,
  session_policy_json TEXT NOT NULL DEFAULT '{}',
  execution_policy_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{"valid":false,"errors":[]}',
  config_hash TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, revision)
);

-- postgres-only
CREATE TABLE business_application_revision_trigger (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL,
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  trigger_type TEXT NOT NULL
    CHECK (trigger_type IN ('dingtalk_private', 'dingtalk_group', 'webhook')),
  connector_id TEXT NOT NULL,
  routing_key TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  actor_policy TEXT NOT NULL
    CHECK (actor_policy IN ('CURRENT_SENDER', 'SERVICE_ACCOUNT')),
  service_account_user_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order),
  UNIQUE(revision_id, trigger_type, connector_id, normalized_routing_key)
);

-- postgres-only
CREATE TABLE business_application_revision_delivery (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL,
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  delivery_type TEXT NOT NULL
    CHECK (delivery_type IN (
      'reply_original', 'dingtalk_private', 'dingtalk_group', 'webhook_callback'
    )),
  connector_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, binding_order)
);

-- postgres-only
CREATE TABLE business_application_publication (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL,
  revision_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  UNIQUE(application_id, revision),
  UNIQUE(revision_id)
);

-- postgres-only
CREATE TABLE business_application_deployment (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL,
  environment TEXT NOT NULL,
  publication_id TEXT,
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  activated_by TEXT NOT NULL DEFAULT '',
  activated_at TEXT,
  deactivated_by TEXT NOT NULL DEFAULT '',
  deactivated_at TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(application_id, environment)
);

-- postgres-only
CREATE TABLE business_application_active_route (
  id TEXT PRIMARY KEY,
  deployment_id TEXT NOT NULL,
  application_id TEXT NOT NULL,
  publication_id TEXT NOT NULL,
  environment TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  normalized_routing_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(environment, trigger_type, connector_id, normalized_routing_key),
  UNIQUE(deployment_id, trigger_type, connector_id, normalized_routing_key)
);

-- postgres-only
CREATE TABLE model_connection (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL
    CHECK (protocol IN ('anthropic_compatible')),
  current_revision_id TEXT,
  status TEXT NOT NULL DEFAULT 'rotation_required'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE model_connection_revision (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  config_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  api_key_secret_id TEXT,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(connection_id, revision)
);

-- postgres-only
CREATE TABLE channel_connector_runtime (
    connector_id text primary key,
    runtime_id text not null default '',
    runtime_status text not null default 'STOPPED'
        check (runtime_status in (
            'STOPPED', 'STARTING', 'CONNECTED', 'REGISTERED',
            'RECONNECTING', 'AUTH_FAILED', 'ERROR'
        )),
    loaded_revision integer,
    connected integer not null default 0,
    registered integer not null default 0,
    connected_at text,
    disconnected_at text,
    last_message_at text,
    last_heartbeat_at text,
    last_error_code text not null default '',
    last_error_summary text not null default '',
    updated_at text not null
);

-- postgres-only
CREATE TABLE channel_runtime_lease (
    lease_name text primary key,
    runtime_id text not null,
    lease_token text not null,
    expires_at text not null,
    updated_at text not null
);

-- postgres-only
CREATE TABLE channel_ingress_event (
    id text primary key,
    source_type text not null,
    connector_id text not null,
    external_event_id text not null,
    correlation_id text not null,
    payload_hash text not null,
    safe_summary_json text not null default '{}',
    normalized_event_json text not null default '{}',
    reply_credential_ciphertext text not null default '',
    status text not null default 'ACCEPTED'
        check (status in (
            'ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING',
            'JOB_CREATED', 'REJECTED', 'DISPATCH_FAILED'
        )),
    job_id text,
    error_code text not null default '',
    error_summary text not null default '',
    request_bytes integer not null default 0,
    received_at text not null,
    dispatched_at text,
    completed_at text,
    unique (connector_id, external_event_id)
);

-- postgres-only
CREATE TABLE channel_ingress_outbox (
    id text primary key,
    channel_event_id text not null unique,
    correlation_id text not null,
    status text not null default 'pending'
        check (status in ('pending', 'publishing', 'published', 'dead')),
    attempt_count integer not null default 0,
    next_attempt_at text not null,
    claimed_by text not null default '',
    claimed_at text,
    last_error_summary text not null default '',
    created_at text not null,
    published_at text,
    updated_at text not null
);

-- postgres-only
CREATE TABLE dingtalk_identity_candidate (
    id text primary key,
    tenant_code text not null,
    external_subject_id text not null,
    display_name text not null default '',
    first_seen_at text not null,
    last_seen_at text not null,
    observation_count integer not null default 0
        check (observation_count >= 0),
    revision integer not null default 1
        check (revision >= 1),
    created_at text not null,
    updated_at text not null, dingtalk_enterprise_id TEXT,
    unique (tenant_code, external_subject_id)
);

-- postgres-only
CREATE TABLE dingtalk_identity_candidate_message (
    id text primary key,
    candidate_id text not null,
    source_ingress_event_id text not null unique,
    connector_id text not null,
    robot_code text not null default '',
    conversation_type text not null
        check (conversation_type in ('direct', 'group')),
    conversation_id text not null default '',
    message_kind text not null default 'unsupported',
    safe_text text not null default '',
    text_truncated integer not null default 0
        check (text_truncated in (0, 1)),
    attachment_type text not null default '',
    attachment_name text not null default '',
    attachment_size integer,
    occurred_at text not null,
    received_at text not null,
    created_at text not null
);

-- postgres-only
CREATE TABLE rbac_role_admin_capability (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL,
  capability_code TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_code TEXT NOT NULL DEFAULT '*',
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, capability_code, resource_type, resource_code)
);

-- postgres-only
CREATE TABLE rbac_role_application_access (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL,
  application_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, application_id)
);

-- postgres-only
CREATE TABLE rbac_role_application_scope (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  base_id TEXT,
  workshop_id TEXT,
  scope_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, scope_key)
);

-- postgres-only
CREATE TABLE job_dispatch_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL UNIQUE,
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED', 'DEAD')),
  attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 8
    CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0
    CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 3
    CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  published_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (attempt_count <= max_attempts),
  CHECK (replay_count <= max_replay_count)
);

-- postgres-only
CREATE TABLE job_dispatch_cutover_quarantine (
  id TEXT PRIMARY KEY,
  source_queue TEXT NOT NULL,
  message_digest TEXT NOT NULL,
  job_id TEXT,
  reason_code TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  observed_by TEXT NOT NULL,
  UNIQUE (source_queue, message_digest)
);

-- postgres-only
CREATE TABLE delivery_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL,
  result_artifact_id TEXT NOT NULL,
  application_publication_id TEXT NOT NULL DEFAULT '',
  delivery_binding_json TEXT NOT NULL,
  target_summary TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN (
      'PENDING',
      'RUNNING',
      'RETRY_WAIT',
      'SUCCEEDED',
      'FAILED',
      'DEAD',
      'SKIPPED'
    )
  ),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0 CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 0 CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claim_token TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  claim_expires_at TEXT,
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  finished_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(job_id, result_artifact_id)
);

-- postgres-only
CREATE TABLE platform_secret_change_event (
  id TEXT PRIMARY KEY,
  secret_id TEXT NOT NULL,
  secret_revision INTEGER NOT NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT,
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  processed_at TEXT,
  UNIQUE(secret_id, secret_revision, action)
);

-- postgres-only
CREATE TABLE platform_resource_draft (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL UNIQUE,
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  config_json TEXT NOT NULL DEFAULT '{}',
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_resource_verification (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL,
  draft_id TEXT,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL
    CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  provider_contract_version TEXT NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(resource_id, draft_revision, content_hash)
);

-- postgres-only
CREATE TABLE platform_resource_revision (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  provider_contract_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(resource_id, revision),
  UNIQUE(resource_id, id)
);

-- postgres-only
CREATE TABLE resource_reset_operation (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL
    CHECK (
      status IN (
        'REPORTED',
        'PREPARING',
        'PREPARED',
        'CONFIRMED',
        'APPLYING',
        'APPLIED',
        'VERIFIED',
        'ABORTED',
        'FAILED'
      )
    ),
  target_kinds_json TEXT NOT NULL DEFAULT '[]',
  inventory_digest TEXT NOT NULL DEFAULT '',
  database_fingerprint TEXT NOT NULL DEFAULT '',
  backup_reference TEXT NOT NULL DEFAULT '',
  impact_summary_json TEXT NOT NULL DEFAULT '{}',
  prepared_by TEXT NOT NULL DEFAULT '',
  prepared_at TEXT,
  confirmed_by TEXT NOT NULL DEFAULT '',
  confirmed_at TEXT,
  applied_by TEXT NOT NULL DEFAULT '',
  applied_at TEXT,
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  correlation_id TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE dingtalk_enterprise (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
  corp_id TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
    CHECK (status IN (
      'PENDING_VERIFICATION', 'ACTIVE', 'DISABLED', 'ARCHIVED'
    )),
  verification_event_id TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (corp_id IS NULL OR length(trim(corp_id)) BETWEEN 1 AND 128),
  CHECK (status <> 'ACTIVE' OR (corp_id IS NOT NULL AND verified_at IS NOT NULL))
);

-- postgres-only
CREATE TABLE dingtalk_identity_application_observation (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  last_ingress_event_id TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(external_identity_id, connector_id)
);

-- postgres-only
CREATE TABLE dingtalk_identity_nickname_audit (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  source_ingress_event_id TEXT NOT NULL UNIQUE,
  previous_nickname TEXT NOT NULL DEFAULT '',
  current_nickname TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE platform_resource (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  resource_kind TEXT NOT NULL
    CHECK (resource_kind IN ('database', 'redis', 'loki')),
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('global', 'environment', 'base', 'workshop')),
  environment_id TEXT,
  base_id TEXT,
  workshop_id TEXT,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, placement TEXT CHECK (placement IN ('cloud', 'edge')),
  CHECK (
    (scope_type = 'global' AND environment_id IS NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'environment' AND environment_id IS NOT NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'base' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'workshop' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NOT NULL)
  )
);

-- postgres-only
CREATE TABLE loki_resource_draft_test_session (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  actor_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'EXPIRED')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(id, resource_id, draft_id, content_hash)
);

-- postgres-only
CREATE TABLE resource_reset_target (
  operation_id TEXT NOT NULL,
  target_type TEXT NOT NULL
    CHECK (
      target_type IN (
        'resource',
        'draft',
        'verification',
        'revision',
        'legacy_binding',
        'application_binding',
        'handler_resource_binding',
        'builtin_tool_resource_mapping',
        'builtin_tool_draft_resource_mapping',
        'builtin_tool_resolution',
        'resource_runtime_state',
        'application_runtime_state',
        'activation'
      )
    ),
  target_id TEXT NOT NULL,
  target_revision INTEGER NOT NULL DEFAULT 0 CHECK (target_revision >= 0),
  target_code TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL CHECK (action IN ('DELETE', 'INVALIDATE', 'BLOCK')),
  item_digest TEXT NOT NULL CHECK (length(item_digest) = 64),
  apply_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (apply_status IN ('PENDING', 'APPLIED', 'SKIPPED', 'FAILED')),
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(operation_id, target_type, target_id)
);

-- postgres-only
CREATE TABLE agent_runtime_event (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL
    CHECK (event_type IN ('execution_started', 'tool_event', 'assistant_text', 'terminal')),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);

-- postgres-only
CREATE TABLE agent_runtime_terminal_ledger (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL,
  events_json TEXT NOT NULL,
  terminal_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_runtime_invocation_claim (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_kind TEXT NOT NULL
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')),
  owner_instance_id TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE agent_runtime_invocation_event (
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (invocation_id, sequence)
);

-- postgres-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL,
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order)
);

-- postgres-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL,
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order)
);

-- postgres-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL,
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order)
);

-- postgres-only
CREATE TABLE agent_job_mcp_tool_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE,
  application_publication_id TEXT,
  agent_publication_id TEXT NOT NULL,
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  authorization_hash TEXT NOT NULL CHECK (length(authorization_hash) = 64),
  created_at TEXT NOT NULL
);

-- postgres-only
CREATE TABLE rbac_role_application_mcp_tool (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, tool_identifier)
);

-- postgres-only
CREATE TABLE ones_identity_verification_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  external_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  teams_json TEXT NOT NULL DEFAULT '[]',
  verified_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

-- postgres-only
ALTER TABLE "agent_job" ADD CONSTRAINT "fk_agent_job_0" FOREIGN KEY ("webhook_trigger_publication_id") REFERENCES "webhook_trigger_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job" ADD CONSTRAINT "fk_agent_job_1" FOREIGN KEY ("webhook_trigger_id") REFERENCES "webhook_trigger_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job" ADD CONSTRAINT "fk_agent_job_2" FOREIGN KEY ("webhook_event_id") REFERENCES "webhook_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job" ADD CONSTRAINT "fk_agent_job_3" FOREIGN KEY ("session_id") REFERENCES "agent_session" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_message" ADD CONSTRAINT "fk_agent_message_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_message" ADD CONSTRAINT "fk_agent_message_1" FOREIGN KEY ("session_id") REFERENCES "agent_session" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_step" ADD CONSTRAINT "fk_agent_step_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "audit_event" ADD CONSTRAINT "fk_audit_event_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_tool_call" ADD CONSTRAINT "fk_agent_tool_call_0" FOREIGN KEY ("audit_id") REFERENCES "audit_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_tool_call" ADD CONSTRAINT "fk_agent_tool_call_1" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_artifact" ADD CONSTRAINT "fk_agent_artifact_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "integration_connector" ADD CONSTRAINT "fk_integration_connector_0" FOREIGN KEY ("dingtalk_enterprise_id") REFERENCES "dingtalk_enterprise" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_attempt" ADD CONSTRAINT "fk_delivery_attempt_0" FOREIGN KEY ("delivery_outbox_id") REFERENCES "delivery_outbox" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_attempt" ADD CONSTRAINT "fk_delivery_attempt_1" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_chunk" ADD CONSTRAINT "fk_delivery_chunk_0" FOREIGN KEY ("delivery_outbox_id") REFERENCES "delivery_outbox" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_chunk" ADD CONSTRAINT "fk_delivery_chunk_1" FOREIGN KEY ("attempt_id") REFERENCES "delivery_attempt" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_base" ADD CONSTRAINT "fk_platform_base_0" FOREIGN KEY ("environment_id") REFERENCES "platform_environment" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_workshop" ADD CONSTRAINT "fk_platform_workshop_0" FOREIGN KEY ("base_id") REFERENCES "platform_base" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_workflow_node" ADD CONSTRAINT "fk_agent_workflow_node_0" FOREIGN KEY ("template_id") REFERENCES "agent_workflow_template" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_workflow_edge" ADD CONSTRAINT "fk_agent_workflow_edge_0" FOREIGN KEY ("template_id") REFERENCES "agent_workflow_template" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_workflow_publication" ADD CONSTRAINT "fk_agent_workflow_publication_0" FOREIGN KEY ("template_id") REFERENCES "agent_workflow_template" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_secret_version" ADD CONSTRAINT "fk_platform_secret_version_0" FOREIGN KEY ("secret_id") REFERENCES "platform_secret" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_runtime_config_value" ADD CONSTRAINT "fk_platform_runtime_config_value_0" FOREIGN KEY ("definition_id") REFERENCES "platform_runtime_config_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "message_attachment" ADD CONSTRAINT "fk_message_attachment_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "message_attachment" ADD CONSTRAINT "fk_message_attachment_1" FOREIGN KEY ("message_id") REFERENCES "agent_message" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "attachment_content" ADD CONSTRAINT "fk_attachment_content_0" FOREIGN KEY ("attachment_id") REFERENCES "message_attachment" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "user_password_credential" ADD CONSTRAINT "fk_user_password_credential_0" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "user_external_identity" ADD CONSTRAINT "fk_user_external_identity_0" FOREIGN KEY ("dingtalk_enterprise_id") REFERENCES "dingtalk_enterprise" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "user_external_identity" ADD CONSTRAINT "fk_user_external_identity_1" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "user_session" ADD CONSTRAINT "fk_user_session_0" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_user_role" ADD CONSTRAINT "fk_rbac_user_role_0" FOREIGN KEY ("role_id") REFERENCES "rbac_role" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_user_role" ADD CONSTRAINT "fk_rbac_user_role_1" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "identity_migration_audit" ADD CONSTRAINT "fk_identity_migration_audit_0" FOREIGN KEY ("internal_user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_revision" ADD CONSTRAINT "fk_agent_revision_0" FOREIGN KEY ("agent_id") REFERENCES "agent_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_publication" ADD CONSTRAINT "fk_agent_publication_0" FOREIGN KEY ("revision_id") REFERENCES "agent_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_publication" ADD CONSTRAINT "fk_agent_publication_1" FOREIGN KEY ("agent_id") REFERENCES "agent_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_skill_binding" ADD CONSTRAINT "fk_agent_skill_binding_0" FOREIGN KEY ("publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_channel_binding" ADD CONSTRAINT "fk_agent_channel_binding_0" FOREIGN KEY ("publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_definition" ADD CONSTRAINT "fk_webhook_trigger_definition_0" FOREIGN KEY ("service_account_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_definition" ADD CONSTRAINT "fk_webhook_trigger_definition_1" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_revision" ADD CONSTRAINT "fk_webhook_trigger_revision_0" FOREIGN KEY ("trigger_id") REFERENCES "webhook_trigger_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_publication" ADD CONSTRAINT "fk_webhook_trigger_publication_0" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_publication" ADD CONSTRAINT "fk_webhook_trigger_publication_1" FOREIGN KEY ("revision_id") REFERENCES "webhook_trigger_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_trigger_publication" ADD CONSTRAINT "fk_webhook_trigger_publication_2" FOREIGN KEY ("trigger_id") REFERENCES "webhook_trigger_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_event" ADD CONSTRAINT "fk_webhook_event_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_event" ADD CONSTRAINT "fk_webhook_event_1" FOREIGN KEY ("service_account_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_event" ADD CONSTRAINT "fk_webhook_event_2" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_event" ADD CONSTRAINT "fk_webhook_event_3" FOREIGN KEY ("trigger_publication_id") REFERENCES "webhook_trigger_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_event" ADD CONSTRAINT "fk_webhook_event_4" FOREIGN KEY ("trigger_id") REFERENCES "webhook_trigger_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_replay_nonce" ADD CONSTRAINT "fk_webhook_replay_nonce_0" FOREIGN KEY ("trigger_id") REFERENCES "webhook_trigger_definition" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "webhook_outbox" ADD CONSTRAINT "fk_webhook_outbox_0" FOREIGN KEY ("webhook_event_id") REFERENCES "webhook_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application" ADD CONSTRAINT "fk_business_application_0" FOREIGN KEY ("owner_user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision" ADD CONSTRAINT "fk_business_application_revision_0" FOREIGN KEY ("workflow_publication_id") REFERENCES "agent_workflow_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision" ADD CONSTRAINT "fk_business_application_revision_1" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision" ADD CONSTRAINT "fk_business_application_revision_2" FOREIGN KEY ("application_id") REFERENCES "business_application" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_trigger" ADD CONSTRAINT "fk_business_application_revision_trigger_0" FOREIGN KEY ("service_account_user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_trigger" ADD CONSTRAINT "fk_business_application_revision_trigger_1" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_trigger" ADD CONSTRAINT "fk_business_application_revision_trigger_2" FOREIGN KEY ("revision_id") REFERENCES "business_application_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_delivery" ADD CONSTRAINT "fk_business_application_revision_delivery_0" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_delivery" ADD CONSTRAINT "fk_business_application_revision_delivery_1" FOREIGN KEY ("revision_id") REFERENCES "business_application_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_publication" ADD CONSTRAINT "fk_business_application_publication_0" FOREIGN KEY ("revision_id") REFERENCES "business_application_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_publication" ADD CONSTRAINT "fk_business_application_publication_1" FOREIGN KEY ("application_id") REFERENCES "business_application" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_deployment" ADD CONSTRAINT "fk_business_application_deployment_0" FOREIGN KEY ("publication_id") REFERENCES "business_application_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_deployment" ADD CONSTRAINT "fk_business_application_deployment_1" FOREIGN KEY ("application_id") REFERENCES "business_application" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_active_route" ADD CONSTRAINT "fk_business_application_active_route_0" FOREIGN KEY ("publication_id") REFERENCES "business_application_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_active_route" ADD CONSTRAINT "fk_business_application_active_route_1" FOREIGN KEY ("application_id") REFERENCES "business_application" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_active_route" ADD CONSTRAINT "fk_business_application_active_route_2" FOREIGN KEY ("deployment_id") REFERENCES "business_application_deployment" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "model_connection_revision" ADD CONSTRAINT "fk_model_connection_revision_0" FOREIGN KEY ("api_key_secret_id") REFERENCES "platform_secret" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "model_connection_revision" ADD CONSTRAINT "fk_model_connection_revision_1" FOREIGN KEY ("connection_id") REFERENCES "model_connection" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "channel_connector_runtime" ADD CONSTRAINT "fk_channel_connector_runtime_0" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "channel_ingress_event" ADD CONSTRAINT "fk_channel_ingress_event_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "channel_ingress_event" ADD CONSTRAINT "fk_channel_ingress_event_1" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "channel_ingress_outbox" ADD CONSTRAINT "fk_channel_ingress_outbox_0" FOREIGN KEY ("channel_event_id") REFERENCES "channel_ingress_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_candidate" ADD CONSTRAINT "fk_dingtalk_identity_candidate_0" FOREIGN KEY ("dingtalk_enterprise_id") REFERENCES "dingtalk_enterprise" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_candidate_message" ADD CONSTRAINT "fk_dingtalk_identity_candidate_message_0" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_candidate_message" ADD CONSTRAINT "fk_dingtalk_identity_candidate_message_1" FOREIGN KEY ("source_ingress_event_id") REFERENCES "channel_ingress_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_candidate_message" ADD CONSTRAINT "fk_dingtalk_identity_candidate_message_2" FOREIGN KEY ("candidate_id") REFERENCES "dingtalk_identity_candidate" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;

-- postgres-only
ALTER TABLE "rbac_role_admin_capability" ADD CONSTRAINT "fk_rbac_role_admin_capability_0" FOREIGN KEY ("role_id") REFERENCES "rbac_role" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_access" ADD CONSTRAINT "fk_rbac_role_application_access_0" FOREIGN KEY ("application_id") REFERENCES "business_application" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_access" ADD CONSTRAINT "fk_rbac_role_application_access_1" FOREIGN KEY ("role_id") REFERENCES "rbac_role" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_scope" ADD CONSTRAINT "fk_rbac_role_application_scope_0" FOREIGN KEY ("workshop_id") REFERENCES "platform_workshop" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_scope" ADD CONSTRAINT "fk_rbac_role_application_scope_1" FOREIGN KEY ("base_id") REFERENCES "platform_base" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_scope" ADD CONSTRAINT "fk_rbac_role_application_scope_2" FOREIGN KEY ("environment_id") REFERENCES "platform_environment" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_scope" ADD CONSTRAINT "fk_rbac_role_application_scope_3" FOREIGN KEY ("application_access_id") REFERENCES "rbac_role_application_access" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "job_dispatch_outbox" ADD CONSTRAINT "fk_job_dispatch_outbox_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_outbox" ADD CONSTRAINT "fk_delivery_outbox_0" FOREIGN KEY ("result_artifact_id") REFERENCES "agent_artifact" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "delivery_outbox" ADD CONSTRAINT "fk_delivery_outbox_1" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_secret_change_event" ADD CONSTRAINT "fk_platform_secret_change_event_0" FOREIGN KEY ("secret_id") REFERENCES "platform_secret" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource_draft" ADD CONSTRAINT "fk_platform_resource_draft_0" FOREIGN KEY ("resource_id") REFERENCES "platform_resource" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource_verification" ADD CONSTRAINT "fk_platform_resource_verification_0" FOREIGN KEY ("draft_id") REFERENCES "platform_resource_draft" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;

-- postgres-only
ALTER TABLE "platform_resource_verification" ADD CONSTRAINT "fk_platform_resource_verification_1" FOREIGN KEY ("resource_id") REFERENCES "platform_resource" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource_revision" ADD CONSTRAINT "fk_platform_resource_revision_0" FOREIGN KEY ("verification_id") REFERENCES "platform_resource_verification" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource_revision" ADD CONSTRAINT "fk_platform_resource_revision_1" FOREIGN KEY ("resource_id") REFERENCES "platform_resource" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_enterprise" ADD CONSTRAINT "fk_dingtalk_enterprise_0" FOREIGN KEY ("created_by") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_application_observation" ADD CONSTRAINT "fk_dingtalk_identity_application_observation_0" FOREIGN KEY ("last_ingress_event_id") REFERENCES "channel_ingress_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_application_observation" ADD CONSTRAINT "fk_dingtalk_identity_application_observation_1" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_application_observation" ADD CONSTRAINT "fk_dingtalk_identity_application_observation_2" FOREIGN KEY ("external_identity_id") REFERENCES "user_external_identity" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_nickname_audit" ADD CONSTRAINT "fk_dingtalk_identity_nickname_audit_0" FOREIGN KEY ("source_ingress_event_id") REFERENCES "channel_ingress_event" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_nickname_audit" ADD CONSTRAINT "fk_dingtalk_identity_nickname_audit_1" FOREIGN KEY ("connector_id") REFERENCES "integration_connector" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "dingtalk_identity_nickname_audit" ADD CONSTRAINT "fk_dingtalk_identity_nickname_audit_2" FOREIGN KEY ("external_identity_id") REFERENCES "user_external_identity" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource" ADD CONSTRAINT "fk_platform_resource_0" FOREIGN KEY ("workshop_id") REFERENCES "platform_workshop" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource" ADD CONSTRAINT "fk_platform_resource_1" FOREIGN KEY ("base_id") REFERENCES "platform_base" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "platform_resource" ADD CONSTRAINT "fk_platform_resource_2" FOREIGN KEY ("environment_id") REFERENCES "platform_environment" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "loki_resource_draft_test_session" ADD CONSTRAINT "fk_loki_resource_draft_test_session_0" FOREIGN KEY ("draft_id") REFERENCES "platform_resource_draft" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;

-- postgres-only
ALTER TABLE "loki_resource_draft_test_session" ADD CONSTRAINT "fk_loki_resource_draft_test_session_1" FOREIGN KEY ("resource_id") REFERENCES "platform_resource" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "resource_reset_target" ADD CONSTRAINT "fk_resource_reset_target_0" FOREIGN KEY ("operation_id") REFERENCES "resource_reset_operation" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_runtime_event" ADD CONSTRAINT "fk_agent_runtime_event_0" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_publication_mcp_tool" ADD CONSTRAINT "fk_agent_publication_mcp_tool_0" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_mcp_tool" ADD CONSTRAINT "fk_business_application_revision_mcp_tool_0" FOREIGN KEY ("agent_publication_id", "tool_identifier") REFERENCES "agent_publication_mcp_tool" ("agent_publication_id", "tool_identifier") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_mcp_tool" ADD CONSTRAINT "fk_business_application_revision_mcp_tool_1" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_revision_mcp_tool" ADD CONSTRAINT "fk_business_application_revision_mcp_tool_2" FOREIGN KEY ("application_revision_id") REFERENCES "business_application_revision" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_publication_mcp_tool" ADD CONSTRAINT "fk_business_application_publication_mcp_tool_0" FOREIGN KEY ("agent_publication_id", "tool_identifier") REFERENCES "agent_publication_mcp_tool" ("agent_publication_id", "tool_identifier") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_publication_mcp_tool" ADD CONSTRAINT "fk_business_application_publication_mcp_tool_1" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "business_application_publication_mcp_tool" ADD CONSTRAINT "fk_business_application_publication_mcp_tool_2" FOREIGN KEY ("application_publication_id") REFERENCES "business_application_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job_mcp_tool_snapshot" ADD CONSTRAINT "fk_agent_job_mcp_tool_snapshot_0" FOREIGN KEY ("agent_publication_id") REFERENCES "agent_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job_mcp_tool_snapshot" ADD CONSTRAINT "fk_agent_job_mcp_tool_snapshot_1" FOREIGN KEY ("application_publication_id") REFERENCES "business_application_publication" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "agent_job_mcp_tool_snapshot" ADD CONSTRAINT "fk_agent_job_mcp_tool_snapshot_2" FOREIGN KEY ("job_id") REFERENCES "agent_job" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "rbac_role_application_mcp_tool" ADD CONSTRAINT "fk_rbac_role_application_mcp_tool_0" FOREIGN KEY ("application_access_id") REFERENCES "rbac_role_application_access" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

-- postgres-only
ALTER TABLE "ones_identity_verification_challenge" ADD CONSTRAINT "fk_ones_identity_verification_challenge_0" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;

CREATE INDEX idx_agent_job_status ON agent_job(status);

CREATE INDEX idx_agent_job_session ON agent_job(session_id);

CREATE INDEX idx_delivery_attempt_job ON delivery_attempt(job_id);

CREATE INDEX idx_delivery_attempt_status ON delivery_attempt(status);

CREATE INDEX idx_delivery_chunk_attempt ON delivery_chunk(attempt_id);

CREATE INDEX idx_platform_environment_status ON platform_environment(status);

CREATE INDEX idx_platform_base_environment ON platform_base(environment_id);

CREATE INDEX idx_platform_base_status ON platform_base(status);

CREATE INDEX idx_platform_workshop_base ON platform_workshop(base_id);

CREATE INDEX idx_platform_workshop_status ON platform_workshop(status);

CREATE INDEX idx_platform_secret_reference_status ON platform_secret_reference(status);

CREATE INDEX idx_platform_config_audit_entity ON platform_config_audit(entity_type, entity_id);

CREATE INDEX idx_platform_config_audit_created ON platform_config_audit(created_at);

CREATE INDEX idx_agent_workflow_template_project ON agent_workflow_template(project_code);

CREATE INDEX idx_agent_workflow_template_status ON agent_workflow_template(status);

CREATE INDEX idx_agent_workflow_node_template ON agent_workflow_node(template_id);

CREATE INDEX idx_agent_workflow_node_type ON agent_workflow_node(node_type);

CREATE INDEX idx_agent_workflow_edge_template ON agent_workflow_edge(template_id);

CREATE INDEX idx_agent_workflow_edge_source ON agent_workflow_edge(template_id, source_node_key);

CREATE INDEX idx_agent_workflow_edge_target ON agent_workflow_edge(template_id, target_node_key);

CREATE INDEX idx_agent_workflow_publication_template ON agent_workflow_publication(template_id);

CREATE INDEX idx_platform_secret_status ON platform_secret(status);

CREATE INDEX idx_platform_secret_ref ON platform_secret(ref);

CREATE INDEX idx_platform_secret_version_secret ON platform_secret_version(secret_id);

CREATE INDEX idx_platform_secret_version_status ON platform_secret_version(status);

CREATE INDEX idx_platform_runtime_config_definition_status
  ON platform_runtime_config_definition(status);

CREATE INDEX idx_platform_runtime_config_definition_bootstrap
  ON platform_runtime_config_definition(bootstrap_only);

CREATE INDEX idx_platform_runtime_config_value_key
  ON platform_runtime_config_value(key);

CREATE INDEX idx_platform_runtime_config_value_scope
  ON platform_runtime_config_value(scope_type, scope_code, service_name);

CREATE INDEX idx_platform_runtime_config_value_status
  ON platform_runtime_config_value(status);

CREATE UNIQUE INDEX idx_agent_session_key ON agent_session(session_key);

CREATE UNIQUE INDEX idx_agent_message_external
  ON agent_message(session_id, external_message_id)
  WHERE external_message_id <> '';

CREATE UNIQUE INDEX idx_agent_message_sequence
  ON agent_message(session_id, sequence_no)
  WHERE sequence_no > 0;

CREATE INDEX idx_message_attachment_job ON message_attachment(job_id);

CREATE INDEX idx_message_attachment_status ON message_attachment(status);

CREATE INDEX idx_app_user_status ON app_user(status);

CREATE INDEX idx_external_identity_user
  ON user_external_identity(user_id);

CREATE INDEX idx_external_identity_status
  ON user_external_identity(status);

CREATE INDEX idx_user_session_user ON user_session(user_id);

CREATE INDEX idx_user_session_status ON user_session(status);

CREATE INDEX idx_user_session_expiry
  ON user_session(idle_expires_at, absolute_expires_at);

CREATE INDEX idx_rbac_role_status ON rbac_role(status);

CREATE INDEX idx_rbac_user_role_user ON rbac_user_role(user_id);

CREATE INDEX idx_rbac_user_role_role ON rbac_user_role(role_id);

CREATE INDEX idx_identity_migration_status
  ON identity_migration_audit(status);

CREATE INDEX idx_agent_definition_status
  ON agent_definition(status);

CREATE INDEX idx_agent_definition_project
  ON agent_definition(project_code);

CREATE INDEX idx_agent_revision_agent
  ON agent_revision(agent_id, revision);

CREATE INDEX idx_agent_revision_status
  ON agent_revision(status);

CREATE INDEX idx_agent_publication_agent
  ON agent_publication(agent_id, revision);

CREATE INDEX idx_agent_publication_status
  ON agent_publication(status);

CREATE INDEX idx_agent_job_internal_user
  ON agent_job(internal_user_id);

CREATE INDEX idx_agent_job_publication
  ON agent_job(agent_publication_id);

CREATE INDEX idx_app_user_account_type_status
  ON app_user(account_type, status);

CREATE INDEX idx_webhook_trigger_status_type
  ON webhook_trigger_definition(status, trigger_type);

CREATE INDEX idx_webhook_trigger_service_account
  ON webhook_trigger_definition(service_account_id);

CREATE INDEX idx_webhook_trigger_revision_status
  ON webhook_trigger_revision(trigger_id, status, revision);

CREATE INDEX idx_webhook_trigger_publication_status
  ON webhook_trigger_publication(trigger_id, status, revision);

CREATE INDEX idx_webhook_trigger_publication_agent
  ON webhook_trigger_publication(agent_publication_id);

CREATE INDEX idx_webhook_event_trigger_received
  ON webhook_event(trigger_id, received_at);

CREATE INDEX idx_webhook_event_status_received
  ON webhook_event(status, received_at);

CREATE INDEX idx_webhook_event_job
  ON webhook_event(job_id);

CREATE INDEX idx_webhook_event_correlation
  ON webhook_event(correlation_id);

CREATE INDEX idx_webhook_replay_nonce_expires
  ON webhook_replay_nonce(expires_at);

CREATE INDEX idx_webhook_outbox_pending
  ON webhook_outbox(status, next_attempt_at);

CREATE INDEX idx_agent_job_webhook_event
  ON agent_job(webhook_event_id);

CREATE INDEX idx_agent_job_webhook_trigger
  ON agent_job(webhook_trigger_id, webhook_trigger_publication_id);

CREATE INDEX idx_agent_job_created_status
  ON agent_job(created_at, status);

CREATE INDEX idx_agent_job_project_created
  ON agent_job(project_code, created_at);

CREATE INDEX idx_agent_job_session_created
  ON agent_job(session_id, created_at);

CREATE INDEX idx_agent_job_source_created
  ON agent_job(source_channel, created_at);

CREATE INDEX idx_agent_session_updated
  ON agent_session(updated_at, id);

CREATE INDEX idx_agent_session_requester_updated
  ON agent_session(requester_id, updated_at);

CREATE INDEX idx_agent_message_session_created
  ON agent_message(session_id, created_at, id);

CREATE INDEX idx_message_attachment_created
  ON message_attachment(created_at, id);

CREATE INDEX idx_delivery_attempt_created_status
  ON delivery_attempt(created_at, status);

CREATE INDEX idx_integration_connector_type_enabled
  ON integration_connector(connector_type, enabled);

CREATE INDEX idx_agent_job_retry_due
    ON agent_job (status, next_retry_at);

CREATE INDEX idx_agent_job_legacy_retry_recovery
    ON agent_job (status, retry_count, locked_at)
    WHERE result IS NULL;

CREATE INDEX idx_business_application_project_status
  ON business_application(project_code, status);

CREATE INDEX idx_business_application_owner
  ON business_application(owner_user_id);

CREATE INDEX idx_business_application_revision_app
  ON business_application_revision(application_id, revision);

CREATE INDEX idx_business_application_revision_status
  ON business_application_revision(status);

CREATE INDEX idx_business_application_trigger_revision
  ON business_application_revision_trigger(revision_id, binding_order);

CREATE INDEX idx_business_application_trigger_route
  ON business_application_revision_trigger(
    trigger_type, connector_id, normalized_routing_key
  );

CREATE INDEX idx_business_application_delivery_revision
  ON business_application_revision_delivery(revision_id, binding_order);

CREATE INDEX idx_business_application_publication_app
  ON business_application_publication(application_id, revision);

CREATE INDEX idx_business_application_deployment_environment
  ON business_application_deployment(environment, active);

CREATE INDEX idx_business_application_active_route_deployment
  ON business_application_active_route(deployment_id);

CREATE INDEX idx_agent_session_business_application
  ON agent_session(business_application_id, updated_at);

CREATE INDEX idx_agent_job_business_application
  ON agent_job(business_application_id, created_at);

CREATE INDEX idx_agent_job_business_application_publication
  ON agent_job(business_application_publication_id, created_at);

CREATE INDEX idx_agent_job_business_application_deployment
  ON agent_job(business_application_deployment_id, created_at);

CREATE INDEX idx_model_connection_status
  ON model_connection(status);

CREATE INDEX idx_model_connection_revision_connection
  ON model_connection_revision(connection_id, revision);

CREATE INDEX idx_model_connection_revision_status
  ON model_connection_revision(status);

CREATE INDEX idx_model_connection_revision_hash
  ON model_connection_revision(config_hash);

CREATE INDEX idx_channel_connector_runtime_heartbeat
    on channel_connector_runtime(last_heartbeat_at);

CREATE INDEX idx_channel_runtime_lease_expiry
    on channel_runtime_lease(expires_at);

CREATE INDEX idx_channel_ingress_event_status_received
    on channel_ingress_event(status, received_at);

CREATE INDEX idx_channel_ingress_outbox_claim
    on channel_ingress_outbox(status, next_attempt_at, created_at);

CREATE INDEX idx_dingtalk_identity_candidate_last_seen
    on dingtalk_identity_candidate(last_seen_at desc, id desc);

CREATE INDEX idx_dingtalk_identity_candidate_display_name
    on dingtalk_identity_candidate(display_name);

CREATE INDEX idx_dingtalk_candidate_message_recent
    on dingtalk_identity_candidate_message(
        candidate_id, received_at desc, id desc
    );

CREATE INDEX idx_dingtalk_candidate_message_conversation
    on dingtalk_identity_candidate_message(
        conversation_type, conversation_id
    );

CREATE INDEX idx_dingtalk_candidate_message_robot
    on dingtalk_identity_candidate_message(robot_code);

CREATE INDEX idx_rbac_user_role_expiry
  ON rbac_user_role(status, expires_at);

CREATE INDEX idx_role_admin_capability_role
  ON rbac_role_admin_capability(role_id, status);

CREATE INDEX idx_role_admin_capability_resource
  ON rbac_role_admin_capability(capability_code, resource_type, resource_code, status);

CREATE INDEX idx_role_application_access_role
  ON rbac_role_application_access(role_id, status);

CREATE INDEX idx_role_application_access_application
  ON rbac_role_application_access(application_id, status);

CREATE INDEX idx_role_application_scope_access
  ON rbac_role_application_scope(application_access_id);

CREATE INDEX idx_role_application_scope_nodes
  ON rbac_role_application_scope(environment_id, base_id, workshop_id);

CREATE INDEX idx_agent_session_publication_scope
  ON agent_session(application_publication_id, execution_scope_hash, updated_at);

CREATE INDEX idx_job_dispatch_outbox_due
  ON job_dispatch_outbox(status, next_attempt_at, created_at);

CREATE INDEX idx_job_dispatch_outbox_claim
  ON job_dispatch_outbox(status, claimed_at)
  WHERE status = 'RUNNING';

CREATE INDEX idx_job_dispatch_outbox_job_status
  ON job_dispatch_outbox(job_id, status);

CREATE INDEX idx_job_dispatch_outbox_audit
  ON job_dispatch_outbox(correlation_id, created_at);

CREATE INDEX idx_job_dispatch_cutover_quarantine_job
  ON job_dispatch_cutover_quarantine(job_id, observed_at);

CREATE INDEX idx_delivery_outbox_claim
  ON delivery_outbox(status, next_attempt_at, created_at);

CREATE INDEX idx_delivery_outbox_job
  ON delivery_outbox(job_id, created_at);

CREATE INDEX idx_delivery_outbox_correlation
  ON delivery_outbox(correlation_id, created_at);

CREATE INDEX idx_delivery_outbox_stale_claim
  ON delivery_outbox(status, claim_expires_at);

CREATE UNIQUE INDEX uq_delivery_attempt_idempotency
  ON delivery_attempt(idempotency_key);

CREATE UNIQUE INDEX uq_delivery_attempt_outbox_number
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no)
  WHERE delivery_outbox_id IS NOT NULL;

CREATE INDEX idx_delivery_attempt_outbox
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no);

CREATE UNIQUE INDEX uq_delivery_chunk_attempt_index
  ON delivery_chunk(delivery_outbox_id, replay_no, attempt_no, chunk_index)
  WHERE delivery_outbox_id IS NOT NULL;

CREATE UNIQUE INDEX uq_delivery_chunk_logical_success
  ON delivery_chunk(delivery_outbox_id, chunk_index)
  WHERE delivery_outbox_id IS NOT NULL AND status = 'SUCCEEDED';

CREATE INDEX idx_delivery_chunk_logical
  ON delivery_chunk(delivery_outbox_id, chunk_index, status);

CREATE UNIQUE INDEX uq_platform_secret_version_active
  ON platform_secret_version(secret_id)
  WHERE status = 'active';

CREATE INDEX idx_platform_secret_change_pending
  ON platform_secret_change_event(status, created_at);

CREATE INDEX idx_platform_resource_draft_status
  ON platform_resource_draft(status, updated_at);

CREATE INDEX idx_platform_resource_verification_resource
  ON platform_resource_verification(resource_id, verified_at);

CREATE INDEX idx_platform_resource_revision_status
  ON platform_resource_revision(resource_id, status, revision);

CREATE INDEX idx_resource_reset_status
  ON resource_reset_operation(status, created_at);

CREATE INDEX idx_resource_reset_correlation
  ON resource_reset_operation(correlation_id);

CREATE UNIQUE INDEX idx_dingtalk_enterprise_corp_id
  ON dingtalk_enterprise(corp_id)
  WHERE corp_id IS NOT NULL;

CREATE INDEX idx_dingtalk_enterprise_status_name
  ON dingtalk_enterprise(status, name, id);

CREATE INDEX idx_integration_connector_dingtalk_enterprise
  ON integration_connector(dingtalk_enterprise_id, enabled, deleted);

CREATE UNIQUE INDEX idx_dingtalk_identity_enterprise_subject
  ON user_external_identity(dingtalk_enterprise_id, external_subject_id)
  WHERE provider = 'dingtalk' AND dingtalk_enterprise_id IS NOT NULL;

CREATE UNIQUE INDEX idx_dingtalk_identity_user_enterprise_current
  ON user_external_identity(user_id, dingtalk_enterprise_id)
  WHERE provider = 'dingtalk'
    AND dingtalk_enterprise_id IS NOT NULL
    AND status IN ('enabled', 'disabled');

CREATE INDEX idx_dingtalk_identity_application_observation_recent
  ON dingtalk_identity_application_observation(
    external_identity_id, last_observed_at DESC, connector_id
  );

CREATE INDEX idx_dingtalk_identity_nickname_audit_history
  ON dingtalk_identity_nickname_audit(
    external_identity_id, observed_at DESC, source_ingress_event_id DESC
  );

CREATE UNIQUE INDEX idx_dingtalk_candidate_enterprise_subject
  ON dingtalk_identity_candidate(dingtalk_enterprise_id, external_subject_id)
  WHERE dingtalk_enterprise_id IS NOT NULL;

CREATE INDEX idx_dingtalk_candidate_enterprise_recent
  ON dingtalk_identity_candidate(
    dingtalk_enterprise_id, last_seen_at DESC, id DESC
  );

CREATE UNIQUE INDEX idx_platform_base_identity_environment
  ON platform_base(id, environment_id);

CREATE UNIQUE INDEX idx_platform_workshop_identity_base
  ON platform_workshop(id, base_id);

CREATE INDEX idx_platform_resource_scope
  ON platform_resource(scope_type, environment_id, base_id, workshop_id);

CREATE INDEX idx_platform_resource_kind_status
  ON platform_resource(resource_kind, status);

CREATE INDEX idx_loki_draft_test_session_lookup
  ON loki_resource_draft_test_session(
    resource_id,
    actor_id,
    status,
    expires_at
  );

CREATE INDEX idx_resource_reset_target_status
  ON resource_reset_target(operation_id, apply_status, target_type);

CREATE INDEX idx_agent_runtime_event_job
  ON agent_runtime_event(job_id, invocation_id, sequence);

CREATE INDEX idx_agent_runtime_event_digest
  ON agent_runtime_event(request_digest);

CREATE INDEX idx_agent_runtime_terminal_ledger_expires
  ON agent_runtime_terminal_ledger(expires_at);

CREATE INDEX idx_agent_definition_runtime_kind
  ON agent_definition(runtime_kind, status);

CREATE INDEX idx_agent_publication_runtime_kind
  ON agent_publication(runtime_kind, status);

CREATE INDEX idx_agent_runtime_invocation_claim_expires
  ON agent_runtime_invocation_claim(expires_at);

CREATE INDEX idx_agent_runtime_invocation_event_expires
  ON agent_runtime_invocation_event(expires_at);

CREATE INDEX idx_platform_resource_direct_resolution
  ON platform_resource(
    resource_kind,
    status,
    environment_id,
    base_id,
    workshop_id,
    placement
  );

CREATE INDEX idx_agent_publication_mcp_tool_identifier
  ON agent_publication_mcp_tool(tool_identifier, agent_publication_id);

CREATE INDEX idx_application_publication_mcp_tool_identifier
  ON business_application_publication_mcp_tool(
    tool_identifier,
    application_publication_id
  );

CREATE INDEX idx_job_mcp_tool_snapshot_publication
  ON agent_job_mcp_tool_snapshot(application_publication_id, created_at);

CREATE INDEX idx_role_application_mcp_tool_identifier
  ON rbac_role_application_mcp_tool(tool_identifier, application_access_id);

CREATE UNIQUE INDEX idx_ones_identity_challenge_pending
  ON ones_identity_verification_challenge(user_id)
  WHERE status = 'PENDING';

CREATE INDEX idx_ones_identity_challenge_expiry
  ON ones_identity_verification_challenge(status, expires_at);

-- postgres-only
-- postgres-only
-- 为最终保留的 PostgreSQL public 项目表及字段建立完整中文注释清单。
-- Database.execute_script 在 SQLite 下会跳过 COMMENT ON，保证测试数据库兼容。
-- schema_migration 是迁移器内部账本，不属于项目领域 schema 注释契约。

COMMENT ON TABLE "agent_artifact" IS 'Agent 产物表，记录诊断过程中生成的报告、证据摘要或文件引用';
COMMENT ON TABLE "agent_channel_binding" IS 'Agent 发布与渠道 Connector 的显式绑定关系';
COMMENT ON TABLE "agent_definition" IS '支持多Agent的稳定定义';
COMMENT ON TABLE "agent_job" IS 'Agent 任务表，记录一次异步只读诊断执行请求及其状态、结果和 Channel 元数据';
COMMENT ON TABLE "agent_job_mcp_tool_snapshot" IS 'Job 创建时冻结的 MCP 工具标识、Schema 与授权摘要';
COMMENT ON TABLE "agent_message" IS 'Agent 消息表，记录会话内用户、系统和 Agent 的消息历史';
COMMENT ON TABLE "agent_publication" IS 'Agent不可变发布快照';
COMMENT ON TABLE "agent_publication_mcp_tool" IS 'Agent 发布快照包含的精确 MCP 工具清单';
COMMENT ON TABLE "agent_revision" IS 'Agent可编辑草稿revision';
COMMENT ON TABLE "agent_runtime_event" IS 'Python Worker按sequence持久化的TypeScript Runtime安全归一化事件，不保存原始SDK消息、Token或私有推理';
COMMENT ON TABLE "agent_runtime_invocation_claim" IS 'Agent Runtime模型调用前的有界执行占用；Runtime重启后遗留占用失败关闭，禁止自动重放模型';
COMMENT ON TABLE "agent_runtime_invocation_event" IS 'Agent Runtime追加式脱敏事件前缀；重启后只用于续接orphan终态，不恢复或重放模型SDK流';
COMMENT ON TABLE "agent_runtime_terminal_ledger" IS 'TypeScript Runtime有界终态恢复账本；只保存规范事件并按TTL清理，不保存原始SDK消息或Secret';
COMMENT ON TABLE "agent_session" IS 'Agent 会话表，记录一次外部 Channel 对话或请求上下文以及后续 Agent job 的会话归属';
COMMENT ON TABLE "agent_skill_binding" IS 'Agent 修订绑定的 Skill 代码、顺序与启用状态';
COMMENT ON TABLE "agent_step" IS 'Agent 执行步骤表，记录诊断过程中的阶段性说明和推理摘要';
COMMENT ON TABLE "agent_tool_call" IS 'Agent 工具调用表，记录只读内部工具调用请求、响应摘要、风险级别和审计关联';
COMMENT ON TABLE "agent_workflow_edge" IS 'Agent 流程边表，保存节点连线、端口和条件';
COMMENT ON TABLE "agent_workflow_node" IS 'Agent 流程节点表，保存拖拽节点、位置和节点配置';
COMMENT ON TABLE "agent_workflow_publication" IS 'Agent 流程发布快照表，保存不可变的已发布 graph snapshot';
COMMENT ON TABLE "agent_workflow_template" IS 'Agent 诊断流程模板表，保存 Web 拖拽编排草稿配置';
COMMENT ON TABLE "app_user" IS '统一内部用户，Web和Channel身份均解析到该主体';
COMMENT ON TABLE "attachment_content" IS '附件受限解析产生的有界纯文本和分段索引';
COMMENT ON TABLE "audit_event" IS '审计事件表，记录 Agent、工具平台和投递链路中的关键可审计动作';
COMMENT ON TABLE "business_application" IS '业务应用稳定定义，不直接参与现有数据面路由';
COMMENT ON TABLE "business_application_active_route" IS '活动Trigger确定性路由唯一投影';
COMMENT ON TABLE "business_application_deployment" IS '环境级显式激活指针';
COMMENT ON TABLE "business_application_publication" IS '不可变业务应用发布快照';
COMMENT ON TABLE "business_application_publication_mcp_tool" IS '业务应用发布快照选择的 MCP 工具子集';
COMMENT ON TABLE "business_application_revision" IS '业务应用追加式草稿修订';
COMMENT ON TABLE "business_application_revision_delivery" IS '业务应用修订中的结果投递绑定配置';
COMMENT ON TABLE "business_application_revision_mcp_tool" IS '业务应用修订选择的 MCP 工具子集';
COMMENT ON TABLE "business_application_revision_trigger" IS '业务应用修订中的入口触发器绑定配置';
COMMENT ON TABLE "channel_connector_runtime" IS '渠道 Connector 的连接状态、租约与安全错误摘要';
COMMENT ON TABLE "channel_ingress_event" IS '渠道接收后持久化的标准化入口事件，不保存认证密钥';
COMMENT ON TABLE "channel_ingress_outbox" IS '渠道入口事件到异步消息队列之间的事务 Outbox';
COMMENT ON TABLE "channel_runtime_lease" IS '渠道 Runtime 实例的互斥租约与心跳状态';
COMMENT ON TABLE "delivery_attempt" IS '结果投递尝试表，记录 Agent job 最终报告或失败通知的一次投递过程';
COMMENT ON TABLE "delivery_chunk" IS '结果投递分片表，记录长报告按目标平台限制拆分后的每个发送分片';
COMMENT ON TABLE "delivery_outbox" IS '持久化 Agent 结果或安全失败通知的独立投递意图；状态不回写 Agent Job 成败';
COMMENT ON TABLE "dingtalk_enterprise" IS '钉钉企业 Corp ID 命名空间，独立治理企业身份归属';
COMMENT ON TABLE "dingtalk_identity_application_observation" IS '企业范围内钉钉身份与应用之间的观测事实';
COMMENT ON TABLE "dingtalk_identity_candidate" IS '尚未绑定内部用户的钉钉身份候选及受限元数据';
COMMENT ON TABLE "dingtalk_identity_candidate_message" IS '钉钉身份候选与已接收入口事件的关联记录';
COMMENT ON TABLE "dingtalk_identity_nickname_audit" IS '钉钉身份昵称变化的最小审计事实，不保存消息正文或认证材料';
COMMENT ON TABLE "identity_migration_audit" IS '统一身份迁移过程的追加式审计记录';
COMMENT ON TABLE "integration_connector" IS '渠道入口与结果投递使用的稳定 Connector 配置，不承载工具执行连接';
COMMENT ON TABLE "job_dispatch_cutover_quarantine" IS '旧Agent消息切换时无法安全转换的摘要清单，不保存原始RabbitMQ payload';
COMMENT ON TABLE "job_dispatch_outbox" IS 'Agent Job提交后到RabbitMQ发布之间的事务Outbox，不保存可变执行payload';
COMMENT ON TABLE "loki_resource_draft_test_session" IS 'Loki 工具资源草稿验证使用的短时测试会话';
COMMENT ON TABLE "message_attachment" IS '钉钉多模态消息附件元数据和安全处理状态；原始二进制保存在私有对象存储';
COMMENT ON TABLE "model_connection" IS 'Agent模型连接稳定身份；MVP仅支持Anthropic兼容协议';
COMMENT ON TABLE "model_connection_revision" IS '模型连接追加式版本；非敏感配置可发布，凭据仅引用加密Secret';
COMMENT ON TABLE "ones_identity_verification_challenge" IS 'ONES 本人验证产生的短时单次 Challenge，只保存已验证主体和 Team 候选';
COMMENT ON TABLE "platform_base" IS '业务环境下的基地目录，供数据范围授权和目标代码校验使用';
COMMENT ON TABLE "platform_config_audit" IS '平台配置审计表，记录配置新增、修改、启停、导入和发布动作';
COMMENT ON TABLE "platform_environment" IS '业务数据范围的环境目录，供角色授权与工具调用目标校验使用';
COMMENT ON TABLE "platform_resource" IS 'DB、Redis、Loki 的稳定 Resource Identity；连接内容只存在于 Draft/Revision';
COMMENT ON TABLE "platform_resource_draft" IS '每个 Resource Identity 最多一个可编辑 Draft；内容变化必须重置为 DRAFT';
COMMENT ON TABLE "platform_resource_revision" IS '发布后不可变的 Resource Revision；普通路径只能更新治理状态';
COMMENT ON TABLE "platform_resource_verification" IS '字段、Secret、连接和只读权限的技术验证记录，只保存安全摘要';
COMMENT ON TABLE "platform_runtime_config_definition" IS '运行时配置定义表，声明 key、类型、默认值、敏感性和适用服务';
COMMENT ON TABLE "platform_runtime_config_value" IS '运行时配置值表，保存 typed key 在不同作用域下的非敏感值或 secret_ref';
COMMENT ON TABLE "platform_secret" IS 'Web 管理密钥元数据表，只保存引用、状态、当前版本和脱敏摘要';
COMMENT ON TABLE "platform_secret_change_event" IS 'Secret active version 或状态变化通知；消费者重载相关资源，失败时保留 Last Known Good';
COMMENT ON TABLE "platform_secret_reference" IS '平台密钥引用表，只保存 env/vault/kms 等引用，不保存真实密钥值';
COMMENT ON TABLE "platform_secret_version" IS 'Web 管理密钥密文版本表，保存 AES-GCM 密文和 nonce';
COMMENT ON TABLE "platform_workshop" IS '业务基地下的车间目录，供数据范围授权和目标代码校验使用';
COMMENT ON TABLE "rbac_role" IS '统一RBAC角色';
COMMENT ON TABLE "rbac_role_admin_capability" IS '角色管理后台能力绑定，能力定义来自后端只读目录';
COMMENT ON TABLE "rbac_role_application_access" IS '角色对具体业务应用的使用授权聚合';
COMMENT ON TABLE "rbac_role_application_mcp_tool" IS '角色在指定业务应用内获准使用的稳定 MCP 工具标识';
COMMENT ON TABLE "rbac_role_application_scope" IS '业务应用授权下的明确环境、基地、车间范围，不支持未来资源通配';
COMMENT ON TABLE "rbac_user_role" IS '内部用户与 RBAC 角色的成员关系及授权来源';
COMMENT ON TABLE "resource_reset_operation" IS 'DB、Redis 与 Loki 工具资源四阶段受控重置操作及维护门禁';
COMMENT ON TABLE "resource_reset_target" IS '资源重置操作冻结的精确目标清单，不允许包含受保护数据类别';
COMMENT ON TABLE "user_external_identity" IS '外部身份绑定，钉钉按provider+tenant+subject唯一';
COMMENT ON TABLE "user_password_credential" IS 'Web 用户密码哈希凭据及密码变更时间，不保存明文密码';
COMMENT ON TABLE "user_session" IS 'Web服务端session，仅保存token和CSRF哈希';
COMMENT ON TABLE "webhook_event" IS 'Webhook持久化Inbox，只保存hash、声明式提取结果和脱敏有界摘要';
COMMENT ON TABLE "webhook_outbox" IS 'Webhook Inbox到RabbitMQ dispatcher的事务Outbox';
COMMENT ON TABLE "webhook_replay_nonce" IS 'HMAC防重放nonce哈希和到期时间，不保存原始nonce';
COMMENT ON TABLE "webhook_trigger_definition" IS '受管Webhook Trigger稳定定义，保存公开入口、connector、服务账号和当前发布指针';
COMMENT ON TABLE "webhook_trigger_publication" IS 'Webhook Trigger不可变发布快照并固定具体Agent publication';
COMMENT ON TABLE "webhook_trigger_revision" IS 'Webhook Trigger可编辑草稿和校验结果';

COMMENT ON COLUMN "agent_artifact"."id" IS '产物 ID';
COMMENT ON COLUMN "agent_artifact"."job_id" IS '关联的 Agent job ID';
COMMENT ON COLUMN "agent_artifact"."artifact_type" IS '产物类型，例如 report、evidence、attachment';
COMMENT ON COLUMN "agent_artifact"."name" IS '产物名称';
COMMENT ON COLUMN "agent_artifact"."content" IS '产物内容或安全摘要';
COMMENT ON COLUMN "agent_artifact"."file_path" IS '产物文件路径或外部引用，可为空';
COMMENT ON COLUMN "agent_artifact"."created_at" IS '产物创建时间';
COMMENT ON COLUMN "agent_channel_binding"."id" IS 'Agent 渠道绑定记录 ID';
COMMENT ON COLUMN "agent_channel_binding"."publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "agent_channel_binding"."direction" IS 'Agent 渠道绑定的方向';
COMMENT ON COLUMN "agent_channel_binding"."connector_id" IS 'Agent 渠道绑定的ConnectorID';
COMMENT ON COLUMN "agent_channel_binding"."config_json" IS 'Agent 渠道绑定的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_channel_binding"."created_at" IS 'Agent 渠道绑定创建时间';
COMMENT ON COLUMN "agent_definition"."id" IS 'Agent 定义记录 ID';
COMMENT ON COLUMN "agent_definition"."code" IS 'Agent 定义的编码';
COMMENT ON COLUMN "agent_definition"."name" IS 'Agent 定义的名称';
COMMENT ON COLUMN "agent_definition"."description" IS 'Agent 定义的描述';
COMMENT ON COLUMN "agent_definition"."project_code" IS 'Agent 定义的项目编码';
COMMENT ON COLUMN "agent_definition"."status" IS 'Agent 定义当前生命周期状态';
COMMENT ON COLUMN "agent_definition"."current_publication_id" IS 'Agent 定义的当前发布ID';
COMMENT ON COLUMN "agent_definition"."revision" IS 'Agent 定义乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "agent_definition"."created_by" IS '创建Agent 定义的用户或服务主体标识';
COMMENT ON COLUMN "agent_definition"."created_at" IS 'Agent 定义创建时间';
COMMENT ON COLUMN "agent_definition"."updated_at" IS 'Agent 定义最近更新时间';
COMMENT ON COLUMN "agent_definition"."classification" IS 'Agent 分类；internal_diagnostic 才允许绑定内部诊断 Handler';
COMMENT ON COLUMN "agent_definition"."runtime_kind" IS 'Agent创建后不可变的执行Runtime；只能为python-v1或typescript-v1';
COMMENT ON COLUMN "agent_job"."id" IS 'Agent Job记录 ID';
COMMENT ON COLUMN "agent_job"."session_id" IS '归属的 Agent 会话 ID';
COMMENT ON COLUMN "agent_job"."idempotency_key" IS '幂等键，用于防止同一外部请求重复创建任务';
COMMENT ON COLUMN "agent_job"."user_id" IS '发起任务的用户或服务主体 ID';
COMMENT ON COLUMN "agent_job"."project_code" IS '项目编码，用于权限校验、数据源选择和诊断上下文限定';
COMMENT ON COLUMN "agent_job"."source" IS '早期任务来源标识，例如 dingding 或 debug_api';
COMMENT ON COLUMN "agent_job"."user_message" IS '用户原始问题或外部告警转换后的诊断请求文本';
COMMENT ON COLUMN "agent_job"."status" IS '任务状态，例如 PENDING、RUNNING、SUCCEEDED、FAILED';
COMMENT ON COLUMN "agent_job"."priority" IS '任务优先级，数值越小表示优先级越高';
COMMENT ON COLUMN "agent_job"."retry_count" IS '任务已重试次数';
COMMENT ON COLUMN "agent_job"."max_retry_count" IS '任务最大允许重试次数';
COMMENT ON COLUMN "agent_job"."result" IS 'Agent 最终诊断结果文本，未完成或失败时可为空';
COMMENT ON COLUMN "agent_job"."error_message" IS '任务失败时的安全错误摘要';
COMMENT ON COLUMN "agent_job"."created_at" IS '任务创建时间';
COMMENT ON COLUMN "agent_job"."started_at" IS '任务开始执行时间，未开始时为空';
COMMENT ON COLUMN "agent_job"."finished_at" IS '任务完成时间，未完成时为空';
COMMENT ON COLUMN "agent_job"."locked_at" IS '任务被 worker 锁定的时间，用于并发调度控制';
COMMENT ON COLUMN "agent_job"."locked_by" IS '锁定该任务的 worker 标识';
COMMENT ON COLUMN "agent_job"."source_channel" IS '创建该任务的来源 Channel 类型，例如 dingding、debug_api、grafana_alert';
COMMENT ON COLUMN "agent_job"."source_connector_id" IS '创建该任务的来源 connector ID';
COMMENT ON COLUMN "agent_job"."external_event_id" IS '外部系统事件 ID，用于 webhook 幂等和跨系统追踪';
COMMENT ON COLUMN "agent_job"."requester_id" IS '归一化后的请求方身份，通常与 user_id 保持一致并用于权限和审计';
COMMENT ON COLUMN "agent_job"."routing_context_json" IS '任务诊断范围 JSON，传递给 Agent 上下文和内部工具寻址逻辑';
COMMENT ON COLUMN "agent_job"."reply_route_json" IS '任务结果投递路由 JSON，供 ResultDeliveryService 发送成功报告或失败通知';
COMMENT ON COLUMN "agent_job"."internal_user_id" IS 'Agent Job的内部用户ID';
COMMENT ON COLUMN "agent_job"."external_identity_id" IS 'Agent Job的外部身份ID';
COMMENT ON COLUMN "agent_job"."agent_definition_id" IS 'Agent Job的Agent定义ID';
COMMENT ON COLUMN "agent_job"."agent_publication_id" IS 'Agent Job的Agent发布ID';
COMMENT ON COLUMN "agent_job"."agent_revision" IS 'Agent Job的Agent修订';
COMMENT ON COLUMN "agent_job"."agent_config_hash" IS 'Agent Job的Agent配置哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_job"."webhook_event_id" IS '受管Webhook来源event ID，非Webhook job为空';
COMMENT ON COLUMN "agent_job"."webhook_trigger_id" IS '关联的Webhook 触发器定义 ID（webhook_trigger_definition.id）';
COMMENT ON COLUMN "agent_job"."webhook_trigger_publication_id" IS 'job创建时固定的Webhook Trigger publication ID';
COMMENT ON COLUMN "agent_job"."last_error_code" IS 'Agent Job的最近错误编码';
COMMENT ON COLUMN "agent_job"."last_error_at" IS 'Agent Job的最近错误时间';
COMMENT ON COLUMN "agent_job"."next_retry_at" IS 'Agent Job的下次重试时间';
COMMENT ON COLUMN "agent_job"."business_application_id" IS '创建Job时命中的稳定业务应用ID；历史或兼容路径为空';
COMMENT ON COLUMN "agent_job"."business_application_code" IS 'Agent Job的业务应用编码';
COMMENT ON COLUMN "agent_job"."business_application_publication_id" IS '创建Job时固定的不可变业务应用Publication';
COMMENT ON COLUMN "agent_job"."business_application_deployment_id" IS 'Agent Job的业务应用部署ID';
COMMENT ON COLUMN "agent_job"."business_application_route_id" IS '创建Job时命中的活动route ID，仅作历史来源，不建立会被停用删除的外键';
COMMENT ON COLUMN "agent_job"."business_application_config_hash" IS 'Agent Job的业务应用配置哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_job"."business_application_runtime_status" IS 'Agent Job的业务应用Runtime状态';
COMMENT ON COLUMN "agent_job"."business_application_route_decision_json" IS '脱敏的运行时路由决策和组件状态摘要';
COMMENT ON COLUMN "agent_job"."execution_policy_json" IS '创建Job时固定的v1执行策略，包含requested/effective/sources；维护迁移后强制非空且无默认值';
COMMENT ON COLUMN "agent_job"."execution_policy_tool_call_count" IS '当前或最终执行attempt内进入内部MCP handler的调用尝试数';
COMMENT ON COLUMN "agent_job"."execution_policy_exhausted" IS '最终执行attempt是否因执行策略耗尽而结束';
COMMENT ON COLUMN "agent_job"."model_runtime_provenance_json" IS 'Job创建时固定的非敏感模型运行来源，不包含Secret ID、引用或明文';
COMMENT ON COLUMN "agent_job"."agent_runtime_kind" IS 'Agent Job的AgentRuntime类型';
COMMENT ON COLUMN "agent_job"."agent_runtime_protocol_version" IS 'Agent Job的AgentRuntime协议版本';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."id" IS 'Job MCP 工具快照记录 ID';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."application_publication_id" IS '关联的业务应用发布 ID（business_application_publication.id）';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."agent_publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."schema_version" IS 'Job MCP 工具快照的Schema版本';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."snapshot_json" IS 'Job MCP 工具快照的快照JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."snapshot_hash" IS 'Job MCP 工具快照的快照哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."authorization_hash" IS 'Job MCP 工具快照的授权快照哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_job_mcp_tool_snapshot"."created_at" IS 'Job MCP 工具快照创建时间';
COMMENT ON COLUMN "agent_message"."id" IS '消息 ID';
COMMENT ON COLUMN "agent_message"."session_id" IS '归属的 Agent 会话 ID';
COMMENT ON COLUMN "agent_message"."job_id" IS '关联的 Agent job ID，可为空表示会话级消息';
COMMENT ON COLUMN "agent_message"."role" IS '消息角色，例如 user、assistant、system';
COMMENT ON COLUMN "agent_message"."content" IS '消息正文内容';
COMMENT ON COLUMN "agent_message"."created_at" IS '消息创建时间';
COMMENT ON COLUMN "agent_message"."external_message_id" IS 'Agent 消息的外部消息ID';
COMMENT ON COLUMN "agent_message"."sender_id" IS 'Agent 消息的发送人ID';
COMMENT ON COLUMN "agent_message"."sender_display_name" IS 'Agent 消息的发送人显示名称';
COMMENT ON COLUMN "agent_message"."message_type" IS 'Agent 消息的消息类型';
COMMENT ON COLUMN "agent_message"."sequence_no" IS 'Agent 消息的序列序号';
COMMENT ON COLUMN "agent_message"."content_status" IS 'Agent 消息的内容状态';
COMMENT ON COLUMN "agent_message"."safe_metadata_json" IS 'Agent 消息的安全元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_publication"."id" IS 'Agent 发布记录 ID';
COMMENT ON COLUMN "agent_publication"."agent_id" IS '关联的Agent 定义 ID（agent_definition.id）';
COMMENT ON COLUMN "agent_publication"."revision_id" IS '关联的Agent 修订 ID（agent_revision.id）';
COMMENT ON COLUMN "agent_publication"."revision" IS 'Agent 发布乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "agent_publication"."schema_version" IS 'Agent 发布的Schema版本';
COMMENT ON COLUMN "agent_publication"."snapshot_json" IS 'Agent 发布的快照JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_publication"."config_hash" IS 'Agent 发布的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_publication"."status" IS 'Agent 发布当前生命周期状态';
COMMENT ON COLUMN "agent_publication"."published_by" IS 'Agent 发布的发布主体标识';
COMMENT ON COLUMN "agent_publication"."published_at" IS 'Agent 发布的发布时间';
COMMENT ON COLUMN "agent_publication"."runtime_kind" IS '发布时从Agent Definition冻结的Runtime投影；legacy schema v1确定性回填python-v1';
COMMENT ON COLUMN "agent_publication_mcp_tool"."agent_publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "agent_publication_mcp_tool"."server_code" IS 'Agent 发布 MCP 工具的服务端编码';
COMMENT ON COLUMN "agent_publication_mcp_tool"."tool_identifier" IS 'Agent 发布 MCP 工具的工具标识';
COMMENT ON COLUMN "agent_publication_mcp_tool"."schema_hash" IS 'Agent 发布 MCP 工具的Schema哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_publication_mcp_tool"."model_description" IS 'Agent 发布 MCP 工具的模型描述';
COMMENT ON COLUMN "agent_publication_mcp_tool"."selection_order" IS 'Agent 发布 MCP 工具的选择顺序';
COMMENT ON COLUMN "agent_publication_mcp_tool"."created_at" IS 'Agent 发布 MCP 工具创建时间';
COMMENT ON COLUMN "agent_revision"."id" IS 'Agent 修订记录 ID';
COMMENT ON COLUMN "agent_revision"."agent_id" IS '关联的Agent 定义 ID（agent_definition.id）';
COMMENT ON COLUMN "agent_revision"."revision" IS 'Agent 修订乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "agent_revision"."status" IS 'Agent 修订当前生命周期状态';
COMMENT ON COLUMN "agent_revision"."config_json" IS 'Agent 修订的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_revision"."config_hash" IS 'Agent 修订的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_revision"."validation_json" IS 'Agent 修订的校验JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_revision"."created_by" IS '创建Agent 修订的用户或服务主体标识';
COMMENT ON COLUMN "agent_revision"."created_at" IS 'Agent 修订创建时间';
COMMENT ON COLUMN "agent_revision"."updated_at" IS 'Agent 修订最近更新时间';
COMMENT ON COLUMN "agent_runtime_event"."id" IS 'Agent Runtime 事件记录 ID';
COMMENT ON COLUMN "agent_runtime_event"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "agent_runtime_event"."invocation_id" IS 'Agent Runtime 事件的调用ID';
COMMENT ON COLUMN "agent_runtime_event"."request_digest" IS 'Agent Runtime 事件的请求摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_runtime_event"."sequence" IS 'Agent Runtime 事件的序列';
COMMENT ON COLUMN "agent_runtime_event"."event_type" IS 'Agent Runtime 事件的事件类型';
COMMENT ON COLUMN "agent_runtime_event"."payload_json" IS '仅保存V1契约允许的安全payload；写入前再次执行敏感字段清理';
COMMENT ON COLUMN "agent_runtime_event"."created_at" IS 'Agent Runtime 事件创建时间';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."invocation_id" IS 'Agent Runtime 调用占用的调用ID';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."request_digest" IS 'Agent Runtime 调用占用的请求摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."runtime_kind" IS 'Agent Runtime 调用占用的Runtime类型';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."owner_instance_id" IS 'Runtime进程启动实例标识，仅用于区分本进程执行与重启遗留执行，不是凭据';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."claimed_at" IS 'Agent Runtime 调用占用的领取时间';
COMMENT ON COLUMN "agent_runtime_invocation_claim"."expires_at" IS 'Agent Runtime 调用占用的过期时间';
COMMENT ON COLUMN "agent_runtime_invocation_event"."invocation_id" IS 'Agent Runtime 调用事件的调用ID';
COMMENT ON COLUMN "agent_runtime_invocation_event"."request_digest" IS 'Agent Runtime 调用事件的请求摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_runtime_invocation_event"."sequence" IS 'Agent Runtime 调用事件的序列';
COMMENT ON COLUMN "agent_runtime_invocation_event"."event_json" IS '模型调用过程的追加式脱敏事件 JSON，不用于重放模型请求';
COMMENT ON COLUMN "agent_runtime_invocation_event"."created_at" IS 'Agent Runtime 调用事件创建时间';
COMMENT ON COLUMN "agent_runtime_invocation_event"."expires_at" IS 'Agent Runtime 调用事件的过期时间';
COMMENT ON COLUMN "agent_runtime_terminal_ledger"."invocation_id" IS 'Agent Runtime 终态账本的调用ID';
COMMENT ON COLUMN "agent_runtime_terminal_ledger"."request_digest" IS 'Agent Runtime 终态账本的请求摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_runtime_terminal_ledger"."events_json" IS '用于终态恢复的有界规范事件 JSON，不包含 Secret 或原始 SDK 消息';
COMMENT ON COLUMN "agent_runtime_terminal_ledger"."terminal_at" IS 'Agent Runtime 终态账本的终态时间';
COMMENT ON COLUMN "agent_runtime_terminal_ledger"."expires_at" IS 'Agent Runtime 终态账本的过期时间';
COMMENT ON COLUMN "agent_session"."id" IS 'Agent 会话 ID';
COMMENT ON COLUMN "agent_session"."dingding_conversation_id" IS '钉钉会话 ID，用于兼容早期钉钉入口会话归属';
COMMENT ON COLUMN "agent_session"."dingding_user_id" IS '钉钉用户 ID，用于兼容早期钉钉入口请求人标识';
COMMENT ON COLUMN "agent_session"."source" IS '早期请求来源标识，例如 dingding 或 debug_api';
COMMENT ON COLUMN "agent_session"."project_code" IS '项目编码，用于选择权限、数据源和诊断上下文';
COMMENT ON COLUMN "agent_session"."created_at" IS '会话创建时间';
COMMENT ON COLUMN "agent_session"."updated_at" IS '会话最近更新时间';
COMMENT ON COLUMN "agent_session"."source_channel" IS '请求来源 Channel 类型，例如 dingding、debug_api、grafana_alert';
COMMENT ON COLUMN "agent_session"."source_connector_id" IS '来源 connector ID，用于关联入口配置、验签和审计';
COMMENT ON COLUMN "agent_session"."external_conversation_id" IS '外部系统的会话 ID，例如钉钉会话、调试会话或告警分组';
COMMENT ON COLUMN "agent_session"."requester_id" IS '归一化后的请求方身份，用户或服务账号均使用该字段做权限判断';
COMMENT ON COLUMN "agent_session"."requester_display_name" IS '请求方展示名称，仅用于展示和审计摘要，不参与权限判断';
COMMENT ON COLUMN "agent_session"."routing_context_json" IS '请求路由上下文 JSON，包含 project/environment/base/workshop/service 等诊断范围';
COMMENT ON COLUMN "agent_session"."reply_route_json" IS '结果投递路由 JSON，描述 delivery type、connector、target 和投递选项';
COMMENT ON COLUMN "agent_session"."session_key" IS 'Agent 会话的会话键';
COMMENT ON COLUMN "agent_session"."conversation_type" IS 'Agent 会话的会话类型';
COMMENT ON COLUMN "agent_session"."bot_identity" IS 'Agent 会话的机器人身份';
COMMENT ON COLUMN "agent_session"."summary_text" IS 'Agent 会话的摘要文本';
COMMENT ON COLUMN "agent_session"."summary_through_sequence" IS 'Agent 会话的摘要截至序列';
COMMENT ON COLUMN "agent_session"."summary_version" IS 'Agent 会话的摘要版本';
COMMENT ON COLUMN "agent_session"."message_sequence" IS 'Agent 会话的消息序列';
COMMENT ON COLUMN "agent_session"."last_message_at" IS 'Agent 会话的最近消息时间';
COMMENT ON COLUMN "agent_session"."external_identity_id" IS 'Agent 会话的外部身份ID';
COMMENT ON COLUMN "agent_session"."business_application_id" IS '稳定业务应用ID，用于隔离连续会话；历史会话为空';
COMMENT ON COLUMN "agent_session"."business_application_code" IS 'Agent 会话的业务应用编码';
COMMENT ON COLUMN "agent_session"."conversation_mode" IS 'Agent 会话的会话模式';
COMMENT ON COLUMN "agent_session"."recent_message_limit" IS 'Agent 会话的最近消息上限';
COMMENT ON COLUMN "agent_session"."session_policy_json" IS '创建会话时固定的业务应用会话策略安全摘要';
COMMENT ON COLUMN "agent_session"."application_publication_id" IS 'Session v2 固定的业务应用发布 ID；旧历史可空';
COMMENT ON COLUMN "agent_session"."execution_scope_hash" IS 'Session v2 固定的 canonical Execution Scope SHA-256；旧历史可空';
COMMENT ON COLUMN "agent_session"."isolation_key_version" IS 'Session 隔离键契约版本；新会话为 2';
COMMENT ON COLUMN "agent_session"."history_read_only" IS '旧 application/actor Session 只允许历史读取，不得附着新 Job';
COMMENT ON COLUMN "agent_skill_binding"."id" IS 'Agent Skill 绑定记录 ID';
COMMENT ON COLUMN "agent_skill_binding"."publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "agent_skill_binding"."skill_code" IS 'Agent Skill 绑定的Skill编码';
COMMENT ON COLUMN "agent_skill_binding"."created_at" IS 'Agent Skill 绑定创建时间';
COMMENT ON COLUMN "agent_step"."id" IS '执行步骤 ID';
COMMENT ON COLUMN "agent_step"."job_id" IS '关联的 Agent job ID';
COMMENT ON COLUMN "agent_step"."step_type" IS '步骤类型，例如 plan、tool、analysis、final';
COMMENT ON COLUMN "agent_step"."title" IS '步骤标题';
COMMENT ON COLUMN "agent_step"."content" IS '步骤内容或摘要';
COMMENT ON COLUMN "agent_step"."created_at" IS '步骤创建时间';
COMMENT ON COLUMN "agent_tool_call"."id" IS '工具调用 ID';
COMMENT ON COLUMN "agent_tool_call"."job_id" IS '关联的 Agent job ID';
COMMENT ON COLUMN "agent_tool_call"."tool_name" IS '工具名称，例如 database.query、loki.query、schema.directory';
COMMENT ON COLUMN "agent_tool_call"."request_payload" IS '工具请求载荷 JSON，应避免保存敏感明文';
COMMENT ON COLUMN "agent_tool_call"."response_summary" IS '工具响应安全摘要';
COMMENT ON COLUMN "agent_tool_call"."status" IS '工具调用状态，例如 SUCCEEDED、FAILED、DENIED';
COMMENT ON COLUMN "agent_tool_call"."duration_ms" IS '工具调用耗时，单位毫秒';
COMMENT ON COLUMN "agent_tool_call"."risk_level" IS '工具风险级别，例如 low、medium、high';
COMMENT ON COLUMN "agent_tool_call"."audit_id" IS '关联的审计事件 ID';
COMMENT ON COLUMN "agent_tool_call"."created_at" IS '工具调用记录创建时间';
COMMENT ON COLUMN "agent_workflow_edge"."id" IS 'Agent 工作流连线记录 ID';
COMMENT ON COLUMN "agent_workflow_edge"."template_id" IS '关联的Agent 工作流模板 ID（agent_workflow_template.id）';
COMMENT ON COLUMN "agent_workflow_edge"."edge_key" IS 'Agent 工作流连线的连线键';
COMMENT ON COLUMN "agent_workflow_edge"."source_node_key" IS 'Agent 工作流连线的来源节点键';
COMMENT ON COLUMN "agent_workflow_edge"."target_node_key" IS 'Agent 工作流连线的目标节点键';
COMMENT ON COLUMN "agent_workflow_edge"."source_port" IS 'Agent 工作流连线的来源端口';
COMMENT ON COLUMN "agent_workflow_edge"."target_port" IS 'Agent 工作流连线的目标端口';
COMMENT ON COLUMN "agent_workflow_edge"."condition_json" IS 'Agent 工作流连线的条件JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_edge"."created_at" IS 'Agent 工作流连线创建时间';
COMMENT ON COLUMN "agent_workflow_edge"."updated_at" IS 'Agent 工作流连线最近更新时间';
COMMENT ON COLUMN "agent_workflow_node"."id" IS 'Agent 工作流节点记录 ID';
COMMENT ON COLUMN "agent_workflow_node"."template_id" IS '关联的Agent 工作流模板 ID（agent_workflow_template.id）';
COMMENT ON COLUMN "agent_workflow_node"."node_key" IS 'Agent 工作流节点的节点键';
COMMENT ON COLUMN "agent_workflow_node"."node_type" IS 'Agent 工作流节点的节点类型';
COMMENT ON COLUMN "agent_workflow_node"."title" IS 'Agent 工作流节点的标题';
COMMENT ON COLUMN "agent_workflow_node"."position_json" IS 'Agent 工作流节点的位置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_node"."config_json" IS 'Agent 工作流节点的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_node"."ui_json" IS 'Agent 工作流节点的界面JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_node"."created_at" IS 'Agent 工作流节点创建时间';
COMMENT ON COLUMN "agent_workflow_node"."updated_at" IS 'Agent 工作流节点最近更新时间';
COMMENT ON COLUMN "agent_workflow_publication"."id" IS 'Agent 工作流发布记录 ID';
COMMENT ON COLUMN "agent_workflow_publication"."template_id" IS '关联的Agent 工作流模板 ID（agent_workflow_template.id）';
COMMENT ON COLUMN "agent_workflow_publication"."version" IS 'Agent 工作流发布的版本';
COMMENT ON COLUMN "agent_workflow_publication"."graph_snapshot_json" IS 'Agent 工作流发布的流程图快照JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_publication"."config_hash" IS 'Agent 工作流发布的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "agent_workflow_publication"."published_by" IS 'Agent 工作流发布的发布主体标识';
COMMENT ON COLUMN "agent_workflow_publication"."published_at" IS 'Agent 工作流发布的发布时间';
COMMENT ON COLUMN "agent_workflow_template"."id" IS 'Agent 工作流模板记录 ID';
COMMENT ON COLUMN "agent_workflow_template"."code" IS 'Agent 工作流模板的编码';
COMMENT ON COLUMN "agent_workflow_template"."name" IS 'Agent 工作流模板的名称';
COMMENT ON COLUMN "agent_workflow_template"."description" IS 'Agent 工作流模板的描述';
COMMENT ON COLUMN "agent_workflow_template"."project_code" IS 'Agent 工作流模板的项目编码';
COMMENT ON COLUMN "agent_workflow_template"."status" IS 'Agent 工作流模板当前生命周期状态';
COMMENT ON COLUMN "agent_workflow_template"."version" IS 'Agent 工作流模板的版本';
COMMENT ON COLUMN "agent_workflow_template"."entry_node_key" IS 'Agent 工作流模板的入口节点键';
COMMENT ON COLUMN "agent_workflow_template"."graph_schema_version" IS 'Agent 工作流模板的流程图Schema版本';
COMMENT ON COLUMN "agent_workflow_template"."graph_json" IS 'Agent 工作流模板的流程图JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_template"."settings_json" IS 'Agent 工作流模板的设置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "agent_workflow_template"."created_by" IS '创建Agent 工作流模板的用户或服务主体标识';
COMMENT ON COLUMN "agent_workflow_template"."created_at" IS 'Agent 工作流模板创建时间';
COMMENT ON COLUMN "agent_workflow_template"."updated_at" IS 'Agent 工作流模板最近更新时间';
COMMENT ON COLUMN "app_user"."id" IS '平台用户记录 ID';
COMMENT ON COLUMN "app_user"."username" IS '平台用户的登录用户名';
COMMENT ON COLUMN "app_user"."display_name" IS '平台用户的显示名称';
COMMENT ON COLUMN "app_user"."email" IS '平台用户的邮箱地址';
COMMENT ON COLUMN "app_user"."status" IS '平台用户当前生命周期状态';
COMMENT ON COLUMN "app_user"."revision" IS '平台用户乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "app_user"."created_at" IS '平台用户创建时间';
COMMENT ON COLUMN "app_user"."updated_at" IS '平台用户最近更新时间';
COMMENT ON COLUMN "app_user"."account_type" IS '账号类型：human为自然人，service为不可交互登录的受管服务账号';
COMMENT ON COLUMN "attachment_content"."id" IS '附件解析内容记录 ID';
COMMENT ON COLUMN "attachment_content"."attachment_id" IS '关联的消息附件 ID（message_attachment.id）';
COMMENT ON COLUMN "attachment_content"."plain_text" IS '附件解析内容的受限解析后的纯文本';
COMMENT ON COLUMN "attachment_content"."segments_json" IS '附件解析内容的分段JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "attachment_content"."parser_version" IS '附件解析内容的解析器版本';
COMMENT ON COLUMN "attachment_content"."char_count" IS '附件解析内容的字符数量';
COMMENT ON COLUMN "attachment_content"."truncated" IS '附件解析内容结果是否已截断';
COMMENT ON COLUMN "attachment_content"."created_at" IS '附件解析内容创建时间';
COMMENT ON COLUMN "audit_event"."id" IS '审计事件 ID';
COMMENT ON COLUMN "audit_event"."job_id" IS '关联的 Agent job ID，可为空表示系统级审计事件';
COMMENT ON COLUMN "audit_event"."event_type" IS '审计事件类型，例如 permission_check、tool_call、delivery';
COMMENT ON COLUMN "audit_event"."actor_id" IS '触发事件的用户、服务或 worker 标识';
COMMENT ON COLUMN "audit_event"."status" IS '审计事件状态，例如 ALLOWED、DENIED、SUCCEEDED、FAILED';
COMMENT ON COLUMN "audit_event"."summary" IS '面向审计阅读的事件摘要';
COMMENT ON COLUMN "audit_event"."payload_summary" IS '安全载荷摘要 JSON，不保存敏感明文';
COMMENT ON COLUMN "audit_event"."created_at" IS '审计事件创建时间';
COMMENT ON COLUMN "business_application"."id" IS '业务应用记录 ID';
COMMENT ON COLUMN "business_application"."code" IS '业务应用的编码';
COMMENT ON COLUMN "business_application"."name" IS '业务应用的名称';
COMMENT ON COLUMN "business_application"."description" IS '业务应用的描述';
COMMENT ON COLUMN "business_application"."project_code" IS '业务应用的项目编码';
COMMENT ON COLUMN "business_application"."owner_user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "business_application"."status" IS '业务应用当前生命周期状态';
COMMENT ON COLUMN "business_application"."revision" IS '业务应用乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "business_application"."created_by" IS '创建业务应用的用户或服务主体标识';
COMMENT ON COLUMN "business_application"."created_at" IS '业务应用创建时间';
COMMENT ON COLUMN "business_application"."updated_at" IS '业务应用最近更新时间';
COMMENT ON COLUMN "business_application_active_route"."id" IS '业务应用活动路由记录 ID';
COMMENT ON COLUMN "business_application_active_route"."deployment_id" IS '关联的业务应用部署 ID（business_application_deployment.id）';
COMMENT ON COLUMN "business_application_active_route"."application_id" IS '关联的业务应用 ID（business_application.id）';
COMMENT ON COLUMN "business_application_active_route"."publication_id" IS '关联的业务应用发布 ID（business_application_publication.id）';
COMMENT ON COLUMN "business_application_active_route"."environment" IS '业务应用活动路由的环境';
COMMENT ON COLUMN "business_application_active_route"."trigger_type" IS '业务应用活动路由的触发器类型';
COMMENT ON COLUMN "business_application_active_route"."connector_id" IS '业务应用活动路由的ConnectorID';
COMMENT ON COLUMN "business_application_active_route"."normalized_routing_key" IS '业务应用活动路由的标准化路由键';
COMMENT ON COLUMN "business_application_active_route"."created_at" IS '业务应用活动路由创建时间';
COMMENT ON COLUMN "business_application_deployment"."id" IS '业务应用部署记录 ID';
COMMENT ON COLUMN "business_application_deployment"."application_id" IS '关联的业务应用 ID（business_application.id）';
COMMENT ON COLUMN "business_application_deployment"."environment" IS '业务应用部署的环境';
COMMENT ON COLUMN "business_application_deployment"."publication_id" IS '关联的业务应用发布 ID（business_application_publication.id）';
COMMENT ON COLUMN "business_application_deployment"."active" IS '业务应用部署是否处于生效状态';
COMMENT ON COLUMN "business_application_deployment"."revision" IS '业务应用部署乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "business_application_deployment"."activated_by" IS '业务应用部署的激活主体标识';
COMMENT ON COLUMN "business_application_deployment"."activated_at" IS '业务应用部署的激活时间';
COMMENT ON COLUMN "business_application_deployment"."deactivated_by" IS '业务应用部署的停用主体标识';
COMMENT ON COLUMN "business_application_deployment"."deactivated_at" IS '业务应用部署的停用时间';
COMMENT ON COLUMN "business_application_deployment"."updated_at" IS '业务应用部署最近更新时间';
COMMENT ON COLUMN "business_application_publication"."id" IS '业务应用发布记录 ID';
COMMENT ON COLUMN "business_application_publication"."application_id" IS '关联的业务应用 ID（business_application.id）';
COMMENT ON COLUMN "business_application_publication"."revision_id" IS '关联的业务应用修订 ID（business_application_revision.id）';
COMMENT ON COLUMN "business_application_publication"."revision" IS '业务应用发布乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "business_application_publication"."schema_version" IS '业务应用发布的Schema版本';
COMMENT ON COLUMN "business_application_publication"."snapshot_json" IS '业务应用发布的快照JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_publication"."config_hash" IS '业务应用发布的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "business_application_publication"."published_by" IS '业务应用发布的发布主体标识';
COMMENT ON COLUMN "business_application_publication"."published_at" IS '业务应用发布的发布时间';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."application_publication_id" IS '关联的业务应用发布 ID（business_application_publication.id）';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."agent_publication_id" IS '关联的Agent 发布 MCP 工具 ID（agent_publication_mcp_tool.agent_publication_id）';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."server_code" IS '业务应用发布 MCP 工具的服务端编码';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."tool_identifier" IS '关联的Agent 发布 MCP 工具 ID（agent_publication_mcp_tool.tool_identifier）';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."schema_hash" IS '业务应用发布 MCP 工具的Schema哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."selection_order" IS '业务应用发布 MCP 工具的选择顺序';
COMMENT ON COLUMN "business_application_publication_mcp_tool"."created_at" IS '业务应用发布 MCP 工具创建时间';
COMMENT ON COLUMN "business_application_revision"."id" IS '业务应用修订记录 ID';
COMMENT ON COLUMN "business_application_revision"."application_id" IS '关联的业务应用 ID（business_application.id）';
COMMENT ON COLUMN "business_application_revision"."revision" IS '业务应用修订乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "business_application_revision"."status" IS '业务应用修订当前生命周期状态';
COMMENT ON COLUMN "business_application_revision"."agent_publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "business_application_revision"."workflow_publication_id" IS '关联的Agent 工作流发布 ID（agent_workflow_publication.id）';
COMMENT ON COLUMN "business_application_revision"."session_policy_json" IS '业务应用修订的会话策略JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_revision"."execution_policy_json" IS '业务应用修订的执行策略JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_revision"."validation_json" IS '业务应用修订的校验JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_revision"."config_hash" IS '业务应用修订的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "business_application_revision"."created_by" IS '创建业务应用修订的用户或服务主体标识';
COMMENT ON COLUMN "business_application_revision"."created_at" IS '业务应用修订创建时间';
COMMENT ON COLUMN "business_application_revision"."updated_at" IS '业务应用修订最近更新时间';
COMMENT ON COLUMN "business_application_revision_delivery"."id" IS '业务应用修订投递配置记录 ID';
COMMENT ON COLUMN "business_application_revision_delivery"."revision_id" IS '关联的业务应用修订 ID（business_application_revision.id）';
COMMENT ON COLUMN "business_application_revision_delivery"."binding_order" IS '业务应用修订投递配置的绑定顺序';
COMMENT ON COLUMN "business_application_revision_delivery"."delivery_type" IS '业务应用修订投递配置的投递类型';
COMMENT ON COLUMN "business_application_revision_delivery"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "business_application_revision_delivery"."enabled" IS '业务应用修订投递配置是否启用';
COMMENT ON COLUMN "business_application_revision_delivery"."config_json" IS '业务应用修订投递配置的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_revision_delivery"."created_at" IS '业务应用修订投递配置创建时间';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."application_revision_id" IS '关联的业务应用修订 ID（business_application_revision.id）';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."agent_publication_id" IS '关联的Agent 发布 MCP 工具 ID（agent_publication_mcp_tool.agent_publication_id）';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."server_code" IS '业务应用修订 MCP 工具的服务端编码';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."tool_identifier" IS '关联的Agent 发布 MCP 工具 ID（agent_publication_mcp_tool.tool_identifier）';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."schema_hash" IS '业务应用修订 MCP 工具的Schema哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."selection_order" IS '业务应用修订 MCP 工具的选择顺序';
COMMENT ON COLUMN "business_application_revision_mcp_tool"."created_at" IS '业务应用修订 MCP 工具创建时间';
COMMENT ON COLUMN "business_application_revision_trigger"."id" IS '业务应用修订触发器记录 ID';
COMMENT ON COLUMN "business_application_revision_trigger"."revision_id" IS '关联的业务应用修订 ID（business_application_revision.id）';
COMMENT ON COLUMN "business_application_revision_trigger"."binding_order" IS '业务应用修订触发器的绑定顺序';
COMMENT ON COLUMN "business_application_revision_trigger"."trigger_type" IS '业务应用修订触发器的触发器类型';
COMMENT ON COLUMN "business_application_revision_trigger"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "business_application_revision_trigger"."routing_key" IS '业务应用修订触发器的路由键';
COMMENT ON COLUMN "business_application_revision_trigger"."normalized_routing_key" IS '业务应用修订触发器的标准化路由键';
COMMENT ON COLUMN "business_application_revision_trigger"."actor_policy" IS '业务应用修订触发器的操作主体策略';
COMMENT ON COLUMN "business_application_revision_trigger"."service_account_user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "business_application_revision_trigger"."enabled" IS '业务应用修订触发器是否启用';
COMMENT ON COLUMN "business_application_revision_trigger"."config_json" IS '业务应用修订触发器的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "business_application_revision_trigger"."created_at" IS '业务应用修订触发器创建时间';
COMMENT ON COLUMN "channel_connector_runtime"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "channel_connector_runtime"."runtime_id" IS '渠道 Connector 运行状态的RuntimeID';
COMMENT ON COLUMN "channel_connector_runtime"."runtime_status" IS '渠道 Connector 运行状态的Runtime状态';
COMMENT ON COLUMN "channel_connector_runtime"."loaded_revision" IS '渠道 Connector 运行状态的已加载修订';
COMMENT ON COLUMN "channel_connector_runtime"."connected" IS '渠道 Connector 运行状态是否已连接';
COMMENT ON COLUMN "channel_connector_runtime"."registered" IS '渠道 Connector 运行状态是否已完成注册';
COMMENT ON COLUMN "channel_connector_runtime"."connected_at" IS '渠道 Connector 运行状态的连接时间';
COMMENT ON COLUMN "channel_connector_runtime"."disconnected_at" IS '渠道 Connector 运行状态的断开连接时间';
COMMENT ON COLUMN "channel_connector_runtime"."last_message_at" IS '渠道 Connector 运行状态的最近消息时间';
COMMENT ON COLUMN "channel_connector_runtime"."last_heartbeat_at" IS '渠道 Connector 运行状态的最近心跳时间';
COMMENT ON COLUMN "channel_connector_runtime"."last_error_code" IS '渠道 Connector 运行状态的最近错误编码';
COMMENT ON COLUMN "channel_connector_runtime"."last_error_summary" IS '渠道 Connector 运行状态的最近错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "channel_connector_runtime"."updated_at" IS '渠道 Connector 运行状态最近更新时间';
COMMENT ON COLUMN "channel_ingress_event"."id" IS '渠道入口事件记录 ID';
COMMENT ON COLUMN "channel_ingress_event"."source_type" IS '渠道入口事件的来源类型';
COMMENT ON COLUMN "channel_ingress_event"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "channel_ingress_event"."external_event_id" IS '渠道入口事件的外部事件ID';
COMMENT ON COLUMN "channel_ingress_event"."correlation_id" IS '渠道入口事件的关联追踪ID';
COMMENT ON COLUMN "channel_ingress_event"."payload_hash" IS '渠道入口事件的载荷哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "channel_ingress_event"."safe_summary_json" IS '渠道入口事件的安全摘要JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "channel_ingress_event"."normalized_event_json" IS '脱敏且有界的标准化渠道入口事件 JSON';
COMMENT ON COLUMN "channel_ingress_event"."reply_credential_ciphertext" IS '回复原会话所需短期凭据密文，终态或过期后必须清理';
COMMENT ON COLUMN "channel_ingress_event"."status" IS '渠道入口事件当前生命周期状态';
COMMENT ON COLUMN "channel_ingress_event"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "channel_ingress_event"."error_code" IS '渠道入口事件的错误编码';
COMMENT ON COLUMN "channel_ingress_event"."error_summary" IS '渠道入口事件的错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "channel_ingress_event"."request_bytes" IS '渠道入口事件的请求字节';
COMMENT ON COLUMN "channel_ingress_event"."received_at" IS '渠道入口事件的接收时间';
COMMENT ON COLUMN "channel_ingress_event"."dispatched_at" IS '渠道入口事件的派发时间';
COMMENT ON COLUMN "channel_ingress_event"."completed_at" IS '渠道入口事件的完成时间';
COMMENT ON COLUMN "channel_ingress_outbox"."id" IS '渠道入口事务 Outbox记录 ID';
COMMENT ON COLUMN "channel_ingress_outbox"."channel_event_id" IS '关联的渠道入口事件 ID（channel_ingress_event.id）';
COMMENT ON COLUMN "channel_ingress_outbox"."correlation_id" IS '渠道入口事务 Outbox的关联追踪ID';
COMMENT ON COLUMN "channel_ingress_outbox"."status" IS '渠道入口事务 Outbox当前生命周期状态';
COMMENT ON COLUMN "channel_ingress_outbox"."attempt_count" IS '渠道入口事务 Outbox的尝试数量';
COMMENT ON COLUMN "channel_ingress_outbox"."next_attempt_at" IS '渠道入口事务 Outbox的下次尝试时间';
COMMENT ON COLUMN "channel_ingress_outbox"."claimed_by" IS '渠道入口事务 Outbox的领取主体标识';
COMMENT ON COLUMN "channel_ingress_outbox"."claimed_at" IS '渠道入口事务 Outbox的领取时间';
COMMENT ON COLUMN "channel_ingress_outbox"."last_error_summary" IS '渠道入口事务 Outbox的最近错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "channel_ingress_outbox"."created_at" IS '渠道入口事务 Outbox创建时间';
COMMENT ON COLUMN "channel_ingress_outbox"."published_at" IS '渠道入口事务 Outbox的发布时间';
COMMENT ON COLUMN "channel_ingress_outbox"."updated_at" IS '渠道入口事务 Outbox最近更新时间';
COMMENT ON COLUMN "channel_runtime_lease"."lease_name" IS '渠道 Runtime 租约的租约名称';
COMMENT ON COLUMN "channel_runtime_lease"."runtime_id" IS '渠道 Runtime 租约的RuntimeID';
COMMENT ON COLUMN "channel_runtime_lease"."lease_token" IS '渠道 Runtime 租约的租约Token';
COMMENT ON COLUMN "channel_runtime_lease"."expires_at" IS '渠道 Runtime 租约的过期时间';
COMMENT ON COLUMN "channel_runtime_lease"."updated_at" IS '渠道 Runtime 租约最近更新时间';
COMMENT ON COLUMN "delivery_attempt"."id" IS '投递尝试 ID';
COMMENT ON COLUMN "delivery_attempt"."job_id" IS '关联的 Agent job ID';
COMMENT ON COLUMN "delivery_attempt"."route_type" IS '投递路由类型，例如 none、dingtalk_webhook_robot、dingtalk_enterprise_robot、email、webhook';
COMMENT ON COLUMN "delivery_attempt"."connector_id" IS '投递使用的 connector ID，none 路由可为空';
COMMENT ON COLUMN "delivery_attempt"."target_summary" IS '投递目标安全摘要 JSON，不包含 token、secret 或完整敏感 URL';
COMMENT ON COLUMN "delivery_attempt"."status" IS '投递尝试状态，例如 STARTED、SUCCEEDED、FAILED、SKIPPED';
COMMENT ON COLUMN "delivery_attempt"."error_message" IS '安全错误摘要，投递成功时为空';
COMMENT ON COLUMN "delivery_attempt"."created_at" IS '投递尝试创建时间';
COMMENT ON COLUMN "delivery_attempt"."finished_at" IS '投递尝试完成时间，未完成时为空';
COMMENT ON COLUMN "delivery_attempt"."delivery_outbox_id" IS '新投递路径所属 Delivery Outbox；旧历史 attempt 可为空';
COMMENT ON COLUMN "delivery_attempt"."replay_no" IS '投递尝试的重放序号';
COMMENT ON COLUMN "delivery_attempt"."attempt_no" IS '投递尝试的尝试序号';
COMMENT ON COLUMN "delivery_attempt"."correlation_id" IS '投递尝试的关联追踪ID';
COMMENT ON COLUMN "delivery_attempt"."idempotency_key" IS 'Delivery event、replay number 与 attempt number 组成的稳定幂等键';
COMMENT ON COLUMN "delivery_attempt"."error_code" IS '投递尝试的错误编码';
COMMENT ON COLUMN "delivery_chunk"."id" IS '投递分片 ID';
COMMENT ON COLUMN "delivery_chunk"."attempt_id" IS '关联的 delivery_attempt ID';
COMMENT ON COLUMN "delivery_chunk"."chunk_index" IS '分片序号，从 1 开始';
COMMENT ON COLUMN "delivery_chunk"."chunk_count" IS '本次投递总分片数';
COMMENT ON COLUMN "delivery_chunk"."status" IS '分片发送状态，例如 SUCCEEDED 或 FAILED';
COMMENT ON COLUMN "delivery_chunk"."payload_summary" IS '分片内容安全摘要 JSON，记录标题、长度等非敏感信息';
COMMENT ON COLUMN "delivery_chunk"."error_message" IS '分片发送失败时的安全错误摘要';
COMMENT ON COLUMN "delivery_chunk"."created_at" IS '分片记录创建时间';
COMMENT ON COLUMN "delivery_chunk"."delivery_outbox_id" IS '关联的投递事务 Outbox ID（delivery_outbox.id）';
COMMENT ON COLUMN "delivery_chunk"."replay_no" IS '投递分片的重放序号';
COMMENT ON COLUMN "delivery_chunk"."attempt_no" IS '投递分片的尝试序号';
COMMENT ON COLUMN "delivery_chunk"."idempotency_key" IS '跨 attempt 稳定的逻辑 chunk 幂等键';
COMMENT ON COLUMN "delivery_chunk"."payload_hash" IS '发送正文的 SHA-256，用于验证重试未改写 payload';
COMMENT ON COLUMN "delivery_chunk"."sent_at" IS '投递分片的发送时间';
COMMENT ON COLUMN "delivery_outbox"."id" IS '投递事务 Outbox记录 ID';
COMMENT ON COLUMN "delivery_outbox"."event_key" IS '结果 artifact 级稳定幂等键';
COMMENT ON COLUMN "delivery_outbox"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "delivery_outbox"."result_artifact_id" IS '关联的Agent 产物 ID（agent_artifact.id）';
COMMENT ON COLUMN "delivery_outbox"."application_publication_id" IS '投递事务 Outbox的应用发布ID';
COMMENT ON COLUMN "delivery_outbox"."delivery_binding_json" IS 'Job 创建时固化的 delivery route 与 connector binding，不含 Secret 明文';
COMMENT ON COLUMN "delivery_outbox"."target_summary" IS '不可逆脱敏的投递目标摘要';
COMMENT ON COLUMN "delivery_outbox"."correlation_id" IS '投递事务 Outbox的关联追踪ID';
COMMENT ON COLUMN "delivery_outbox"."status" IS '投递事务 Outbox当前生命周期状态';
COMMENT ON COLUMN "delivery_outbox"."attempt_count" IS '投递事务 Outbox的尝试数量';
COMMENT ON COLUMN "delivery_outbox"."max_attempts" IS '投递事务 Outbox的最大尝试';
COMMENT ON COLUMN "delivery_outbox"."replay_count" IS '投递事务 Outbox的重放数量';
COMMENT ON COLUMN "delivery_outbox"."max_replay_count" IS '投递事务 Outbox的最大重放数量';
COMMENT ON COLUMN "delivery_outbox"."next_attempt_at" IS '投递事务 Outbox的下次尝试时间';
COMMENT ON COLUMN "delivery_outbox"."claimed_by" IS '投递事务 Outbox的领取主体标识';
COMMENT ON COLUMN "delivery_outbox"."claim_token" IS '多副本 Dispatcher 单次 claim 的随机 ownership token';
COMMENT ON COLUMN "delivery_outbox"."claimed_at" IS '投递事务 Outbox的领取时间';
COMMENT ON COLUMN "delivery_outbox"."claim_expires_at" IS '投递事务 Outbox的占用过期时间';
COMMENT ON COLUMN "delivery_outbox"."last_error_code" IS '投递事务 Outbox的最近错误编码';
COMMENT ON COLUMN "delivery_outbox"."last_error_summary" IS '投递事务 Outbox的最近错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "delivery_outbox"."started_at" IS '投递事务 Outbox的开始时间';
COMMENT ON COLUMN "delivery_outbox"."finished_at" IS '投递事务 Outbox的结束时间';
COMMENT ON COLUMN "delivery_outbox"."dead_at" IS '投递事务 Outbox的死信时间';
COMMENT ON COLUMN "delivery_outbox"."last_replayed_at" IS '投递事务 Outbox的最近重放时间';
COMMENT ON COLUMN "delivery_outbox"."last_replayed_by" IS '投递事务 Outbox的最近重放主体标识';
COMMENT ON COLUMN "delivery_outbox"."created_at" IS '投递事务 Outbox创建时间';
COMMENT ON COLUMN "delivery_outbox"."updated_at" IS '投递事务 Outbox最近更新时间';
COMMENT ON COLUMN "dingtalk_enterprise"."id" IS '钉钉企业记录 ID';
COMMENT ON COLUMN "dingtalk_enterprise"."name" IS '钉钉企业的名称';
COMMENT ON COLUMN "dingtalk_enterprise"."corp_id" IS '钉钉企业的钉钉 Corp ID';
COMMENT ON COLUMN "dingtalk_enterprise"."status" IS '钉钉企业当前生命周期状态';
COMMENT ON COLUMN "dingtalk_enterprise"."verification_event_id" IS '钉钉企业的验证事件ID';
COMMENT ON COLUMN "dingtalk_enterprise"."verified_at" IS '钉钉企业的验证时间';
COMMENT ON COLUMN "dingtalk_enterprise"."revision" IS '钉钉企业乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "dingtalk_enterprise"."created_by" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "dingtalk_enterprise"."created_at" IS '钉钉企业创建时间';
COMMENT ON COLUMN "dingtalk_enterprise"."updated_at" IS '钉钉企业最近更新时间';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."id" IS '钉钉身份应用观测记录 ID';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."external_identity_id" IS '关联的用户外部身份 ID（user_external_identity.id）';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."first_observed_at" IS '钉钉身份应用观测的首次观测时间';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."last_observed_at" IS '钉钉身份应用观测的最近观测时间';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."last_ingress_event_id" IS '关联的渠道入口事件 ID（channel_ingress_event.id）';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."revision" IS '钉钉身份应用观测乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."created_at" IS '钉钉身份应用观测创建时间';
COMMENT ON COLUMN "dingtalk_identity_application_observation"."updated_at" IS '钉钉身份应用观测最近更新时间';
COMMENT ON COLUMN "dingtalk_identity_candidate"."id" IS '钉钉身份候选记录 ID';
COMMENT ON COLUMN "dingtalk_identity_candidate"."tenant_code" IS '钉钉身份候选的租户编码';
COMMENT ON COLUMN "dingtalk_identity_candidate"."external_subject_id" IS '钉钉身份候选的外部主体ID';
COMMENT ON COLUMN "dingtalk_identity_candidate"."display_name" IS '钉钉身份候选的显示名称';
COMMENT ON COLUMN "dingtalk_identity_candidate"."first_seen_at" IS '钉钉身份候选的首次发现时间';
COMMENT ON COLUMN "dingtalk_identity_candidate"."last_seen_at" IS '钉钉身份候选的最近发现时间';
COMMENT ON COLUMN "dingtalk_identity_candidate"."observation_count" IS '钉钉身份候选的观测数量';
COMMENT ON COLUMN "dingtalk_identity_candidate"."revision" IS '钉钉身份候选乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "dingtalk_identity_candidate"."created_at" IS '钉钉身份候选创建时间';
COMMENT ON COLUMN "dingtalk_identity_candidate"."updated_at" IS '钉钉身份候选最近更新时间';
COMMENT ON COLUMN "dingtalk_identity_candidate"."dingtalk_enterprise_id" IS '关联的钉钉企业 ID（dingtalk_enterprise.id）';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."id" IS '钉钉身份候选消息关联记录 ID';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."candidate_id" IS '关联的钉钉身份候选 ID（dingtalk_identity_candidate.id）';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."source_ingress_event_id" IS '关联的渠道入口事件 ID（channel_ingress_event.id）';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."robot_code" IS '钉钉身份候选消息关联的机器人编码';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."conversation_type" IS '钉钉身份候选消息关联的会话类型';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."conversation_id" IS '钉钉身份候选消息关联的会话ID';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."message_kind" IS '钉钉身份候选消息关联的消息类型';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."safe_text" IS '钉钉身份候选消息关联的脱敏后的安全文本';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."text_truncated" IS '钉钉身份候选消息关联文本内容是否已截断';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."attachment_type" IS '钉钉身份候选消息关联的附件类型';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."attachment_name" IS '钉钉身份候选消息关联的附件名称';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."attachment_size" IS '钉钉身份候选消息关联的附件大小';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."occurred_at" IS '钉钉身份候选消息关联的发生时间';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."received_at" IS '钉钉身份候选消息关联的接收时间';
COMMENT ON COLUMN "dingtalk_identity_candidate_message"."created_at" IS '钉钉身份候选消息关联创建时间';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."id" IS '钉钉昵称审计记录 ID';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."external_identity_id" IS '关联的用户外部身份 ID（user_external_identity.id）';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."source_ingress_event_id" IS '关联的渠道入口事件 ID（channel_ingress_event.id）';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."previous_nickname" IS '钉钉昵称审计的变更前昵称';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."current_nickname" IS '钉钉昵称审计的当前昵称';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."observed_at" IS '钉钉昵称审计的观测时间';
COMMENT ON COLUMN "dingtalk_identity_nickname_audit"."created_at" IS '钉钉昵称审计创建时间';
COMMENT ON COLUMN "identity_migration_audit"."id" IS '身份迁移审计记录 ID';
COMMENT ON COLUMN "identity_migration_audit"."legacy_subject_type" IS '身份迁移审计的遗留主体类型';
COMMENT ON COLUMN "identity_migration_audit"."legacy_subject_code" IS '身份迁移审计的遗留主体编码';
COMMENT ON COLUMN "identity_migration_audit"."tenant_code" IS '身份迁移审计的租户编码';
COMMENT ON COLUMN "identity_migration_audit"."internal_user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "identity_migration_audit"."status" IS '身份迁移审计当前生命周期状态';
COMMENT ON COLUMN "identity_migration_audit"."reason" IS '身份迁移审计的原因';
COMMENT ON COLUMN "identity_migration_audit"."created_at" IS '身份迁移审计创建时间';
COMMENT ON COLUMN "integration_connector"."id" IS '连接器 ID';
COMMENT ON COLUMN "integration_connector"."connector_type" IS '连接器类型，例如 internal_api_platform、dingtalk_webhook_robot、email、webhook';
COMMENT ON COLUMN "integration_connector"."name" IS '连接器唯一名称';
COMMENT ON COLUMN "integration_connector"."base_url" IS '连接器基础地址或服务地址，不应包含敏感 token';
COMMENT ON COLUMN "integration_connector"."enabled" IS '连接器是否启用，1 表示启用，0 表示停用';
COMMENT ON COLUMN "integration_connector"."metadata" IS '连接器扩展配置 JSON，不应保存敏感明文';
COMMENT ON COLUMN "integration_connector"."created_at" IS '连接器创建时间';
COMMENT ON COLUMN "integration_connector"."updated_at" IS '连接器最近更新时间';
COMMENT ON COLUMN "integration_connector"."allow_ingress" IS '是否允许该 connector 作为 Channel 入站来源，1 表示允许，0 表示禁止';
COMMENT ON COLUMN "integration_connector"."allow_delivery" IS '是否允许该 connector 作为结果投递出口，1 表示允许，0 表示禁止';
COMMENT ON COLUMN "integration_connector"."secret_ref" IS 'connector 密钥引用，可指向环境变量或受控密钥配置，不应存放明文敏感值';
COMMENT ON COLUMN "integration_connector"."endpoint_ref" IS 'connector 目标地址引用，可指向环境变量或受控配置';
COMMENT ON COLUMN "integration_connector"."host_allowlist" IS '允许投递的目标 host 白名单，多个 host 使用逗号分隔';
COMMENT ON COLUMN "integration_connector"."revision" IS '集成 Connector乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "integration_connector"."deleted" IS '集成 Connector是否已删除';
COMMENT ON COLUMN "integration_connector"."dingtalk_enterprise_id" IS '关联的钉钉企业 ID（dingtalk_enterprise.id）';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."id" IS 'Job 调度切换隔离记录记录 ID';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."source_queue" IS 'Job 调度切换隔离记录的来源队列名称';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."message_digest" IS 'Job 调度切换隔离记录的消息摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."job_id" IS 'Job 调度切换隔离记录的JobID';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."reason_code" IS 'Job 调度切换隔离记录的原因编码';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."observed_at" IS 'Job 调度切换隔离记录的观测时间';
COMMENT ON COLUMN "job_dispatch_cutover_quarantine"."observed_by" IS 'Job 调度切换隔离记录的观测主体标识';
COMMENT ON COLUMN "job_dispatch_outbox"."id" IS 'Job 调度事务 Outbox记录 ID';
COMMENT ON COLUMN "job_dispatch_outbox"."event_key" IS '稳定且唯一的dispatch事件键，用于发布和消费幂等';
COMMENT ON COLUMN "job_dispatch_outbox"."idempotency_key" IS '由Job创建事实派生的稳定幂等键，不接受调用方任意payload';
COMMENT ON COLUMN "job_dispatch_outbox"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "job_dispatch_outbox"."correlation_id" IS 'Job 调度事务 Outbox的关联追踪ID';
COMMENT ON COLUMN "job_dispatch_outbox"."status" IS 'Job 调度事务 Outbox当前生命周期状态';
COMMENT ON COLUMN "job_dispatch_outbox"."attempt_count" IS 'Job 调度事务 Outbox的尝试数量';
COMMENT ON COLUMN "job_dispatch_outbox"."max_attempts" IS 'Job 调度事务 Outbox的最大尝试';
COMMENT ON COLUMN "job_dispatch_outbox"."replay_count" IS 'Job 调度事务 Outbox的重放数量';
COMMENT ON COLUMN "job_dispatch_outbox"."max_replay_count" IS 'Job 调度事务 Outbox的最大重放数量';
COMMENT ON COLUMN "job_dispatch_outbox"."next_attempt_at" IS 'Job 调度事务 Outbox的下次尝试时间';
COMMENT ON COLUMN "job_dispatch_outbox"."claimed_by" IS 'Job 调度事务 Outbox的领取主体标识';
COMMENT ON COLUMN "job_dispatch_outbox"."claimed_at" IS 'Job 调度事务 Outbox的领取时间';
COMMENT ON COLUMN "job_dispatch_outbox"."published_at" IS 'Job 调度事务 Outbox的发布时间';
COMMENT ON COLUMN "job_dispatch_outbox"."dead_at" IS 'Job 调度事务 Outbox的死信时间';
COMMENT ON COLUMN "job_dispatch_outbox"."last_replayed_at" IS 'Job 调度事务 Outbox的最近重放时间';
COMMENT ON COLUMN "job_dispatch_outbox"."last_replayed_by" IS 'Job 调度事务 Outbox的最近重放主体标识';
COMMENT ON COLUMN "job_dispatch_outbox"."last_error_code" IS 'Job 调度事务 Outbox的最近错误编码';
COMMENT ON COLUMN "job_dispatch_outbox"."last_error_summary" IS '有界脱敏发布错误摘要，不包含payload、Token、Secret或连接信息';
COMMENT ON COLUMN "job_dispatch_outbox"."created_at" IS 'Job 调度事务 Outbox创建时间';
COMMENT ON COLUMN "job_dispatch_outbox"."updated_at" IS 'Job 调度事务 Outbox最近更新时间';
COMMENT ON COLUMN "loki_resource_draft_test_session"."id" IS 'Loki 资源草稿测试会话记录 ID';
COMMENT ON COLUMN "loki_resource_draft_test_session"."resource_id" IS '关联的平台工具资源 ID（platform_resource.id）';
COMMENT ON COLUMN "loki_resource_draft_test_session"."draft_id" IS '关联的平台工具资源草稿 ID（platform_resource_draft.id）';
COMMENT ON COLUMN "loki_resource_draft_test_session"."draft_revision" IS 'Loki 资源草稿测试会话的草稿修订';
COMMENT ON COLUMN "loki_resource_draft_test_session"."content_hash" IS 'Loki 资源草稿测试会话的内容哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "loki_resource_draft_test_session"."actor_id" IS 'Loki 资源草稿测试会话的操作主体ID';
COMMENT ON COLUMN "loki_resource_draft_test_session"."status" IS 'Loki 资源草稿测试会话当前生命周期状态';
COMMENT ON COLUMN "loki_resource_draft_test_session"."expires_at" IS 'Loki 资源草稿测试会话的过期时间';
COMMENT ON COLUMN "loki_resource_draft_test_session"."created_at" IS 'Loki 资源草稿测试会话创建时间';
COMMENT ON COLUMN "message_attachment"."id" IS '消息附件记录 ID';
COMMENT ON COLUMN "message_attachment"."message_id" IS '关联的Agent 消息 ID（agent_message.id）';
COMMENT ON COLUMN "message_attachment"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "message_attachment"."ordinal" IS '消息附件的顺序号';
COMMENT ON COLUMN "message_attachment"."media_type" IS '消息附件的媒体类型';
COMMENT ON COLUMN "message_attachment"."file_name" IS '消息附件的文件名称';
COMMENT ON COLUMN "message_attachment"."declared_mime" IS '消息附件的声明MIME';
COMMENT ON COLUMN "message_attachment"."detected_mime" IS '消息附件的检测MIME';
COMMENT ON COLUMN "message_attachment"."declared_size" IS '消息附件的声明大小';
COMMENT ON COLUMN "message_attachment"."size_bytes" IS '消息附件的大小字节';
COMMENT ON COLUMN "message_attachment"."sha256" IS '消息附件的SHA-256 摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "message_attachment"."object_bucket" IS '消息附件的对象存储桶';
COMMENT ON COLUMN "message_attachment"."object_key" IS '消息附件的对象键';
COMMENT ON COLUMN "message_attachment"."status" IS '消息附件当前生命周期状态';
COMMENT ON COLUMN "message_attachment"."failure_code" IS '消息附件的失败编码';
COMMENT ON COLUMN "message_attachment"."retry_count" IS '消息附件的重试数量';
COMMENT ON COLUMN "message_attachment"."source_credential_ciphertext" IS '短期媒体来源凭证密文，下载终态或过期后必须清除';
COMMENT ON COLUMN "message_attachment"."source_credential_type" IS '消息附件的来源凭据类型';
COMMENT ON COLUMN "message_attachment"."source_credential_expires_at" IS '消息附件的来源凭据过期时间';
COMMENT ON COLUMN "message_attachment"."created_at" IS '消息附件创建时间';
COMMENT ON COLUMN "message_attachment"."updated_at" IS '消息附件最近更新时间';
COMMENT ON COLUMN "message_attachment"."finished_at" IS '消息附件的结束时间';
COMMENT ON COLUMN "message_attachment"."expires_at" IS '消息附件的过期时间';
COMMENT ON COLUMN "model_connection"."id" IS '模型连接记录 ID';
COMMENT ON COLUMN "model_connection"."code" IS '模型连接的编码';
COMMENT ON COLUMN "model_connection"."name" IS '模型连接的名称';
COMMENT ON COLUMN "model_connection"."protocol" IS '模型连接的协议';
COMMENT ON COLUMN "model_connection"."current_revision_id" IS '模型连接的当前修订ID';
COMMENT ON COLUMN "model_connection"."status" IS '模型连接当前生命周期状态';
COMMENT ON COLUMN "model_connection"."revision" IS '模型连接乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "model_connection"."created_by" IS '创建模型连接的用户或服务主体标识';
COMMENT ON COLUMN "model_connection"."created_at" IS '模型连接创建时间';
COMMENT ON COLUMN "model_connection"."updated_at" IS '模型连接最近更新时间';
COMMENT ON COLUMN "model_connection_revision"."id" IS '模型连接修订记录 ID';
COMMENT ON COLUMN "model_connection_revision"."connection_id" IS '关联的模型连接 ID（model_connection.id）';
COMMENT ON COLUMN "model_connection_revision"."revision" IS '模型连接修订乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "model_connection_revision"."status" IS '模型连接修订当前生命周期状态';
COMMENT ON COLUMN "model_connection_revision"."config_json" IS '模型连接修订的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "model_connection_revision"."config_hash" IS '模型连接修订的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "model_connection_revision"."api_key_secret_id" IS '内部凭据绑定，管理API、审计、prompt和运行记录不得输出';
COMMENT ON COLUMN "model_connection_revision"."created_by" IS '创建模型连接修订的用户或服务主体标识';
COMMENT ON COLUMN "model_connection_revision"."created_at" IS '模型连接修订创建时间';
COMMENT ON COLUMN "ones_identity_verification_challenge"."id" IS 'ONES 身份验证 Challenge记录 ID';
COMMENT ON COLUMN "ones_identity_verification_challenge"."user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "ones_identity_verification_challenge"."external_user_id" IS 'ONES 身份验证 Challenge的外部用户ID';
COMMENT ON COLUMN "ones_identity_verification_challenge"."display_name" IS 'ONES 身份验证 Challenge的显示名称';
COMMENT ON COLUMN "ones_identity_verification_challenge"."teams_json" IS '本次 ONES 验证返回的去重 Team 候选 JSON，不包含登录 Token';
COMMENT ON COLUMN "ones_identity_verification_challenge"."verified_at" IS 'ONES 身份验证 Challenge的验证时间';
COMMENT ON COLUMN "ones_identity_verification_challenge"."expires_at" IS 'ONES 身份验证 Challenge的过期时间';
COMMENT ON COLUMN "ones_identity_verification_challenge"."status" IS 'ONES 身份验证 Challenge当前生命周期状态';
COMMENT ON COLUMN "ones_identity_verification_challenge"."created_at" IS 'ONES 身份验证 Challenge创建时间';
COMMENT ON COLUMN "ones_identity_verification_challenge"."consumed_at" IS 'Challenge 被成功确认并消费的时间';
COMMENT ON COLUMN "platform_base"."id" IS '业务基地目录记录 ID';
COMMENT ON COLUMN "platform_base"."environment_id" IS '所属环境 ID';
COMMENT ON COLUMN "platform_base"."code" IS '业务基地目录的编码';
COMMENT ON COLUMN "platform_base"."display_name" IS '业务基地目录的显示名称';
COMMENT ON COLUMN "platform_base"."engine" IS '基地默认数据库引擎，例如 mysql、sqlserver、oracle';
COMMENT ON COLUMN "platform_base"."status" IS '业务基地目录当前生命周期状态';
COMMENT ON COLUMN "platform_base"."aliases_json" IS '业务基地目录的别名JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_base"."metadata_json" IS '业务基地目录的元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_base"."revision" IS '业务基地目录乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_base"."created_at" IS '业务基地目录创建时间';
COMMENT ON COLUMN "platform_base"."updated_at" IS '业务基地目录最近更新时间';
COMMENT ON COLUMN "platform_config_audit"."id" IS '平台配置审计记录 ID';
COMMENT ON COLUMN "platform_config_audit"."entity_type" IS '平台配置审计的实体类型';
COMMENT ON COLUMN "platform_config_audit"."entity_id" IS '平台配置审计的实体ID';
COMMENT ON COLUMN "platform_config_audit"."action" IS '平台配置审计的操作';
COMMENT ON COLUMN "platform_config_audit"."actor_id" IS '平台配置审计的操作主体ID';
COMMENT ON COLUMN "platform_config_audit"."before_json" IS '平台配置审计的变更前JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_config_audit"."after_json" IS '平台配置审计的变更后JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_config_audit"."correlation_id" IS '平台配置审计的关联追踪ID';
COMMENT ON COLUMN "platform_config_audit"."created_at" IS '平台配置审计创建时间';
COMMENT ON COLUMN "platform_environment"."id" IS '业务环境目录记录 ID';
COMMENT ON COLUMN "platform_environment"."code" IS '环境唯一编码，例如 sanjiu、mmk';
COMMENT ON COLUMN "platform_environment"."display_name" IS '业务环境目录的显示名称';
COMMENT ON COLUMN "platform_environment"."status" IS '环境状态，enabled 表示启用，disabled 表示停用';
COMMENT ON COLUMN "platform_environment"."aliases_json" IS '环境别名 JSON 数组，用于自然语言寻址';
COMMENT ON COLUMN "platform_environment"."metadata_json" IS '环境扩展元数据 JSON，不保存敏感明文';
COMMENT ON COLUMN "platform_environment"."revision" IS '配置修订号，每次更新递增';
COMMENT ON COLUMN "platform_environment"."created_at" IS '业务环境目录创建时间';
COMMENT ON COLUMN "platform_environment"."updated_at" IS '业务环境目录最近更新时间';
COMMENT ON COLUMN "platform_resource"."id" IS '平台工具资源记录 ID';
COMMENT ON COLUMN "platform_resource"."code" IS '平台工具资源的编码';
COMMENT ON COLUMN "platform_resource"."name" IS '平台工具资源的名称';
COMMENT ON COLUMN "platform_resource"."resource_kind" IS '平台工具资源的资源类型';
COMMENT ON COLUMN "platform_resource"."scope_type" IS '平台工具资源的范围类型';
COMMENT ON COLUMN "platform_resource"."environment_id" IS '关联的业务环境目录 ID（platform_environment.id）';
COMMENT ON COLUMN "platform_resource"."base_id" IS '关联的业务基地目录 ID（platform_base.id）';
COMMENT ON COLUMN "platform_resource"."workshop_id" IS '关联的业务车间目录 ID（platform_workshop.id）';
COMMENT ON COLUMN "platform_resource"."status" IS '平台工具资源当前生命周期状态';
COMMENT ON COLUMN "platform_resource"."revision" IS '平台工具资源乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_resource"."created_by" IS '创建平台工具资源的用户或服务主体标识';
COMMENT ON COLUMN "platform_resource"."created_at" IS '平台工具资源创建时间';
COMMENT ON COLUMN "platform_resource"."updated_at" IS '平台工具资源最近更新时间';
COMMENT ON COLUMN "platform_resource"."placement" IS '平台工具资源的部署位置';
COMMENT ON COLUMN "platform_resource_draft"."id" IS '平台工具资源草稿记录 ID';
COMMENT ON COLUMN "platform_resource_draft"."resource_id" IS '关联的平台工具资源 ID（platform_resource.id）';
COMMENT ON COLUMN "platform_resource_draft"."draft_revision" IS '平台工具资源草稿的草稿修订';
COMMENT ON COLUMN "platform_resource_draft"."provider_type" IS '平台工具资源草稿的提供方类型';
COMMENT ON COLUMN "platform_resource_draft"."config_json" IS '平台工具资源草稿的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_resource_draft"."secret_refs_json" IS '平台工具资源草稿的Secret引用集合JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_resource_draft"."content_hash" IS '平台工具资源草稿的内容哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "platform_resource_draft"."status" IS '平台工具资源草稿当前生命周期状态';
COMMENT ON COLUMN "platform_resource_draft"."created_by" IS '创建平台工具资源草稿的用户或服务主体标识';
COMMENT ON COLUMN "platform_resource_draft"."updated_by" IS '最近更新平台工具资源草稿的用户或服务主体标识';
COMMENT ON COLUMN "platform_resource_draft"."created_at" IS '平台工具资源草稿创建时间';
COMMENT ON COLUMN "platform_resource_draft"."updated_at" IS '平台工具资源草稿最近更新时间';
COMMENT ON COLUMN "platform_resource_revision"."id" IS '平台工具资源修订记录 ID';
COMMENT ON COLUMN "platform_resource_revision"."resource_id" IS '关联的平台工具资源 ID（platform_resource.id）';
COMMENT ON COLUMN "platform_resource_revision"."revision" IS '平台工具资源修订乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_resource_revision"."provider_type" IS '平台工具资源修订的提供方类型';
COMMENT ON COLUMN "platform_resource_revision"."provider_contract_version" IS '平台工具资源修订的提供方契约版本';
COMMENT ON COLUMN "platform_resource_revision"."config_json" IS '平台工具资源修订的配置JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_resource_revision"."secret_refs_json" IS '平台工具资源修订的Secret引用集合JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_resource_revision"."content_hash" IS '平台工具资源修订的内容哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "platform_resource_revision"."verification_id" IS '关联的平台工具资源验证 ID（platform_resource_verification.id）';
COMMENT ON COLUMN "platform_resource_revision"."status" IS '平台工具资源修订当前生命周期状态';
COMMENT ON COLUMN "platform_resource_revision"."published_by" IS '平台工具资源修订的发布主体标识';
COMMENT ON COLUMN "platform_resource_revision"."published_at" IS '平台工具资源修订的发布时间';
COMMENT ON COLUMN "platform_resource_revision"."disabled_by" IS '平台工具资源修订的禁用主体标识';
COMMENT ON COLUMN "platform_resource_revision"."disabled_at" IS '平台工具资源修订的禁用时间';
COMMENT ON COLUMN "platform_resource_revision"."archived_by" IS '平台工具资源修订的归档主体标识';
COMMENT ON COLUMN "platform_resource_revision"."archived_at" IS '平台工具资源修订的归档时间';
COMMENT ON COLUMN "platform_resource_verification"."id" IS '平台工具资源验证记录 ID';
COMMENT ON COLUMN "platform_resource_verification"."resource_id" IS '关联的平台工具资源 ID（platform_resource.id）';
COMMENT ON COLUMN "platform_resource_verification"."draft_id" IS '关联的平台工具资源草稿 ID（platform_resource_draft.id）';
COMMENT ON COLUMN "platform_resource_verification"."draft_revision" IS '平台工具资源验证的草稿修订';
COMMENT ON COLUMN "platform_resource_verification"."content_hash" IS '平台工具资源验证的内容哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "platform_resource_verification"."status" IS '平台工具资源验证当前生命周期状态';
COMMENT ON COLUMN "platform_resource_verification"."provider_contract_version" IS '平台工具资源验证的提供方契约版本';
COMMENT ON COLUMN "platform_resource_verification"."checks_json" IS '平台工具资源验证的检查结果JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_resource_verification"."safe_error_summary" IS '平台工具资源验证的安全错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "platform_resource_verification"."verified_by" IS '平台工具资源验证的验证主体标识';
COMMENT ON COLUMN "platform_resource_verification"."verified_at" IS '平台工具资源验证的验证时间';
COMMENT ON COLUMN "platform_runtime_config_definition"."id" IS '平台运行配置定义记录 ID';
COMMENT ON COLUMN "platform_runtime_config_definition"."key" IS '平台运行配置定义的键';
COMMENT ON COLUMN "platform_runtime_config_definition"."value_type" IS '平台运行配置定义的值类型';
COMMENT ON COLUMN "platform_runtime_config_definition"."default_json" IS '平台运行配置定义的默认值JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_runtime_config_definition"."sensitive" IS '平台运行配置定义是否属于敏感配置';
COMMENT ON COLUMN "platform_runtime_config_definition"."bootstrap_only" IS '1 表示只能由部署环境提供，不允许 DB 普通配置覆盖';
COMMENT ON COLUMN "platform_runtime_config_definition"."service_names_json" IS '平台运行配置定义的服务名称集合JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_runtime_config_definition"."description" IS '平台运行配置定义的描述';
COMMENT ON COLUMN "platform_runtime_config_definition"."status" IS '平台运行配置定义当前生命周期状态';
COMMENT ON COLUMN "platform_runtime_config_definition"."revision" IS '平台运行配置定义乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_runtime_config_definition"."created_at" IS '平台运行配置定义创建时间';
COMMENT ON COLUMN "platform_runtime_config_definition"."updated_at" IS '平台运行配置定义最近更新时间';
COMMENT ON COLUMN "platform_runtime_config_value"."id" IS '平台运行配置值记录 ID';
COMMENT ON COLUMN "platform_runtime_config_value"."definition_id" IS '关联的平台运行配置定义 ID（platform_runtime_config_definition.id）';
COMMENT ON COLUMN "platform_runtime_config_value"."key" IS '平台运行配置值的键';
COMMENT ON COLUMN "platform_runtime_config_value"."scope_type" IS '平台运行配置值的范围类型';
COMMENT ON COLUMN "platform_runtime_config_value"."scope_code" IS '平台运行配置值的范围编码';
COMMENT ON COLUMN "platform_runtime_config_value"."service_name" IS '平台运行配置值的服务名称';
COMMENT ON COLUMN "platform_runtime_config_value"."value_json" IS '平台运行配置值的值JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_runtime_config_value"."secret_ref" IS '敏感配置引用，只允许 secret://platform、env、vault、kms 等引用，不保存明文';
COMMENT ON COLUMN "platform_runtime_config_value"."status" IS '平台运行配置值当前生命周期状态';
COMMENT ON COLUMN "platform_runtime_config_value"."revision" IS '平台运行配置值乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_runtime_config_value"."created_at" IS '平台运行配置值创建时间';
COMMENT ON COLUMN "platform_runtime_config_value"."updated_at" IS '平台运行配置值最近更新时间';
COMMENT ON COLUMN "platform_secret"."id" IS '平台 Secret记录 ID';
COMMENT ON COLUMN "platform_secret"."code" IS '平台 Secret的编码';
COMMENT ON COLUMN "platform_secret"."provider" IS '平台 Secret的提供方';
COMMENT ON COLUMN "platform_secret"."ref" IS '稳定密钥引用，格式 secret://platform/<code>';
COMMENT ON COLUMN "platform_secret"."purpose" IS '平台 Secret的用途';
COMMENT ON COLUMN "platform_secret"."status" IS '平台 Secret当前生命周期状态';
COMMENT ON COLUMN "platform_secret"."active_version" IS '平台 Secret的生效版本';
COMMENT ON COLUMN "platform_secret"."masked_summary" IS '密钥脱敏摘要，不可用于还原明文';
COMMENT ON COLUMN "platform_secret"."metadata_json" IS '平台 Secret的元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_secret"."revision" IS '平台 Secret乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_secret"."created_at" IS '平台 Secret创建时间';
COMMENT ON COLUMN "platform_secret"."updated_at" IS '平台 Secret最近更新时间';
COMMENT ON COLUMN "platform_secret_change_event"."id" IS '平台 Secret 变更事件记录 ID';
COMMENT ON COLUMN "platform_secret_change_event"."secret_id" IS '关联的平台 Secret ID（platform_secret.id）';
COMMENT ON COLUMN "platform_secret_change_event"."secret_revision" IS '平台 Secret 变更事件的Secret修订';
COMMENT ON COLUMN "platform_secret_change_event"."action" IS '平台 Secret 变更事件的操作';
COMMENT ON COLUMN "platform_secret_change_event"."status" IS '平台 Secret 变更事件当前生命周期状态';
COMMENT ON COLUMN "platform_secret_change_event"."attempt_count" IS '平台 Secret 变更事件的尝试数量';
COMMENT ON COLUMN "platform_secret_change_event"."claimed_at" IS '平台 Secret 变更事件的领取时间';
COMMENT ON COLUMN "platform_secret_change_event"."error_summary" IS '固定安全错误摘要，不包含凭据、密文或资源连接参数';
COMMENT ON COLUMN "platform_secret_change_event"."created_at" IS '平台 Secret 变更事件创建时间';
COMMENT ON COLUMN "platform_secret_change_event"."processed_at" IS '平台 Secret 变更事件的处理时间';
COMMENT ON COLUMN "platform_secret_reference"."id" IS '平台 Secret 外部引用记录 ID';
COMMENT ON COLUMN "platform_secret_reference"."code" IS '平台 Secret 外部引用的编码';
COMMENT ON COLUMN "platform_secret_reference"."provider" IS '密钥提供方，例如 env、vault、kms';
COMMENT ON COLUMN "platform_secret_reference"."ref" IS '密钥引用字符串，例如 env:ORDER_DB_PASSWORD';
COMMENT ON COLUMN "platform_secret_reference"."purpose" IS '平台 Secret 外部引用的用途';
COMMENT ON COLUMN "platform_secret_reference"."status" IS '平台 Secret 外部引用当前生命周期状态';
COMMENT ON COLUMN "platform_secret_reference"."metadata_json" IS '平台 Secret 外部引用的元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_secret_reference"."revision" IS '平台 Secret 外部引用乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_secret_reference"."created_at" IS '平台 Secret 外部引用创建时间';
COMMENT ON COLUMN "platform_secret_reference"."updated_at" IS '平台 Secret 外部引用最近更新时间';
COMMENT ON COLUMN "platform_secret_version"."id" IS '平台 Secret 密文版本记录 ID';
COMMENT ON COLUMN "platform_secret_version"."secret_id" IS '关联的平台 Secret ID（platform_secret.id）';
COMMENT ON COLUMN "platform_secret_version"."version" IS '平台 Secret 密文版本的版本';
COMMENT ON COLUMN "platform_secret_version"."ciphertext" IS '加密后的密钥值，API、审计和 prompt 不得输出';
COMMENT ON COLUMN "platform_secret_version"."nonce" IS '平台 Secret 密文使用的 AES-GCM Nonce';
COMMENT ON COLUMN "platform_secret_version"."key_id" IS '平台 Secret 密文版本的键ID';
COMMENT ON COLUMN "platform_secret_version"."algorithm" IS '平台 Secret 密文版本的算法';
COMMENT ON COLUMN "platform_secret_version"."status" IS '平台 Secret 密文版本当前生命周期状态';
COMMENT ON COLUMN "platform_secret_version"."created_by" IS '创建平台 Secret 密文版本的用户或服务主体标识';
COMMENT ON COLUMN "platform_secret_version"."created_at" IS '平台 Secret 密文版本创建时间';
COMMENT ON COLUMN "platform_workshop"."id" IS '业务车间目录记录 ID';
COMMENT ON COLUMN "platform_workshop"."base_id" IS '关联的业务基地目录 ID（platform_base.id）';
COMMENT ON COLUMN "platform_workshop"."code" IS '业务车间目录的编码';
COMMENT ON COLUMN "platform_workshop"."display_name" IS '业务车间目录的显示名称';
COMMENT ON COLUMN "platform_workshop"."table_prefix" IS '车间表名前缀，用于只读 SQL 安全约束';
COMMENT ON COLUMN "platform_workshop"."redis_key_prefix" IS '车间 Redis key 前缀，用于只读 Redis 安全约束';
COMMENT ON COLUMN "platform_workshop"."loki_labels_json" IS '车间 Loki label 约束 JSON';
COMMENT ON COLUMN "platform_workshop"."status" IS '业务车间目录当前生命周期状态';
COMMENT ON COLUMN "platform_workshop"."aliases_json" IS '业务车间目录的别名JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_workshop"."metadata_json" IS '业务车间目录的元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "platform_workshop"."revision" IS '业务车间目录乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "platform_workshop"."created_at" IS '业务车间目录创建时间';
COMMENT ON COLUMN "platform_workshop"."updated_at" IS '业务车间目录最近更新时间';
COMMENT ON COLUMN "rbac_role"."id" IS 'RBAC 角色记录 ID';
COMMENT ON COLUMN "rbac_role"."code" IS 'RBAC 角色的编码';
COMMENT ON COLUMN "rbac_role"."name" IS 'RBAC 角色的名称';
COMMENT ON COLUMN "rbac_role"."description" IS 'RBAC 角色的描述';
COMMENT ON COLUMN "rbac_role"."status" IS 'RBAC 角色当前生命周期状态';
COMMENT ON COLUMN "rbac_role"."revision" IS 'RBAC 角色乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "rbac_role"."created_at" IS 'RBAC 角色创建时间';
COMMENT ON COLUMN "rbac_role"."updated_at" IS 'RBAC 角色最近更新时间';
COMMENT ON COLUMN "rbac_role"."origin" IS 'RBAC 角色的来源';
COMMENT ON COLUMN "rbac_role"."protected" IS 'RBAC 角色是否属于受保护对象';
COMMENT ON COLUMN "rbac_role"."purpose_tags_json" IS 'RBAC 角色的用途标签JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "rbac_role"."metadata_revision" IS 'RBAC 角色的元数据修订';
COMMENT ON COLUMN "rbac_role"."admin_revision" IS 'RBAC 角色的管理修订';
COMMENT ON COLUMN "rbac_role"."business_revision" IS 'RBAC 角色的业务修订';
COMMENT ON COLUMN "rbac_role"."membership_revision" IS 'RBAC 角色的成员关系修订';
COMMENT ON COLUMN "rbac_role_admin_capability"."id" IS '角色管理能力授权记录 ID';
COMMENT ON COLUMN "rbac_role_admin_capability"."role_id" IS '关联的RBAC 角色 ID（rbac_role.id）';
COMMENT ON COLUMN "rbac_role_admin_capability"."capability_code" IS '角色管理能力授权的能力编码';
COMMENT ON COLUMN "rbac_role_admin_capability"."resource_type" IS '角色管理能力授权的资源类型';
COMMENT ON COLUMN "rbac_role_admin_capability"."resource_code" IS '角色管理能力授权的资源编码';
COMMENT ON COLUMN "rbac_role_admin_capability"."status" IS '角色管理能力授权当前生命周期状态';
COMMENT ON COLUMN "rbac_role_admin_capability"."created_at" IS '角色管理能力授权创建时间';
COMMENT ON COLUMN "rbac_role_admin_capability"."updated_at" IS '角色管理能力授权最近更新时间';
COMMENT ON COLUMN "rbac_role_application_access"."id" IS '角色应用访问授权记录 ID';
COMMENT ON COLUMN "rbac_role_application_access"."role_id" IS '关联的RBAC 角色 ID（rbac_role.id）';
COMMENT ON COLUMN "rbac_role_application_access"."application_id" IS '关联的业务应用 ID（business_application.id）';
COMMENT ON COLUMN "rbac_role_application_access"."status" IS '角色应用访问授权当前生命周期状态';
COMMENT ON COLUMN "rbac_role_application_access"."revision" IS '角色应用访问授权乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "rbac_role_application_access"."created_at" IS '角色应用访问授权创建时间';
COMMENT ON COLUMN "rbac_role_application_access"."updated_at" IS '角色应用访问授权最近更新时间';
COMMENT ON COLUMN "rbac_role_application_mcp_tool"."id" IS '角色应用 MCP 工具授权记录 ID';
COMMENT ON COLUMN "rbac_role_application_mcp_tool"."application_access_id" IS '关联的角色应用访问授权 ID（rbac_role_application_access.id）';
COMMENT ON COLUMN "rbac_role_application_mcp_tool"."tool_identifier" IS '角色应用 MCP 工具授权的工具标识';
COMMENT ON COLUMN "rbac_role_application_mcp_tool"."created_at" IS '角色应用 MCP 工具授权创建时间';
COMMENT ON COLUMN "rbac_role_application_scope"."id" IS '角色应用数据范围记录 ID';
COMMENT ON COLUMN "rbac_role_application_scope"."application_access_id" IS '关联的角色应用访问授权 ID（rbac_role_application_access.id）';
COMMENT ON COLUMN "rbac_role_application_scope"."environment_id" IS '关联的业务环境目录 ID（platform_environment.id）';
COMMENT ON COLUMN "rbac_role_application_scope"."base_id" IS '关联的业务基地目录 ID（platform_base.id）';
COMMENT ON COLUMN "rbac_role_application_scope"."workshop_id" IS '关联的业务车间目录 ID（platform_workshop.id）';
COMMENT ON COLUMN "rbac_role_application_scope"."scope_key" IS '角色应用数据范围的范围键';
COMMENT ON COLUMN "rbac_role_application_scope"."created_at" IS '角色应用数据范围创建时间';
COMMENT ON COLUMN "rbac_user_role"."id" IS '用户角色成员关系记录 ID';
COMMENT ON COLUMN "rbac_user_role"."user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "rbac_user_role"."role_id" IS '关联的RBAC 角色 ID（rbac_role.id）';
COMMENT ON COLUMN "rbac_user_role"."status" IS '用户角色成员关系当前生命周期状态';
COMMENT ON COLUMN "rbac_user_role"."revision" IS '用户角色成员关系乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "rbac_user_role"."created_at" IS '用户角色成员关系创建时间';
COMMENT ON COLUMN "rbac_user_role"."updated_at" IS '用户角色成员关系最近更新时间';
COMMENT ON COLUMN "rbac_user_role"."expires_at" IS '用户角色成员关系的过期时间';
COMMENT ON COLUMN "rbac_user_role"."assigned_by" IS '用户角色成员关系的分配主体标识';
COMMENT ON COLUMN "rbac_user_role"."assignment_source" IS '用户角色成员关系的分配来源来源';
COMMENT ON COLUMN "resource_reset_operation"."id" IS '工具资源重置操作记录 ID';
COMMENT ON COLUMN "resource_reset_operation"."status" IS '工具资源重置操作当前生命周期状态';
COMMENT ON COLUMN "resource_reset_operation"."target_kinds_json" IS '工具资源重置操作的目标类型集合JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "resource_reset_operation"."inventory_digest" IS '工具资源重置操作的目标清单摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "resource_reset_operation"."database_fingerprint" IS '工具资源重置操作的数据库结构指纹，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "resource_reset_operation"."backup_reference" IS '工具资源重置操作的备份引用';
COMMENT ON COLUMN "resource_reset_operation"."impact_summary_json" IS '工具资源重置操作的影响摘要JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "resource_reset_operation"."prepared_by" IS '工具资源重置操作的准备主体标识';
COMMENT ON COLUMN "resource_reset_operation"."prepared_at" IS '工具资源重置操作的准备时间';
COMMENT ON COLUMN "resource_reset_operation"."confirmed_by" IS '工具资源重置操作的确认主体标识';
COMMENT ON COLUMN "resource_reset_operation"."confirmed_at" IS '工具资源重置操作的确认时间';
COMMENT ON COLUMN "resource_reset_operation"."applied_by" IS '工具资源重置操作的应用主体标识';
COMMENT ON COLUMN "resource_reset_operation"."applied_at" IS '工具资源重置操作的应用时间';
COMMENT ON COLUMN "resource_reset_operation"."verified_by" IS '工具资源重置操作的验证主体标识';
COMMENT ON COLUMN "resource_reset_operation"."verified_at" IS '工具资源重置操作的验证时间';
COMMENT ON COLUMN "resource_reset_operation"."correlation_id" IS '工具资源重置操作的关联追踪ID';
COMMENT ON COLUMN "resource_reset_operation"."error_code" IS '工具资源重置操作的错误编码';
COMMENT ON COLUMN "resource_reset_operation"."error_summary" IS '工具资源重置操作的错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "resource_reset_operation"."created_at" IS '工具资源重置操作创建时间';
COMMENT ON COLUMN "resource_reset_operation"."updated_at" IS '工具资源重置操作最近更新时间';
COMMENT ON COLUMN "resource_reset_target"."operation_id" IS '关联的工具资源重置操作 ID（resource_reset_operation.id）';
COMMENT ON COLUMN "resource_reset_target"."target_type" IS '工具资源重置目标的目标类型';
COMMENT ON COLUMN "resource_reset_target"."target_id" IS '工具资源重置目标的目标ID';
COMMENT ON COLUMN "resource_reset_target"."target_revision" IS '工具资源重置目标的目标修订';
COMMENT ON COLUMN "resource_reset_target"."target_code" IS '工具资源重置目标的目标编码';
COMMENT ON COLUMN "resource_reset_target"."action" IS '工具资源重置目标的操作';
COMMENT ON COLUMN "resource_reset_target"."item_digest" IS '工具资源重置目标的目标项目摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "resource_reset_target"."apply_status" IS '工具资源重置目标的执行状态';
COMMENT ON COLUMN "resource_reset_target"."error_code" IS '工具资源重置目标的错误编码';
COMMENT ON COLUMN "resource_reset_target"."error_summary" IS '工具资源重置目标的错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "user_external_identity"."id" IS '用户外部身份记录 ID';
COMMENT ON COLUMN "user_external_identity"."user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "user_external_identity"."provider" IS '用户外部身份的提供方';
COMMENT ON COLUMN "user_external_identity"."tenant_code" IS '用户外部身份的租户编码';
COMMENT ON COLUMN "user_external_identity"."external_subject_id" IS '用户外部身份的外部主体ID';
COMMENT ON COLUMN "user_external_identity"."connector_id" IS '用户外部身份的ConnectorID';
COMMENT ON COLUMN "user_external_identity"."union_id" IS '用户外部身份的钉钉 Union ID';
COMMENT ON COLUMN "user_external_identity"."open_id" IS '用户外部身份的钉钉 Open ID';
COMMENT ON COLUMN "user_external_identity"."display_name" IS '用户外部身份的显示名称';
COMMENT ON COLUMN "user_external_identity"."status" IS '用户外部身份当前生命周期状态';
COMMENT ON COLUMN "user_external_identity"."verified_at" IS '用户外部身份的验证时间';
COMMENT ON COLUMN "user_external_identity"."last_seen_at" IS '用户外部身份的最近发现时间';
COMMENT ON COLUMN "user_external_identity"."metadata_json" IS '用户外部身份的元数据JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "user_external_identity"."revision" IS '用户外部身份乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "user_external_identity"."created_at" IS '用户外部身份创建时间';
COMMENT ON COLUMN "user_external_identity"."updated_at" IS '用户外部身份最近更新时间';
COMMENT ON COLUMN "user_external_identity"."dingtalk_enterprise_id" IS '关联的钉钉企业 ID（dingtalk_enterprise.id）';
COMMENT ON COLUMN "user_external_identity"."display_name_observed_at" IS '用户外部身份的显示名称观测时间';
COMMENT ON COLUMN "user_external_identity"."display_name_event_id" IS '用户外部身份的显示名称事件ID';
COMMENT ON COLUMN "user_external_identity"."display_name_source_connector_id" IS '用户外部身份的显示名称来源ConnectorID';
COMMENT ON COLUMN "user_password_credential"."user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "user_password_credential"."password_hash" IS '使用受支持算法生成的密码哈希，不保存明文密码';
COMMENT ON COLUMN "user_password_credential"."revision" IS '用户密码凭据乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "user_password_credential"."password_changed_at" IS '用户密码凭据的密码变更时间';
COMMENT ON COLUMN "user_password_credential"."created_at" IS '用户密码凭据创建时间';
COMMENT ON COLUMN "user_password_credential"."updated_at" IS '用户密码凭据最近更新时间';
COMMENT ON COLUMN "user_session"."id" IS 'Web 用户会话记录 ID';
COMMENT ON COLUMN "user_session"."user_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "user_session"."token_hash" IS 'Web Session Token 的哈希摘要，不保存原始 Token';
COMMENT ON COLUMN "user_session"."csrf_hash" IS 'CSRF Token 的哈希摘要，不保存原始 Token';
COMMENT ON COLUMN "user_session"."status" IS 'Web 用户会话当前生命周期状态';
COMMENT ON COLUMN "user_session"."created_at" IS 'Web 用户会话创建时间';
COMMENT ON COLUMN "user_session"."last_seen_at" IS 'Web 用户会话的最近发现时间';
COMMENT ON COLUMN "user_session"."idle_expires_at" IS 'Web 用户会话的空闲过期时间';
COMMENT ON COLUMN "user_session"."absolute_expires_at" IS 'Web 用户会话的绝对过期时间';
COMMENT ON COLUMN "user_session"."revoked_at" IS 'Web 用户会话的撤销时间';
COMMENT ON COLUMN "user_session"."user_agent_summary" IS 'Web 用户会话的客户端 User-Agent 安全摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "user_session"."remote_address_summary" IS 'Web 用户会话的远端地址安全摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "webhook_event"."id" IS 'Webhook 入口事件记录 ID';
COMMENT ON COLUMN "webhook_event"."trigger_id" IS '关联的Webhook 触发器定义 ID（webhook_trigger_definition.id）';
COMMENT ON COLUMN "webhook_event"."trigger_publication_id" IS '关联的Webhook 触发器发布 ID（webhook_trigger_publication.id）';
COMMENT ON COLUMN "webhook_event"."agent_publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "webhook_event"."service_account_id" IS '关联的平台用户 ID（app_user.id）';
COMMENT ON COLUMN "webhook_event"."external_event_id" IS 'Webhook 入口事件的外部事件ID';
COMMENT ON COLUMN "webhook_event"."dedup_key" IS 'Webhook 入口事件的去重键';
COMMENT ON COLUMN "webhook_event"."payload_hash" IS '原始请求体SHA-256，仅用于审计和去重辅助，不保存正文';
COMMENT ON COLUMN "webhook_event"."request_bytes" IS 'Webhook 入口事件的请求字节';
COMMENT ON COLUMN "webhook_event"."safe_summary_json" IS 'Webhook 入口事件的安全摘要JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "webhook_event"."normalized_event_json" IS '有界标准化Channel输入，不包含认证header、secret或完整原始payload';
COMMENT ON COLUMN "webhook_event"."correlation_id" IS 'Webhook 入口事件的关联追踪ID';
COMMENT ON COLUMN "webhook_event"."job_id" IS '关联的Agent Job ID（agent_job.id）';
COMMENT ON COLUMN "webhook_event"."status" IS 'Webhook 入口事件当前生命周期状态';
COMMENT ON COLUMN "webhook_event"."auth_result" IS 'Webhook 入口事件的认证结果';
COMMENT ON COLUMN "webhook_event"."filter_result" IS 'Webhook 入口事件的过滤结果';
COMMENT ON COLUMN "webhook_event"."error_code" IS 'Webhook 入口事件的错误编码';
COMMENT ON COLUMN "webhook_event"."error_summary" IS 'Webhook 入口事件的错误摘要，必须有界且不包含 Secret 明文';
COMMENT ON COLUMN "webhook_event"."received_at" IS 'Webhook 入口事件的接收时间';
COMMENT ON COLUMN "webhook_event"."dispatched_at" IS 'Webhook 入口事件的派发时间';
COMMENT ON COLUMN "webhook_event"."completed_at" IS 'Webhook 入口事件的完成时间';
COMMENT ON COLUMN "webhook_outbox"."id" IS 'Webhook 事务 Outbox记录 ID';
COMMENT ON COLUMN "webhook_outbox"."webhook_event_id" IS '关联的Webhook 入口事件 ID（webhook_event.id）';
COMMENT ON COLUMN "webhook_outbox"."correlation_id" IS 'Webhook 事务 Outbox的关联追踪ID';
COMMENT ON COLUMN "webhook_outbox"."status" IS 'Webhook 事务 Outbox当前生命周期状态';
COMMENT ON COLUMN "webhook_outbox"."attempt_count" IS 'Webhook 事务 Outbox的尝试数量';
COMMENT ON COLUMN "webhook_outbox"."next_attempt_at" IS 'Webhook 事务 Outbox的下次尝试时间';
COMMENT ON COLUMN "webhook_outbox"."claimed_by" IS 'Webhook 事务 Outbox的领取主体标识';
COMMENT ON COLUMN "webhook_outbox"."claimed_at" IS 'Webhook 事务 Outbox的领取时间';
COMMENT ON COLUMN "webhook_outbox"."last_error_summary" IS '不包含payload、凭证或连接信息的发布错误摘要';
COMMENT ON COLUMN "webhook_outbox"."created_at" IS 'Webhook 事务 Outbox创建时间';
COMMENT ON COLUMN "webhook_outbox"."published_at" IS 'Webhook 事务 Outbox的发布时间';
COMMENT ON COLUMN "webhook_outbox"."updated_at" IS 'Webhook 事务 Outbox最近更新时间';
COMMENT ON COLUMN "webhook_replay_nonce"."trigger_id" IS '关联的Webhook 触发器定义 ID（webhook_trigger_definition.id）';
COMMENT ON COLUMN "webhook_replay_nonce"."nonce_hash" IS 'Webhook 防重放 Nonce 的哈希摘要，不保存原始 Nonce';
COMMENT ON COLUMN "webhook_replay_nonce"."expires_at" IS 'Webhook 防重放 Nonce的过期时间';
COMMENT ON COLUMN "webhook_replay_nonce"."created_at" IS 'Webhook 防重放 Nonce创建时间';
COMMENT ON COLUMN "webhook_trigger_definition"."id" IS 'Webhook 触发器定义记录 ID';
COMMENT ON COLUMN "webhook_trigger_definition"."code" IS 'Webhook 触发器定义的编码';
COMMENT ON COLUMN "webhook_trigger_definition"."name" IS 'Webhook 触发器定义的名称';
COMMENT ON COLUMN "webhook_trigger_definition"."trigger_type" IS 'Webhook 触发器定义的触发器类型';
COMMENT ON COLUMN "webhook_trigger_definition"."public_id" IS '不可预测且可轮换的公共入口标识，不是认证凭证';
COMMENT ON COLUMN "webhook_trigger_definition"."connector_id" IS '关联的集成 Connector ID（integration_connector.id）';
COMMENT ON COLUMN "webhook_trigger_definition"."service_account_id" IS 'Webhook运行时统一RBAC主体，必须是service账号';
COMMENT ON COLUMN "webhook_trigger_definition"."status" IS 'Webhook 触发器定义当前生命周期状态';
COMMENT ON COLUMN "webhook_trigger_definition"."current_publication_id" IS 'Webhook 触发器定义的当前发布ID';
COMMENT ON COLUMN "webhook_trigger_definition"."revision" IS 'Webhook 触发器定义乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "webhook_trigger_definition"."created_by" IS '创建Webhook 触发器定义的用户或服务主体标识';
COMMENT ON COLUMN "webhook_trigger_definition"."created_at" IS 'Webhook 触发器定义创建时间';
COMMENT ON COLUMN "webhook_trigger_definition"."updated_at" IS 'Webhook 触发器定义最近更新时间';
COMMENT ON COLUMN "webhook_trigger_publication"."id" IS 'Webhook 触发器发布记录 ID';
COMMENT ON COLUMN "webhook_trigger_publication"."trigger_id" IS '关联的Webhook 触发器定义 ID（webhook_trigger_definition.id）';
COMMENT ON COLUMN "webhook_trigger_publication"."revision_id" IS '关联的Webhook 触发器修订 ID（webhook_trigger_revision.id）';
COMMENT ON COLUMN "webhook_trigger_publication"."revision" IS 'Webhook 触发器发布乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "webhook_trigger_publication"."schema_version" IS 'Webhook 触发器发布的Schema版本';
COMMENT ON COLUMN "webhook_trigger_publication"."snapshot_json" IS '固定认证引用、映射、routing、Agent和Delivery语义的不可变JSON';
COMMENT ON COLUMN "webhook_trigger_publication"."config_hash" IS 'Webhook 触发器发布的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "webhook_trigger_publication"."agent_publication_id" IS '关联的Agent 发布 ID（agent_publication.id）';
COMMENT ON COLUMN "webhook_trigger_publication"."agent_revision" IS 'Webhook 触发器发布的Agent修订';
COMMENT ON COLUMN "webhook_trigger_publication"."agent_config_hash" IS 'Webhook 触发器发布的Agent配置哈希，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "webhook_trigger_publication"."status" IS 'Webhook 触发器发布当前生命周期状态';
COMMENT ON COLUMN "webhook_trigger_publication"."published_by" IS 'Webhook 触发器发布的发布主体标识';
COMMENT ON COLUMN "webhook_trigger_publication"."published_at" IS 'Webhook 触发器发布的发布时间';
COMMENT ON COLUMN "webhook_trigger_revision"."id" IS 'Webhook 触发器修订记录 ID';
COMMENT ON COLUMN "webhook_trigger_revision"."trigger_id" IS '关联的Webhook 触发器定义 ID（webhook_trigger_definition.id）';
COMMENT ON COLUMN "webhook_trigger_revision"."revision" IS 'Webhook 触发器修订乐观并发修订号，内容更新时递增';
COMMENT ON COLUMN "webhook_trigger_revision"."status" IS 'Webhook 触发器修订当前生命周期状态';
COMMENT ON COLUMN "webhook_trigger_revision"."schema_version" IS 'Webhook 触发器修订的Schema版本';
COMMENT ON COLUMN "webhook_trigger_revision"."config_json" IS '不含secret value和测试payload的类型化配置JSON';
COMMENT ON COLUMN "webhook_trigger_revision"."config_hash" IS 'Webhook 触发器修订的配置哈希摘要，用于完整性校验、幂等判断或安全比对';
COMMENT ON COLUMN "webhook_trigger_revision"."validation_json" IS 'Webhook 触发器修订的校验JSON，保存有界结构化数据且不得包含未声明的敏感明文';
COMMENT ON COLUMN "webhook_trigger_revision"."created_by" IS '创建Webhook 触发器修订的用户或服务主体标识';
COMMENT ON COLUMN "webhook_trigger_revision"."created_at" IS 'Webhook 触发器修订创建时间';
COMMENT ON COLUMN "webhook_trigger_revision"."updated_at" IS 'Webhook 触发器修订最近更新时间';
