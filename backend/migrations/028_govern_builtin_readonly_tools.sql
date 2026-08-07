CREATE TABLE IF NOT EXISTS builtin_tool_manifest_projection (
  tool_identifier TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  tool_semantic_version TEXT NOT NULL,
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  manifest_json TEXT NOT NULL,
  verifier_plan_json TEXT NOT NULL,
  verifier_version TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY(tool_identifier, handler_version),
  UNIQUE(tool_identifier, handler_version, implementation_digest),
  UNIQUE(
    tool_identifier,
    handler_version,
    implementation_digest,
    tool_semantic_version,
    manifest_hash,
    public_schema_hash
  ),
  CHECK (length(trim(tool_identifier)) > 0),
  CHECK (length(trim(handler_version)) > 0),
  CHECK (length(trim(tool_semantic_version)) > 0),
  CHECK (length(trim(verifier_version)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_manifest_digest
  ON builtin_tool_manifest_projection(tool_identifier, implementation_digest);

CREATE TABLE IF NOT EXISTS builtin_tool_installation (
  tool_identifier TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  installation_status TEXT NOT NULL DEFAULT 'INSTALLED'
    CHECK (installation_status IN ('INSTALLED', 'MISSING', 'DRIFTED')),
  safe_health_summary TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(tool_identifier, handler_version),
  UNIQUE(tool_identifier, handler_version, implementation_digest),
  FOREIGN KEY(tool_identifier, handler_version)
    REFERENCES builtin_tool_manifest_projection(
      tool_identifier,
      handler_version
    )
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_installation_status
  ON builtin_tool_installation(installation_status, tool_identifier);

CREATE TABLE IF NOT EXISTS builtin_tool_verification (
  id TEXT PRIMARY KEY,
  tool_identifier TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  verifier_version TEXT NOT NULL,
  normalized_input_hash TEXT NOT NULL
    CHECK (length(normalized_input_hash) = 64),
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(
    tool_identifier,
    handler_version,
    implementation_digest,
    verifier_version,
    normalized_input_hash
  ),
  UNIQUE(id, tool_identifier, handler_version, implementation_digest),
  FOREIGN KEY(tool_identifier, handler_version, implementation_digest)
    REFERENCES builtin_tool_installation(
      tool_identifier,
      handler_version,
      implementation_digest
    )
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_verification_lookup
  ON builtin_tool_verification(
    tool_identifier,
    handler_version,
    implementation_digest,
    status,
    verified_at
  );

CREATE TABLE IF NOT EXISTS builtin_tool_release (
  id TEXT PRIMARY KEY,
  tool_identifier TEXT NOT NULL,
  release_revision INTEGER NOT NULL CHECK (release_revision >= 1),
  tool_semantic_version TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  verification_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DEPRECATED', 'DISABLED', 'ARCHIVED')),
  idempotency_key TEXT NOT NULL UNIQUE,
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  deprecated_by TEXT NOT NULL DEFAULT '',
  deprecated_at TEXT,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(tool_identifier, release_revision),
  UNIQUE(tool_identifier, handler_version, implementation_digest),
  UNIQUE(
    id,
    tool_identifier,
    handler_version,
    implementation_digest,
    public_schema_hash
  ),
  FOREIGN KEY(
    tool_identifier,
    handler_version,
    implementation_digest,
    tool_semantic_version,
    manifest_hash,
    public_schema_hash
  ) REFERENCES builtin_tool_manifest_projection(
    tool_identifier,
    handler_version,
    implementation_digest,
    tool_semantic_version,
    manifest_hash,
    public_schema_hash
  ),
  FOREIGN KEY(
    verification_id,
    tool_identifier,
    handler_version,
    implementation_digest
  ) REFERENCES builtin_tool_verification(
    id,
    tool_identifier,
    handler_version,
    implementation_digest
  )
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_release_lifecycle
  ON builtin_tool_release(tool_identifier, status, release_revision);

CREATE TABLE IF NOT EXISTS builtin_tool_lifecycle_audit (
  id TEXT PRIMARY KEY,
  tool_release_id TEXT NOT NULL REFERENCES builtin_tool_release(id),
  previous_status TEXT,
  new_status TEXT NOT NULL
    CHECK (new_status IN ('ACTIVE', 'DEPRECATED', 'DISABLED', 'ARCHIVED')),
  reason_code TEXT NOT NULL,
  safe_summary TEXT NOT NULL DEFAULT '',
  actor_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  CHECK (
    previous_status IS NULL
    OR previous_status IN ('ACTIVE', 'DEPRECATED', 'DISABLED', 'ARCHIVED')
  )
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_lifecycle_audit_release
  ON builtin_tool_lifecycle_audit(tool_release_id, occurred_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_base_identity_environment
  ON platform_base(id, environment_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_workshop_identity_base
  ON platform_workshop(id, base_id);

CREATE TABLE IF NOT EXISTS workshop_partition_policy (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  workshop_id TEXT NOT NULL UNIQUE REFERENCES platform_workshop(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workshop_partition_policy_status
  ON workshop_partition_policy(status, workshop_id);

CREATE TABLE IF NOT EXISTS workshop_partition_policy_draft (
  policy_id TEXT PRIMARY KEY REFERENCES workshop_partition_policy(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  database_rule_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (database_rule_enabled IN (0, 1)),
  database_table_prefix TEXT,
  redis_rule_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (redis_rule_enabled IN (0, 1)),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(policy_id, draft_revision, content_hash),
  CHECK (
    (database_rule_enabled = 0 AND database_table_prefix IS NULL)
    OR
    (
      database_rule_enabled = 1
      AND database_table_prefix IS NOT NULL
      AND length(trim(database_table_prefix)) > 0
      AND database_table_prefix NOT LIKE '%*%'
      AND database_table_prefix NOT LIKE '%?%'
      AND database_table_prefix NOT LIKE '%!%%' ESCAPE '!'
    )
  ),
  CHECK (database_rule_enabled = 1 OR redis_rule_enabled = 1)
);

CREATE TABLE IF NOT EXISTS workshop_partition_policy_draft_redis_prefix (
  policy_id TEXT NOT NULL
    REFERENCES workshop_partition_policy_draft(policy_id) ON DELETE CASCADE,
  prefix TEXT NOT NULL,
  position INTEGER NOT NULL CHECK (position >= 0),
  PRIMARY KEY(policy_id, prefix),
  UNIQUE(policy_id, position),
  CHECK (length(trim(prefix)) > 0),
  CHECK (prefix NOT LIKE '%*%'),
  CHECK (prefix NOT LIKE '%?%'),
  CHECK (prefix NOT LIKE '%[%')
);

CREATE TABLE IF NOT EXISTS workshop_partition_policy_verification (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES workshop_partition_policy(id),
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verifier_version TEXT NOT NULL,
  redis_resource_revision_id TEXT
    REFERENCES platform_resource_revision(id),
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  database_summary_json TEXT NOT NULL DEFAULT '{}',
  redis_summary_json TEXT NOT NULL DEFAULT '{}',
  zero_match_warning INTEGER NOT NULL DEFAULT 0
    CHECK (zero_match_warning IN (0, 1)),
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(id, policy_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_workshop_partition_verification_policy
  ON workshop_partition_policy_verification(policy_id, status, verified_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workshop_partition_verification_input
  ON workshop_partition_policy_verification(
    policy_id,
    draft_revision,
    content_hash,
    verifier_version,
    coalesce(redis_resource_revision_id, '')
  );

CREATE TABLE IF NOT EXISTS workshop_partition_policy_revision (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES workshop_partition_policy(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  database_rule_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (database_rule_enabled IN (0, 1)),
  database_table_prefix TEXT,
  redis_rule_enabled INTEGER NOT NULL DEFAULT 0
    CHECK (redis_rule_enabled IN (0, 1)),
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
  UNIQUE(policy_id, revision),
  UNIQUE(id, policy_id, content_hash),
  UNIQUE(verification_id),
  FOREIGN KEY(verification_id, policy_id, content_hash)
    REFERENCES workshop_partition_policy_verification(
      id,
      policy_id,
      content_hash
    ),
  CHECK (
    (database_rule_enabled = 0 AND database_table_prefix IS NULL)
    OR
    (
      database_rule_enabled = 1
      AND database_table_prefix IS NOT NULL
      AND length(trim(database_table_prefix)) > 0
      AND database_table_prefix NOT LIKE '%*%'
      AND database_table_prefix NOT LIKE '%?%'
      AND database_table_prefix NOT LIKE '%!%%' ESCAPE '!'
    )
  ),
  CHECK (database_rule_enabled = 1 OR redis_rule_enabled = 1)
);

CREATE INDEX IF NOT EXISTS idx_workshop_partition_revision_policy
  ON workshop_partition_policy_revision(policy_id, status, revision);

CREATE TABLE IF NOT EXISTS workshop_partition_policy_revision_redis_prefix (
  policy_revision_id TEXT NOT NULL
    REFERENCES workshop_partition_policy_revision(id),
  prefix TEXT NOT NULL,
  position INTEGER NOT NULL CHECK (position >= 0),
  PRIMARY KEY(policy_revision_id, prefix),
  UNIQUE(policy_revision_id, position),
  CHECK (length(trim(prefix)) > 0),
  CHECK (prefix NOT LIKE '%*%'),
  CHECK (prefix NOT LIKE '%?%'),
  CHECK (prefix NOT LIKE '%[%')
);

CREATE TABLE IF NOT EXISTS loki_scope_policy (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(environment_id, base_id, code),
  FOREIGN KEY(base_id, environment_id)
    REFERENCES platform_base(id, environment_id)
);

CREATE INDEX IF NOT EXISTS idx_loki_scope_policy_target
  ON loki_scope_policy(environment_id, base_id, status);

CREATE TABLE IF NOT EXISTS loki_scope_policy_draft (
  policy_id TEXT PRIMARY KEY REFERENCES loki_scope_policy(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(policy_id, draft_revision, resource_revision_id, content_hash)
);

CREATE TABLE IF NOT EXISTS loki_scope_policy_draft_condition (
  policy_id TEXT NOT NULL
    REFERENCES loki_scope_policy_draft(policy_id) ON DELETE CASCADE,
  label_key TEXT NOT NULL,
  label_value TEXT NOT NULL,
  position INTEGER NOT NULL CHECK (position >= 0),
  PRIMARY KEY(policy_id, label_key),
  UNIQUE(policy_id, position),
  CHECK (length(trim(label_key)) > 0),
  CHECK (length(trim(label_value)) > 0),
  CHECK (label_key NOT LIKE '%*%'),
  CHECK (label_key NOT LIKE '%?%'),
  CHECK (label_value NOT LIKE '%*%'),
  CHECK (label_value NOT LIKE '%?%')
);

CREATE TABLE IF NOT EXISTS loki_scope_policy_verification (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES loki_scope_policy(id),
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verifier_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  match_count INTEGER NOT NULL DEFAULT 0 CHECK (match_count >= 0),
  truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
  zero_match_warning INTEGER NOT NULL DEFAULT 0
    CHECK (zero_match_warning IN (0, 1)),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(
    policy_id,
    resource_revision_id,
    content_hash,
    verifier_version
  ),
  UNIQUE(id, policy_id, resource_revision_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_loki_scope_verification_policy
  ON loki_scope_policy_verification(policy_id, status, verified_at);

CREATE TABLE IF NOT EXISTS loki_scope_policy_revision (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES loki_scope_policy(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  health_status TEXT NOT NULL DEFAULT 'UNKNOWN'
    CHECK (health_status IN ('HEALTHY', 'EMPTY', 'DEGRADED', 'UNKNOWN')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(policy_id, revision),
  UNIQUE(id, policy_id, resource_revision_id, content_hash),
  FOREIGN KEY(
    verification_id,
    policy_id,
    resource_revision_id,
    content_hash
  ) REFERENCES loki_scope_policy_verification(
    id,
    policy_id,
    resource_revision_id,
    content_hash
  )
);

CREATE INDEX IF NOT EXISTS idx_loki_scope_revision_policy
  ON loki_scope_policy_revision(policy_id, status, revision);

CREATE TABLE IF NOT EXISTS loki_scope_policy_revision_condition (
  policy_revision_id TEXT NOT NULL REFERENCES loki_scope_policy_revision(id),
  label_key TEXT NOT NULL,
  label_value TEXT NOT NULL,
  position INTEGER NOT NULL CHECK (position >= 0),
  PRIMARY KEY(policy_revision_id, label_key),
  UNIQUE(policy_revision_id, position),
  CHECK (length(trim(label_key)) > 0),
  CHECK (length(trim(label_value)) > 0),
  CHECK (label_key NOT LIKE '%*%'),
  CHECK (label_key NOT LIKE '%?%'),
  CHECK (label_value NOT LIKE '%*%'),
  CHECK (label_value NOT LIKE '%?%')
);

CREATE TABLE IF NOT EXISTS agent_publication_builtin_tool (
  id TEXT PRIMARY KEY,
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  tool_identifier TEXT NOT NULL,
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  envelope_hash TEXT NOT NULL CHECK (length(envelope_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, tool_release_id),
  UNIQUE(
    id,
    agent_publication_id,
    tool_identifier,
    tool_release_id,
    handler_version,
    implementation_digest,
    public_schema_hash
  ),
  FOREIGN KEY(
    tool_release_id,
    tool_identifier,
    handler_version,
    implementation_digest,
    public_schema_hash
  ) REFERENCES builtin_tool_release(
    id,
    tool_identifier,
    handler_version,
    implementation_digest,
    public_schema_hash
  )
);

CREATE INDEX IF NOT EXISTS idx_agent_publication_builtin_tool_release
  ON agent_publication_builtin_tool(tool_release_id, agent_publication_id);

CREATE TABLE IF NOT EXISTS business_application_revision_target (
  id TEXT PRIMARY KEY,
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  target_scope_type TEXT NOT NULL
    CHECK (target_scope_type IN ('environment', 'base', 'workshop')),
  target_key TEXT NOT NULL,
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  target_hash TEXT NOT NULL CHECK (length(target_hash) = 64),
  target_order INTEGER NOT NULL CHECK (target_order >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(application_revision_id, target_key),
  UNIQUE(application_revision_id, target_order),
  FOREIGN KEY(base_id, environment_id)
    REFERENCES platform_base(id, environment_id),
  FOREIGN KEY(workshop_id, base_id)
    REFERENCES platform_workshop(id, base_id),
  CHECK (length(trim(target_key)) > 0),
  CHECK (
    (
      target_scope_type = 'environment'
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'base'
      AND base_id IS NOT NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'workshop'
      AND base_id IS NOT NULL
      AND workshop_id IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_application_revision_target_nodes
  ON business_application_revision_target(
    environment_id,
    base_id,
    workshop_id,
    application_revision_id
  );

CREATE TABLE IF NOT EXISTS business_application_revision_builtin_tool (
  id TEXT PRIMARY KEY,
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  agent_publication_tool_id TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  selection_hash TEXT NOT NULL CHECK (length(selection_hash) = 64),
  selection_order INTEGER NOT NULL CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, agent_publication_tool_id),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(
    agent_publication_tool_id,
    agent_publication_id,
    tool_identifier,
    tool_release_id,
    handler_version,
    implementation_digest,
    public_schema_hash
  ) REFERENCES agent_publication_builtin_tool(
    id,
    agent_publication_id,
    tool_identifier,
    tool_release_id,
    handler_version,
    implementation_digest,
    public_schema_hash
  )
);

CREATE INDEX IF NOT EXISTS idx_application_revision_builtin_tool_release
  ON business_application_revision_builtin_tool(
    tool_release_id,
    application_revision_id
  );

CREATE TABLE IF NOT EXISTS business_application_revision_builtin_tool_resource (
  id TEXT PRIMARY KEY,
  application_revision_tool_id TEXT NOT NULL
    REFERENCES business_application_revision_builtin_tool(id),
  resource_slot TEXT NOT NULL,
  target_scope_type TEXT NOT NULL
    CHECK (target_scope_type IN ('global', 'environment', 'base', 'workshop')),
  target_key TEXT NOT NULL,
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  placement TEXT CHECK (placement IN ('cloud', 'edge')),
  placement_key TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  workshop_partition_policy_revision_id TEXT
    REFERENCES workshop_partition_policy_revision(id),
  loki_scope_policy_revision_id TEXT REFERENCES loki_scope_policy_revision(id),
  mapping_hash TEXT NOT NULL CHECK (length(mapping_hash) = 64),
  mapping_order INTEGER NOT NULL CHECK (mapping_order >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(
    application_revision_tool_id,
    resource_slot,
    target_key,
    placement_key
  ),
  UNIQUE(application_revision_tool_id, mapping_order),
  CHECK (length(trim(resource_slot)) > 0),
  CHECK (length(trim(target_key)) > 0),
  CHECK (
    (placement IS NULL AND placement_key = '')
    OR
    (placement IS NOT NULL AND placement_key = placement)
  ),
  CHECK (
    (
      target_scope_type = 'global'
      AND environment_id IS NULL
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'environment'
      AND environment_id IS NOT NULL
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'base'
      AND environment_id IS NOT NULL
      AND base_id IS NOT NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'workshop'
      AND environment_id IS NOT NULL
      AND base_id IS NOT NULL
      AND workshop_id IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_application_revision_builtin_resource
  ON business_application_revision_builtin_tool_resource(
    resource_revision_id,
    application_revision_tool_id
  );

CREATE TABLE IF NOT EXISTS business_application_publication_target (
  id TEXT PRIMARY KEY,
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  target_scope_type TEXT NOT NULL
    CHECK (target_scope_type IN ('environment', 'base', 'workshop')),
  target_key TEXT NOT NULL,
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  target_hash TEXT NOT NULL CHECK (length(target_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(application_publication_id, target_key),
  FOREIGN KEY(base_id, environment_id)
    REFERENCES platform_base(id, environment_id),
  FOREIGN KEY(workshop_id, base_id)
    REFERENCES platform_workshop(id, base_id),
  CHECK (length(trim(target_key)) > 0),
  CHECK (
    (
      target_scope_type = 'environment'
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'base'
      AND base_id IS NOT NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'workshop'
      AND base_id IS NOT NULL
      AND workshop_id IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_application_publication_target_nodes
  ON business_application_publication_target(
    environment_id,
    base_id,
    workshop_id,
    application_publication_id
  );

CREATE TABLE IF NOT EXISTS business_application_publication_builtin_tool (
  id TEXT PRIMARY KEY,
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  agent_publication_tool_id TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  allowlist_hash TEXT NOT NULL CHECK (length(allowlist_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, agent_publication_tool_id),
  UNIQUE(
    id,
    application_publication_id,
    tool_identifier,
    tool_release_id
  ),
  FOREIGN KEY(
    agent_publication_tool_id,
    agent_publication_id,
    tool_identifier,
    tool_release_id,
    handler_version,
    implementation_digest,
    public_schema_hash
  ) REFERENCES agent_publication_builtin_tool(
    id,
    agent_publication_id,
    tool_identifier,
    tool_release_id,
    handler_version,
    implementation_digest,
    public_schema_hash
  ),
  FOREIGN KEY(
    tool_release_id,
    tool_identifier,
    handler_version,
    implementation_digest,
    public_schema_hash
  ) REFERENCES builtin_tool_release(
    id,
    tool_identifier,
    handler_version,
    implementation_digest,
    public_schema_hash
  )
);

CREATE INDEX IF NOT EXISTS idx_application_builtin_tool_release
  ON business_application_publication_builtin_tool(
    tool_release_id,
    application_publication_id
  );

CREATE TABLE IF NOT EXISTS business_application_publication_builtin_tool_resource (
  id TEXT PRIMARY KEY,
  application_tool_id TEXT NOT NULL
    REFERENCES business_application_publication_builtin_tool(id),
  resource_slot TEXT NOT NULL,
  target_scope_type TEXT NOT NULL
    CHECK (target_scope_type IN ('global', 'environment', 'base', 'workshop')),
  target_key TEXT NOT NULL,
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  placement TEXT CHECK (placement IN ('cloud', 'edge')),
  placement_key TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  workshop_partition_policy_revision_id TEXT
    REFERENCES workshop_partition_policy_revision(id),
  loki_scope_policy_revision_id TEXT REFERENCES loki_scope_policy_revision(id),
  mapping_hash TEXT NOT NULL CHECK (length(mapping_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(
    application_tool_id,
    resource_slot,
    target_key,
    placement_key
  ),
  CHECK (length(trim(resource_slot)) > 0),
  CHECK (length(trim(target_key)) > 0),
  CHECK (
    (placement IS NULL AND placement_key = '')
    OR
    (placement IS NOT NULL AND placement_key = placement)
  ),
  CHECK (
    (
      target_scope_type = 'global'
      AND environment_id IS NULL
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'environment'
      AND environment_id IS NOT NULL
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'base'
      AND environment_id IS NOT NULL
      AND base_id IS NOT NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'workshop'
      AND environment_id IS NOT NULL
      AND base_id IS NOT NULL
      AND workshop_id IS NOT NULL
    )
  )
);

CREATE INDEX IF NOT EXISTS idx_application_builtin_tool_resource_revision
  ON business_application_publication_builtin_tool_resource(
    resource_revision_id,
    application_tool_id
  );

CREATE INDEX IF NOT EXISTS idx_application_builtin_tool_resource_target
  ON business_application_publication_builtin_tool_resource(
    target_scope_type,
    environment_id,
    base_id,
    workshop_id,
    placement_key
  );

CREATE TABLE IF NOT EXISTS business_application_publication_builtin_tool_resolution_set (
  application_publication_id TEXT PRIMARY KEY
    REFERENCES business_application_publication(id),
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  resolution_count INTEGER NOT NULL CHECK (resolution_count >= 0),
  resolution_set_hash TEXT NOT NULL CHECK (length(resolution_set_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(application_publication_id, resolution_set_hash)
);

CREATE TABLE IF NOT EXISTS business_application_publication_builtin_tool_resolution (
  id TEXT PRIMARY KEY,
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  application_tool_id TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  resource_slot TEXT NOT NULL,
  target_scope_type TEXT NOT NULL
    CHECK (target_scope_type IN ('environment', 'base', 'workshop')),
  target_key TEXT NOT NULL,
  target_hash TEXT NOT NULL CHECK (length(target_hash) = 64),
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  placement TEXT CHECK (placement IN ('cloud', 'edge')),
  placement_key TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL REFERENCES platform_resource_revision(id),
  resource_content_hash TEXT NOT NULL CHECK (length(resource_content_hash) = 64),
  resource_kind TEXT NOT NULL CHECK (resource_kind IN ('database', 'redis', 'loki')),
  resource_scope_type TEXT NOT NULL
    CHECK (resource_scope_type IN ('global', 'environment', 'base', 'workshop')),
  workshop_partition_policy_revision_id TEXT
    REFERENCES workshop_partition_policy_revision(id),
  workshop_partition_policy_hash TEXT,
  loki_scope_policy_revision_id TEXT REFERENCES loki_scope_policy_revision(id),
  loki_scope_policy_hash TEXT,
  mapping_hash TEXT NOT NULL CHECK (length(mapping_hash) = 64),
  resolution_hash TEXT NOT NULL CHECK (length(resolution_hash) = 64),
  resolution_order INTEGER NOT NULL CHECK (resolution_order >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(
    application_tool_id,
    resource_slot,
    target_key,
    placement_key
  ),
  UNIQUE(application_publication_id, resolution_order),
  UNIQUE(application_publication_id, resolution_hash),
  FOREIGN KEY(
    application_tool_id,
    application_publication_id,
    tool_identifier,
    tool_release_id
  ) REFERENCES business_application_publication_builtin_tool(
    id,
    application_publication_id,
    tool_identifier,
    tool_release_id
  ),
  FOREIGN KEY(base_id, environment_id)
    REFERENCES platform_base(id, environment_id),
  FOREIGN KEY(workshop_id, base_id)
    REFERENCES platform_workshop(id, base_id),
  CHECK (length(trim(resource_slot)) > 0),
  CHECK (length(trim(target_key)) > 0),
  CHECK (
    (placement IS NULL AND placement_key = '')
    OR
    (placement IS NOT NULL AND placement_key = placement)
  ),
  CHECK (
    (
      target_scope_type = 'environment'
      AND base_id IS NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'base'
      AND base_id IS NOT NULL
      AND workshop_id IS NULL
    )
    OR
    (
      target_scope_type = 'workshop'
      AND base_id IS NOT NULL
      AND workshop_id IS NOT NULL
    )
  ),
  CHECK (
    (
      workshop_partition_policy_revision_id IS NULL
      AND workshop_partition_policy_hash IS NULL
    )
    OR
    (
      workshop_partition_policy_revision_id IS NOT NULL
      AND length(workshop_partition_policy_hash) = 64
    )
  ),
  CHECK (
    (
      loki_scope_policy_revision_id IS NULL
      AND loki_scope_policy_hash IS NULL
    )
    OR
    (
      loki_scope_policy_revision_id IS NOT NULL
      AND length(loki_scope_policy_hash) = 64
    )
  ),
  CHECK (
    workshop_partition_policy_revision_id IS NULL
    OR loki_scope_policy_revision_id IS NULL
  )
);

CREATE INDEX IF NOT EXISTS idx_application_builtin_resolution_target
  ON business_application_publication_builtin_tool_resolution(
    application_publication_id,
    target_scope_type,
    environment_id,
    base_id,
    workshop_id,
    resource_slot,
    placement_key
  );

CREATE INDEX IF NOT EXISTS idx_application_builtin_resolution_resource
  ON business_application_publication_builtin_tool_resolution(
    resource_revision_id,
    application_publication_id
  );

CREATE TABLE IF NOT EXISTS agent_job_builtin_tool_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  schema_version INTEGER NOT NULL CHECK (schema_version = 3),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL UNIQUE CHECK (length(snapshot_hash) = 64),
  authorization_hash TEXT NOT NULL CHECK (length(authorization_hash) = 64),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_builtin_tool_snapshot_publication
  ON agent_job_builtin_tool_snapshot(application_publication_id, created_at);

CREATE TABLE IF NOT EXISTS agent_job_builtin_tool_binding (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES agent_job_builtin_tool_snapshot(id),
  tool_identifier TEXT NOT NULL,
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  public_schema_hash TEXT NOT NULL CHECK (length(public_schema_hash) = 64),
  resource_slot TEXT NOT NULL DEFAULT '',
  target_key TEXT NOT NULL,
  available_placements_json TEXT NOT NULL DEFAULT '[]',
  resource_revision_id TEXT,
  workshop_partition_policy_revision_id TEXT,
  workshop_partition_policy_hash TEXT,
  loki_scope_policy_revision_id TEXT,
  loki_scope_policy_hash TEXT,
  binding_hash TEXT NOT NULL CHECK (length(binding_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(snapshot_id, tool_identifier, resource_slot, target_key),
  CHECK (
    workshop_partition_policy_hash IS NULL
    OR length(workshop_partition_policy_hash) = 64
  ),
  CHECK (
    loki_scope_policy_hash IS NULL
    OR length(loki_scope_policy_hash) = 64
  )
);

CREATE INDEX IF NOT EXISTS idx_job_builtin_tool_binding_release
  ON agent_job_builtin_tool_binding(tool_release_id, snapshot_id);

CREATE INDEX IF NOT EXISTS idx_job_builtin_tool_binding_resource
  ON agent_job_builtin_tool_binding(resource_revision_id, snapshot_id);

CREATE TABLE IF NOT EXISTS agent_tool_call_builtin_tool_fact (
  tool_call_id TEXT PRIMARY KEY REFERENCES agent_tool_call(id),
  snapshot_id TEXT NOT NULL REFERENCES agent_job_builtin_tool_snapshot(id),
  tool_execution_binding_id TEXT NOT NULL
    REFERENCES agent_job_builtin_tool_binding(id),
  tool_release_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  actual_placement TEXT CHECK (actual_placement IN ('cloud', 'edge')),
  resource_revision_id TEXT,
  workshop_partition_policy_revision_id TEXT,
  loki_scope_policy_revision_id TEXT,
  effective_scope_hash TEXT NOT NULL CHECK (length(effective_scope_hash) = 64),
  effective_selector_hash TEXT,
  authorization_decision TEXT NOT NULL
    CHECK (authorization_decision IN ('ALLOWED', 'DENIED', 'FAILED')),
  decision_reason_code TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  CHECK (
    effective_selector_hash IS NULL
    OR length(effective_selector_hash) = 64
  )
);

CREATE INDEX IF NOT EXISTS idx_tool_call_builtin_fact_release
  ON agent_tool_call_builtin_tool_fact(tool_release_id, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_call_builtin_fact_resource
  ON agent_tool_call_builtin_tool_fact(resource_revision_id, created_at);

CREATE TABLE IF NOT EXISTS builtin_tool_legacy_migration (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL
    CHECK (
      source_type IN (
        'AGENT_PUBLICATION',
        'APPLICATION_PUBLICATION',
        'JOB'
      )
    ),
  source_id TEXT NOT NULL,
  migration_version TEXT NOT NULL,
  candidate_class TEXT NOT NULL
    CHECK (candidate_class IN ('ZERO', 'ONE', 'MULTIPLE')),
  candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'MATERIALIZED', 'QUARANTINED', 'IGNORED')),
  quarantine_reason_code TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT,
  evidence_summary_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_type, source_id, migration_version),
  CHECK (snapshot_hash IS NULL OR length(snapshot_hash) = 64),
  CHECK (
    status != 'MATERIALIZED'
    OR (candidate_class = 'ONE' AND snapshot_hash IS NOT NULL)
  ),
  CHECK (
    status != 'QUARANTINED'
    OR length(trim(quarantine_reason_code)) > 0
  )
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_legacy_migration_status
  ON builtin_tool_legacy_migration(source_type, status, candidate_class);

CREATE TABLE IF NOT EXISTS builtin_tool_legacy_write_audit (
  id TEXT PRIMARY KEY,
  write_boundary TEXT NOT NULL
    CHECK (
      write_boundary IN (
        'AGENT_PUBLICATION',
        'APPLICATION_PUBLICATION',
        'JOB_SNAPSHOT'
      )
    ),
  source_id TEXT NOT NULL,
  attempted_binding_version TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('REJECTED', 'OBSERVED')),
  reason_code TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_builtin_tool_legacy_write_audit_boundary
  ON builtin_tool_legacy_write_audit(write_boundary, occurred_at);

CREATE VIEW builtin_tool_legacy_reference_report AS
SELECT
  'new_legacy_write_attempt' AS metric,
  count(*) AS reference_count
FROM builtin_tool_legacy_write_audit
WHERE attempted_binding_version = 'legacy-v1'
UNION ALL
SELECT
  'all_agent_name_binding' AS metric,
  count(*) AS reference_count
FROM agent_tool_binding
UNION ALL
SELECT
  'active_agent_name_binding' AS metric,
  count(*) AS reference_count
FROM agent_tool_binding binding
JOIN agent_publication publication
  ON publication.id = binding.publication_id
WHERE publication.status = 'active'
UNION ALL
SELECT
  'recoverable_job_without_exact_snapshot' AS metric,
  count(*) AS reference_count
FROM agent_job job
LEFT JOIN agent_job_builtin_tool_snapshot snapshot
  ON snapshot.job_id = job.id
WHERE snapshot.id IS NULL
  AND (
    job.status IN ('PENDING', 'RUNNING')
    OR
    (
      job.status = 'FAILED'
      AND job.retry_count < job.max_retry_count
      AND job.result IS NULL
    )
  );
