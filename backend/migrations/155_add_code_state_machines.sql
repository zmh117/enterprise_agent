-- 状态机 v2：只增加结构；旧候选由明确来源范围的部署清理另行处理。
-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE knowledge.document DROP CONSTRAINT document_document_kind_check;
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT document_document_kind_check CHECK(document_kind IN ('defect','ticket','requirement','article','object','state_machine','state','operation','rule','transition'));
-- sqlite-only
CREATE TABLE "knowledge.document_fsm" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
 source_object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 external_number TEXT NOT NULL,
 document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article','object','state_machine','state','operation','rule','transition')),
 current_revision_id TEXT,
 lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('pending','active','unavailable','deleted')),
 created_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL,
 source_observed_stamp_raw INTEGER CHECK(source_observed_stamp_raw IS NULL OR source_observed_stamp_raw>0),
 UNIQUE(source_id,source_object_type,external_id),
 UNIQUE(source_id,source_object_type,external_id,id),
 FOREIGN KEY(id,current_revision_id) REFERENCES "knowledge.document_revision"(document_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(lifecycle_state<>'pending' OR current_revision_id IS NULL)
);
-- sqlite-only
INSERT INTO "knowledge.document_fsm" (id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at)
SELECT id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at FROM "knowledge.document";
-- sqlite-only
DROP TABLE "knowledge.document";
-- sqlite-only
ALTER TABLE "knowledge.document_fsm" RENAME TO "knowledge.document";
-- sqlite-only
CREATE INDEX knowledge_document_kind_idx ON "knowledge.document"(source_id,document_kind);
-- postgres-only
CREATE UNIQUE INDEX knowledge_code_member_revision_idx ON knowledge.code_member(snapshot_id,document_id,revision_id);
-- sqlite-only
CREATE UNIQUE INDEX knowledge_code_member_revision_idx ON "knowledge.code_member"(snapshot_id,document_id,revision_id);
-- postgres-only
CREATE TABLE knowledge.code_object (
 snapshot_id TEXT NOT NULL REFERENCES knowledge.code_snapshot(id),
 object_key TEXT NOT NULL,
 document_id TEXT NOT NULL,
 display_name TEXT NOT NULL,
 catalog_hash TEXT NOT NULL CHECK(length(catalog_hash)=64),
 PRIMARY KEY(snapshot_id,object_key),
 FOREIGN KEY(snapshot_id,document_id) REFERENCES knowledge.code_member(snapshot_id,document_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_object" (
 snapshot_id TEXT NOT NULL REFERENCES "knowledge.code_snapshot"(id),
 object_key TEXT NOT NULL,
 document_id TEXT NOT NULL,
 display_name TEXT NOT NULL,
 catalog_hash TEXT NOT NULL CHECK(length(catalog_hash)=64),
 PRIMARY KEY(snapshot_id,object_key),
 FOREIGN KEY(snapshot_id,document_id) REFERENCES "knowledge.code_member"(snapshot_id,document_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_object IS '状态机知识快照中的code_object；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_object.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_object.object_key IS '状态机知识的object_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_object.document_id IS '状态机知识的document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_object.display_name IS '状态机知识的display_name';
-- postgres-only
COMMENT ON COLUMN knowledge.code_object.catalog_hash IS '状态机知识的catalog_hash';
-- postgres-only
CREATE TABLE knowledge.code_machine (
 snapshot_id TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 object_key TEXT NOT NULL,
 dimension TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,machine_key),
 UNIQUE(snapshot_id,machine_key,object_key),
 FOREIGN KEY(snapshot_id,object_key) REFERENCES knowledge.code_object(snapshot_id,object_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_machine" (
 snapshot_id TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 object_key TEXT NOT NULL,
 dimension TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,machine_key),
 UNIQUE(snapshot_id,machine_key,object_key),
 FOREIGN KEY(snapshot_id,object_key) REFERENCES "knowledge.code_object"(snapshot_id,object_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_machine IS '状态机知识快照中的code_machine；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_machine.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_machine.machine_key IS '状态机知识的machine_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_machine.object_key IS '状态机知识的object_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_machine.dimension IS '状态机知识的dimension';
-- postgres-only
CREATE TABLE knowledge.code_event (
 snapshot_id TEXT NOT NULL,
 event_key TEXT NOT NULL,
 object_key TEXT NOT NULL,
 display_name TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,event_key),
 UNIQUE(snapshot_id,event_key,object_key),
 FOREIGN KEY(snapshot_id,object_key) REFERENCES knowledge.code_object(snapshot_id,object_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_event" (
 snapshot_id TEXT NOT NULL,
 event_key TEXT NOT NULL,
 object_key TEXT NOT NULL,
 display_name TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,event_key),
 UNIQUE(snapshot_id,event_key,object_key),
 FOREIGN KEY(snapshot_id,object_key) REFERENCES "knowledge.code_object"(snapshot_id,object_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_event IS '状态机知识快照中的code_event；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_event.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_event.event_key IS '状态机知识的event_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_event.object_key IS '状态机知识的object_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_event.display_name IS '状态机知识的display_name';
-- postgres-only
CREATE TABLE knowledge.code_state (
 snapshot_id TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 state_key TEXT NOT NULL,
 raw_value TEXT NOT NULL,
 display_name TEXT NOT NULL,
 evidence_json JSONB NOT NULL,
 PRIMARY KEY(snapshot_id,machine_key,state_key),
 UNIQUE(snapshot_id,machine_key,raw_value),
 FOREIGN KEY(snapshot_id,machine_key) REFERENCES knowledge.code_machine(snapshot_id,machine_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_state" (
 snapshot_id TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 state_key TEXT NOT NULL,
 raw_value TEXT NOT NULL,
 display_name TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,machine_key,state_key),
 UNIQUE(snapshot_id,machine_key,raw_value),
 FOREIGN KEY(snapshot_id,machine_key) REFERENCES "knowledge.code_machine"(snapshot_id,machine_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_state IS '状态机知识快照中的code_state；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.machine_key IS '状态机知识的machine_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.state_key IS '状态机知识的state_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.raw_value IS '状态机知识的raw_value';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.display_name IS '状态机知识的display_name';
-- postgres-only
COMMENT ON COLUMN knowledge.code_state.evidence_json IS '状态机知识的evidence_json';
-- postgres-only
CREATE TABLE knowledge.code_transition (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 document_id TEXT NOT NULL,
 revision_id TEXT NOT NULL,
 object_key TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 event_key TEXT NOT NULL,
 source_mode TEXT NOT NULL CHECK(source_mode IN ('states','any','unresolved')),
 source_json JSONB NOT NULL,
 target_mode TEXT NOT NULL CHECK(target_mode IN ('state','unchanged','unknown')),
 target_state_key TEXT,
 target_json JSONB NOT NULL,
 guard_json JSONB NOT NULL,
 actions_json JSONB NOT NULL,
 success_boundary_json JSONB NOT NULL,
 PRIMARY KEY(snapshot_id,business_key),
 UNIQUE(snapshot_id,document_id),
 UNIQUE(snapshot_id,business_key,machine_key),
 CHECK((target_mode='state' AND target_state_key IS NOT NULL) OR (target_mode<>'state' AND target_state_key IS NULL)),
 FOREIGN KEY(snapshot_id,document_id,revision_id) REFERENCES knowledge.code_member(snapshot_id,document_id,revision_id),
 FOREIGN KEY(snapshot_id,machine_key,object_key) REFERENCES knowledge.code_machine(snapshot_id,machine_key,object_key),
 FOREIGN KEY(snapshot_id,event_key,object_key) REFERENCES knowledge.code_event(snapshot_id,event_key,object_key),
 FOREIGN KEY(snapshot_id,machine_key,target_state_key) REFERENCES knowledge.code_state(snapshot_id,machine_key,state_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_transition" (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 document_id TEXT NOT NULL,
 revision_id TEXT NOT NULL,
 object_key TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 event_key TEXT NOT NULL,
 source_mode TEXT NOT NULL CHECK(source_mode IN ('states','any','unresolved')),
 source_json TEXT NOT NULL,
 target_mode TEXT NOT NULL CHECK(target_mode IN ('state','unchanged','unknown')),
 target_state_key TEXT,
 target_json TEXT NOT NULL,
 guard_json TEXT NOT NULL,
 actions_json TEXT NOT NULL,
 success_boundary_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,business_key),
 UNIQUE(snapshot_id,document_id),
 UNIQUE(snapshot_id,business_key,machine_key),
 CHECK((target_mode='state' AND target_state_key IS NOT NULL) OR (target_mode<>'state' AND target_state_key IS NULL)),
 FOREIGN KEY(snapshot_id,document_id,revision_id) REFERENCES "knowledge.code_member"(snapshot_id,document_id,revision_id),
 FOREIGN KEY(snapshot_id,machine_key,object_key) REFERENCES "knowledge.code_machine"(snapshot_id,machine_key,object_key),
 FOREIGN KEY(snapshot_id,event_key,object_key) REFERENCES "knowledge.code_event"(snapshot_id,event_key,object_key),
 FOREIGN KEY(snapshot_id,machine_key,target_state_key) REFERENCES "knowledge.code_state"(snapshot_id,machine_key,state_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_transition IS '状态机知识快照中的code_transition；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.business_key IS '状态机知识的business_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.document_id IS '状态机知识的document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.revision_id IS '状态机知识的revision_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.object_key IS '状态机知识的object_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.machine_key IS '状态机知识的machine_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.event_key IS '状态机知识的event_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.source_mode IS '状态机知识的source_mode';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.source_json IS '状态机知识的source_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.target_mode IS '状态机知识的target_mode';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.target_state_key IS '状态机知识的target_state_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.target_json IS '状态机知识的target_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.guard_json IS '状态机知识的guard_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.actions_json IS '状态机知识的actions_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition.success_boundary_json IS '状态机知识的success_boundary_json';
-- postgres-only
CREATE TABLE knowledge.code_transition_source (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 state_key TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,business_key,state_key),
 FOREIGN KEY(snapshot_id,business_key,machine_key) REFERENCES knowledge.code_transition(snapshot_id,business_key,machine_key),
 FOREIGN KEY(snapshot_id,machine_key,state_key) REFERENCES knowledge.code_state(snapshot_id,machine_key,state_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_transition_source" (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 machine_key TEXT NOT NULL,
 state_key TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,business_key,state_key),
 FOREIGN KEY(snapshot_id,business_key,machine_key) REFERENCES "knowledge.code_transition"(snapshot_id,business_key,machine_key),
 FOREIGN KEY(snapshot_id,machine_key,state_key) REFERENCES "knowledge.code_state"(snapshot_id,machine_key,state_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_transition_source IS '状态机知识快照中的code_transition_source；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_source.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_source.business_key IS '状态机知识的business_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_source.machine_key IS '状态机知识的machine_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_source.state_key IS '状态机知识的state_key';
-- postgres-only
CREATE TABLE knowledge.code_transition_failure (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 failure_key TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 machine_key TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('rejected','failed','partial','unknown')),
 phase TEXT NOT NULL,
 state_mode TEXT NOT NULL CHECK(state_mode IN ('state','unchanged','unknown')),
 state_key TEXT,
 failure_json JSONB NOT NULL,
 PRIMARY KEY(snapshot_id,business_key,failure_key),
 UNIQUE(snapshot_id,business_key,ordinal),
 CHECK((state_mode='state' AND state_key IS NOT NULL) OR (state_mode<>'state' AND state_key IS NULL)),
 FOREIGN KEY(snapshot_id,business_key,machine_key) REFERENCES knowledge.code_transition(snapshot_id,business_key,machine_key),
 FOREIGN KEY(snapshot_id,machine_key,state_key) REFERENCES knowledge.code_state(snapshot_id,machine_key,state_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_transition_failure" (
 snapshot_id TEXT NOT NULL,
 business_key TEXT NOT NULL,
 failure_key TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 machine_key TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('rejected','failed','partial','unknown')),
 phase TEXT NOT NULL,
 state_mode TEXT NOT NULL CHECK(state_mode IN ('state','unchanged','unknown')),
 state_key TEXT,
 failure_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,business_key,failure_key),
 UNIQUE(snapshot_id,business_key,ordinal),
 CHECK((state_mode='state' AND state_key IS NOT NULL) OR (state_mode<>'state' AND state_key IS NULL)),
 FOREIGN KEY(snapshot_id,business_key,machine_key) REFERENCES "knowledge.code_transition"(snapshot_id,business_key,machine_key),
 FOREIGN KEY(snapshot_id,machine_key,state_key) REFERENCES "knowledge.code_state"(snapshot_id,machine_key,state_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_transition_failure IS '状态机知识快照中的code_transition_failure；与不可变修订同事务保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.snapshot_id IS '状态机知识的snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.business_key IS '状态机知识的business_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.failure_key IS '状态机知识的failure_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.ordinal IS '状态机知识的ordinal';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.machine_key IS '状态机知识的machine_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.outcome IS '状态机知识的outcome';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.phase IS '状态机知识的phase';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.state_mode IS '状态机知识的state_mode';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.state_key IS '状态机知识的state_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_transition_failure.failure_json IS '状态机知识的failure_json';
