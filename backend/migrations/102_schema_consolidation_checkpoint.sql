-- Re-runnable schema consolidation progress. This table stores only bounded
-- counters, stable high-water IDs, and evidence digests, never business bodies.

CREATE TABLE schema_consolidation_checkpoint (
  phase TEXT NOT NULL,
  target_object TEXT NOT NULL,
  last_id TEXT NOT NULL DEFAULT '',
  scanned_count INTEGER NOT NULL DEFAULT 0 CHECK (scanned_count >= 0),
  updated_count INTEGER NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
  blocked_count INTEGER NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
  evidence_digest TEXT NOT NULL CHECK (length(evidence_digest) = 64),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (phase, target_object)
);

CREATE INDEX idx_schema_consolidation_checkpoint_updated
  ON schema_consolidation_checkpoint(updated_at, phase, target_object);

CREATE TABLE schema_consolidation_contract_approval (
  contract_version TEXT PRIMARY KEY,
  expected_head TEXT NOT NULL,
  target_label TEXT NOT NULL,
  evidence_digest TEXT NOT NULL CHECK (length(evidence_digest) = 64),
  backup_reference_digest TEXT NOT NULL
    CHECK (length(backup_reference_digest) = 64),
  parity_verified INTEGER NOT NULL CHECK (parity_verified = 1),
  workflow_parity_verified INTEGER NOT NULL CHECK (workflow_parity_verified = 1),
  zero_legacy_access_verified INTEGER NOT NULL
    CHECK (zero_legacy_access_verified = 1),
  retry_recovery_cycle_observed INTEGER NOT NULL
    CHECK (retry_recovery_cycle_observed = 1),
  production_release_cycle_observed INTEGER NOT NULL
    CHECK (production_release_cycle_observed = 1),
  retention_verified INTEGER NOT NULL CHECK (retention_verified = 1),
  approvals_verified INTEGER NOT NULL CHECK (approvals_verified = 1),
  approved_at TEXT NOT NULL
);

COMMENT ON TABLE schema_consolidation_checkpoint IS
  '内容安全的有界 schema 收敛回填高水位进度。';
COMMENT ON COLUMN schema_consolidation_checkpoint.phase IS '受控收敛阶段代码。';
COMMENT ON COLUMN schema_consolidation_checkpoint.target_object IS '正在处理的 schema 对象。';
COMMENT ON COLUMN schema_consolidation_checkpoint.last_id IS '稳定高水位标识。';
COMMENT ON COLUMN schema_consolidation_checkpoint.scanned_count IS '累计检查行数。';
COMMENT ON COLUMN schema_consolidation_checkpoint.updated_count IS '累计更新行数。';
COMMENT ON COLUMN schema_consolidation_checkpoint.blocked_count IS '累计阻塞行数。';
COMMENT ON COLUMN schema_consolidation_checkpoint.evidence_digest IS '内容安全进度证据的 SHA-256。';
COMMENT ON COLUMN schema_consolidation_checkpoint.updated_at IS '最近检查点时间。';

COMMENT ON TABLE schema_consolidation_contract_approval IS
  '执行 schema contract 的单独授权内容安全证据门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.contract_version IS '已授权的 contract migration 版本。';
COMMENT ON COLUMN schema_consolidation_contract_approval.expected_head IS '精确前置 migration head。';
COMMENT ON COLUMN schema_consolidation_contract_approval.target_label IS '已确认的非敏感环境标签。';
COMMENT ON COLUMN schema_consolidation_contract_approval.evidence_digest IS '有界退役证据的 SHA-256。';
COMMENT ON COLUMN schema_consolidation_contract_approval.backup_reference_digest IS '操作方备份引用的 SHA-256。';
COMMENT ON COLUMN schema_consolidation_contract_approval.parity_verified IS 'Session Job Message 一致性门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.workflow_parity_verified IS 'Workflow 图一致性门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.zero_legacy_access_verified IS '旧读写零访问观察门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.retry_recovery_cycle_observed IS '完整重试恢复周期观察门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.production_release_cycle_observed IS '生产发布周期观察门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.retention_verified IS '保留期完成门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.approvals_verified IS '跨领域批准门禁。';
COMMENT ON COLUMN schema_consolidation_contract_approval.approved_at IS '批准时间。';
