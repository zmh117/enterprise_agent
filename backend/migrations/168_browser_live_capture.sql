CREATE TABLE browser_live_recording (
 id TEXT PRIMARY KEY,
 origin TEXT NOT NULL,
 user_id TEXT NOT NULL REFERENCES app_user(id),
 application_id TEXT NOT NULL REFERENCES business_application(id),
 scope_ref TEXT NOT NULL,
 started_at TEXT NOT NULL
);
CREATE INDEX ix_browser_live_owner ON browser_live_recording(origin,user_id,application_id,started_at);
CREATE TABLE browser_live_page (
 recording_id TEXT NOT NULL REFERENCES browser_live_recording(id),
 tab_id TEXT NOT NULL,
 document_id TEXT NOT NULL,
 binding_id TEXT NOT NULL,
 revision INTEGER NOT NULL,
 PRIMARY KEY(recording_id,tab_id,document_id),
 FOREIGN KEY(binding_id,revision) REFERENCES browser_workshop_binding(id,revision)
);
-- postgres-only
COMMENT ON TABLE browser_live_recording IS '持续采集的授权登记者';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.id IS '录制身份';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.origin IS '认证来源';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.user_id IS '录制所有者';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.application_id IS '业务应用';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.scope_ref IS '应用发布范围摘要';
-- postgres-only
COMMENT ON COLUMN browser_live_recording.started_at IS '服务端登记时间';
-- postgres-only
COMMENT ON TABLE browser_live_page IS '持续采集顶层文档不可变的车间绑定';
-- postgres-only
COMMENT ON COLUMN browser_live_page.recording_id IS '录制身份';
-- postgres-only
COMMENT ON COLUMN browser_live_page.tab_id IS '录制内的标签实例';
-- postgres-only
COMMENT ON COLUMN browser_live_page.document_id IS '顶层浏览器文档身份';
-- postgres-only
COMMENT ON COLUMN browser_live_page.binding_id IS '已授权的页面规则';
-- postgres-only
COMMENT ON COLUMN browser_live_page.revision IS '文档登记时有效的规则版本';
