CREATE TABLE browser_workshop_binding (
 id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK (revision >= 1),
 origin TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES app_user(id),
 application_id TEXT NOT NULL REFERENCES business_application(id),
 route_key TEXT NOT NULL,
 rule_json TEXT NOT NULL,
 environment_id TEXT NOT NULL REFERENCES platform_environment(id),
 base_id TEXT NOT NULL REFERENCES platform_base(id),
 workshop_id TEXT NOT NULL REFERENCES platform_workshop(id),
 is_head INTEGER NOT NULL CHECK (is_head IN (0,1)),
 enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
 PRIMARY KEY(id,revision)
);
CREATE UNIQUE INDEX uq_browser_workshop_binding_head ON browser_workshop_binding
 (origin,user_id,application_id,route_key) WHERE is_head=1;
-- postgres-only
COMMENT ON TABLE browser_workshop_binding IS '插件页面与车间绑定的版本历史';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.id IS '绑定身份';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.revision IS '绑定版本';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.origin IS '平台来源';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.user_id IS '内部用户';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.application_id IS '业务应用';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.route_key IS '规范化页面规则摘要';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.rule_json IS '已选定位字段组成的匹配规则';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.environment_id IS '环境标识';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.base_id IS '基地标识';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.workshop_id IS '车间标识';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.is_head IS '当前版本标记';
-- postgres-only
COMMENT ON COLUMN browser_workshop_binding.enabled IS '启用标记';
