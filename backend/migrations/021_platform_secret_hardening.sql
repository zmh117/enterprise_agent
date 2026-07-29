CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_secret_version_active
  ON platform_secret_version(secret_id)
  WHERE status = 'active';

COMMENT ON INDEX uq_platform_secret_version_active IS
  '每个平台注册凭据最多只有一个 active 密文版本；新版本先 staged，再原子切换';

CREATE TABLE IF NOT EXISTS platform_secret_change_event (
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

CREATE INDEX IF NOT EXISTS idx_platform_secret_change_pending
  ON platform_secret_change_event(status, created_at);

COMMENT ON TABLE platform_secret_change_event IS
  'Secret active version 或状态变化通知；消费者重载相关资源，失败时保留 Last Known Good';
COMMENT ON COLUMN platform_secret_change_event.error_summary IS
  '固定安全错误摘要，不包含凭据、密文或资源连接参数';
