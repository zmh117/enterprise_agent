-- migration: sqlite-foreign-keys-off
-- Keep Loki Scope Policy verification evidence bound to the exact Draft
-- revision. Identical policy content copied into a later Draft must produce
-- independent evidence instead of colliding with an earlier publication.

-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE loki_scope_policy_verification
  RENAME TO loki_scope_policy_verification_pre_per_draft;

-- sqlite-only
CREATE TABLE loki_scope_policy_verification (
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
    draft_revision,
    resource_revision_id,
    content_hash,
    verifier_version
  ),
  UNIQUE(id, policy_id, resource_revision_id, content_hash)
);

-- sqlite-only
INSERT INTO loki_scope_policy_verification
  (id, policy_id, draft_revision, resource_revision_id, content_hash,
   verifier_version, status, match_count, truncated, zero_match_warning,
   result_summary_json, safe_error_summary, verified_by, verified_at)
SELECT id, policy_id, draft_revision, resource_revision_id, content_hash,
       verifier_version, status, match_count, truncated, zero_match_warning,
       result_summary_json, safe_error_summary, verified_by, verified_at
  FROM loki_scope_policy_verification_pre_per_draft;

-- sqlite-only
DROP TABLE loki_scope_policy_verification_pre_per_draft;

-- sqlite-only
CREATE INDEX idx_loki_scope_verification_policy
  ON loki_scope_policy_verification(policy_id, status, verified_at);

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- postgres-only
ALTER TABLE loki_scope_policy_verification
  DROP CONSTRAINT
    loki_scope_policy_verificatio_policy_id_resource_revision_i_key;

-- postgres-only
ALTER TABLE loki_scope_policy_verification
  ADD CONSTRAINT loki_scope_policy_verification_input_key
  UNIQUE(
    policy_id,
    draft_revision,
    resource_revision_id,
    content_hash,
    verifier_version
  );
