CREATE TABLE browser_live_job_page (
 job_id TEXT PRIMARY KEY REFERENCES agent_job(id),
 binding_id TEXT NOT NULL,
 revision INTEGER NOT NULL,
 recording_id TEXT,
 tab_id TEXT,
 document_id TEXT NOT NULL,
 asked_ms BIGINT NOT NULL,
 timezone TEXT NOT NULL,
 FOREIGN KEY(binding_id,revision) REFERENCES browser_workshop_binding(id,revision),
 FOREIGN KEY(recording_id,tab_id,document_id) REFERENCES browser_live_page(recording_id,tab_id,document_id),
 CHECK ((recording_id IS NULL AND tab_id IS NULL) OR (recording_id IS NOT NULL AND tab_id IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE browser_live_job_page IS '提问时冻结的浏览器文档范围';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.job_id IS '任务';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.binding_id IS '页面绑定';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.revision IS '绑定版本';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.recording_id IS '当前页参与的录制';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.tab_id IS '录制内的标签身份';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.document_id IS 'Chrome 顶层文档';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.asked_ms IS '提问时刻毫秒';
-- postgres-only
COMMENT ON COLUMN browser_live_job_page.timezone IS '用户时区';
