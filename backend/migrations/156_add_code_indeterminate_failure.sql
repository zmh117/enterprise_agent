-- 已取证的运行时不确定结果与提取未知分离；不改写既有候选或事实。
-- postgres-only
ALTER TABLE knowledge.code_transition_failure DROP CONSTRAINT code_transition_failure_state_mode_check;
-- postgres-only
ALTER TABLE knowledge.code_transition_failure ADD CONSTRAINT code_transition_failure_state_mode_check CHECK(state_mode IN ('state','unchanged','unknown','indeterminate'));
-- sqlite-only
CREATE TABLE "knowledge.code_transition_failure_v2" (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 failure_key TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 machine_key TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('rejected','failed','partial','unknown')),
 phase TEXT NOT NULL,
 state_mode TEXT NOT NULL CHECK(state_mode IN ('state','unchanged','unknown','indeterminate')),
 state_key TEXT,
 failure_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,business_key,failure_key),
 UNIQUE(snapshot_id,business_key,ordinal),
 CHECK((state_mode='state' AND state_key IS NOT NULL) OR (state_mode<>'state' AND state_key IS NULL)),
 FOREIGN KEY(snapshot_id,business_key,machine_key) REFERENCES "knowledge.code_transition"(snapshot_id,business_key,machine_key),
 FOREIGN KEY(snapshot_id,machine_key,state_key) REFERENCES "knowledge.code_state"(snapshot_id,machine_key,state_key)
);
-- sqlite-only
INSERT INTO "knowledge.code_transition_failure_v2" SELECT * FROM "knowledge.code_transition_failure";
-- sqlite-only
DROP TABLE "knowledge.code_transition_failure";
-- sqlite-only
ALTER TABLE "knowledge.code_transition_failure_v2" RENAME TO "knowledge.code_transition_failure";
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.state_mode IS 'state 确定状态；unchanged 不变；unknown 证据不足；indeterminate 源码已确认最终状态需现场核验';
