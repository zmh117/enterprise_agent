-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE browser_workshop_binding ALTER COLUMN base_id DROP NOT NULL;
-- postgres-only
ALTER TABLE browser_workshop_binding ALTER COLUMN workshop_id DROP NOT NULL;
-- postgres-only
ALTER TABLE browser_workshop_binding ADD CONSTRAINT ck_browser_binding_parent CHECK (workshop_id IS NULL OR base_id IS NOT NULL);
-- postgres-only
ALTER TABLE browser_workshop_binding ADD COLUMN floating INTEGER NOT NULL DEFAULT 1 CHECK (floating IN (0,1));
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.floating IS '匹配此规则时是否显示悬浮助手';
-- sqlite-only
CREATE TABLE browser_site_binding_copy (
 id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK (revision >= 1),
 origin TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES app_user(id),
 application_id TEXT NOT NULL REFERENCES business_application(id),
 route_key TEXT NOT NULL,
 rule_json TEXT NOT NULL,
 environment_id TEXT NOT NULL REFERENCES platform_environment(id),
 base_id TEXT REFERENCES platform_base(id),
 workshop_id TEXT REFERENCES platform_workshop(id),
 is_head INTEGER NOT NULL CHECK (is_head IN (0,1)),
 enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
 floating INTEGER NOT NULL DEFAULT 1 CHECK (floating IN (0,1)),
 CHECK (workshop_id IS NULL OR base_id IS NOT NULL),
 PRIMARY KEY(id,revision)
);
-- sqlite-only
INSERT INTO browser_site_binding_copy (id,revision,origin,user_id,application_id,route_key,rule_json,environment_id,base_id,workshop_id,is_head,enabled)
 SELECT id,revision,origin,user_id,application_id,route_key,rule_json,environment_id,base_id,workshop_id,is_head,enabled FROM browser_workshop_binding;
-- sqlite-only
DROP TABLE browser_workshop_binding;
-- sqlite-only
ALTER TABLE browser_site_binding_copy RENAME TO browser_workshop_binding;
-- sqlite-only
CREATE UNIQUE INDEX uq_browser_workshop_binding_head ON browser_workshop_binding(origin,user_id,application_id,route_key) WHERE is_head=1;
