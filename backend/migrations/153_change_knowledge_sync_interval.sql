-- 自动同步固定为四小时；保留计划身份、开关、配置修订及运行断点。
-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE knowledge.sync_binding DROP CONSTRAINT sync_binding_interval_seconds_check;
-- postgres-only
ALTER TABLE knowledge.sync_binding ALTER COLUMN interval_seconds SET DEFAULT 14400;
-- postgres-only
UPDATE knowledge.sync_binding b
SET interval_seconds=14400,
    next_run_at=CASE
        WHEN next_run_at IS NOT NULL AND EXISTS (SELECT 1 FROM knowledge.sync_run r WHERE r.binding_id=b.id)
        THEN next_run_at + INTERVAL '3 hours'
        ELSE next_run_at
    END;
-- postgres-only
ALTER TABLE knowledge.sync_binding ADD CONSTRAINT sync_binding_interval_seconds_check CHECK(interval_seconds=14400);
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.interval_seconds IS '自动同步间隔，固定四小时（14400 秒）';
-- sqlite-only
CREATE TABLE "knowledge.sync_binding_four_hours" (
 id TEXT PRIMARY KEY,
 code TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL UNIQUE REFERENCES "knowledge.source"(id),
 configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
 configuration_hash TEXT NOT NULL CHECK(length(configuration_hash)=64),
 configuration_json TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 interval_seconds INTEGER NOT NULL DEFAULT 14400 CHECK(interval_seconds=14400),
 next_run_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 resource_pins_json TEXT NOT NULL DEFAULT '{}',
 schedule_enabled INTEGER NOT NULL DEFAULT 1 CHECK(schedule_enabled IN (0,1))
);
-- sqlite-only
INSERT INTO "knowledge.sync_binding_four_hours"
 (id,code,source_id,configuration_revision,configuration_hash,configuration_json,enabled,interval_seconds,next_run_at,created_at,updated_at,resource_pins_json,schedule_enabled)
SELECT b.id,b.code,b.source_id,b.configuration_revision,b.configuration_hash,b.configuration_json,b.enabled,14400,
 CASE
     WHEN b.next_run_at IS NOT NULL AND EXISTS (SELECT 1 FROM "knowledge.sync_run" r WHERE r.binding_id=b.id)
     THEN strftime('%Y-%m-%dT%H:%M:%f+00:00',b.next_run_at,'+3 hours')
     ELSE b.next_run_at
 END,
 b.created_at,b.updated_at,b.resource_pins_json,b.schedule_enabled
FROM "knowledge.sync_binding" b;
-- sqlite-only
DROP TABLE "knowledge.sync_binding";
-- sqlite-only
ALTER TABLE "knowledge.sync_binding_four_hours" RENAME TO "knowledge.sync_binding";
