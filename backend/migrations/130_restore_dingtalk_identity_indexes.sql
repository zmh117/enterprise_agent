-- Restore the DingTalk identity invariants lost when migration 126 rebuilt
-- user_external_identity on SQLite. PostgreSQL keeps the same named indexes
-- from the baseline, so IF NOT EXISTS makes this forward repair portable.

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_identity_enterprise_subject
  ON user_external_identity(dingtalk_enterprise_id, external_subject_id)
  WHERE provider = 'dingtalk' AND dingtalk_enterprise_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_identity_user_enterprise_current
  ON user_external_identity(user_id, dingtalk_enterprise_id)
  WHERE provider = 'dingtalk'
    AND dingtalk_enterprise_id IS NOT NULL
    AND status IN ('enabled', 'disabled');
