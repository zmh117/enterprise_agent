CREATE TABLE browser_live_evidence_part (
 recording_id TEXT NOT NULL,
 tab_id TEXT NOT NULL,
 document_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 part_number INTEGER NOT NULL,
 part_digest TEXT NOT NULL,
 event_digest TEXT NOT NULL,
 event_bytes INTEGER NOT NULL,
 part_count INTEGER NOT NULL,
 source_seq INTEGER NOT NULL,
 observed_ms BIGINT NOT NULL,
 received_ns BIGINT NOT NULL,
 kind TEXT NOT NULL,
 PRIMARY KEY(recording_id,event_id,part_number),
 FOREIGN KEY(recording_id,tab_id,document_id) REFERENCES browser_live_page(recording_id,tab_id,document_id)
);
CREATE INDEX ix_browser_live_page_time ON browser_live_evidence_part(recording_id,tab_id,observed_ms,event_id);
CREATE INDEX ix_browser_live_recording_arrivals ON browser_live_evidence_part(recording_id,received_ns,event_id) WHERE part_number=0;
-- postgres-only
COMMENT ON TABLE browser_live_evidence_part IS '已接收分片的核对清单';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.recording_id IS '录制';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.tab_id IS '录制内标签实例';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.document_id IS '顶层文档';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.event_id IS '稳定事件身份';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.part_number IS '分片序号';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.part_digest IS '当前分片摘要';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.event_digest IS '完整事件摘要';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.event_bytes IS '完整事件字节数';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.part_count IS '期望分片总数';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.source_seq IS '录制内源序号';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.observed_ms IS '浏览器观察时间毫秒';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.received_ns IS '平台接收时间纳秒';
-- postgres-only
COMMENT ON COLUMN browser_live_evidence_part.kind IS '事件类别';
