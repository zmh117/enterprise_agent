ALTER TABLE agent_session ADD COLUMN session_key TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN conversation_type TEXT NOT NULL DEFAULT 'direct';
ALTER TABLE agent_session ADD COLUMN bot_identity TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN summary_text TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN summary_through_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_session ADD COLUMN summary_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_session ADD COLUMN message_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_session ADD COLUMN last_message_at TEXT;

UPDATE agent_session SET session_key = 'legacy:' || id WHERE session_key = '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_session_key ON agent_session(session_key);

ALTER TABLE agent_message ADD COLUMN external_message_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_message ADD COLUMN sender_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_message ADD COLUMN sender_display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_message ADD COLUMN message_type TEXT NOT NULL DEFAULT 'text';
ALTER TABLE agent_message ADD COLUMN sequence_no INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_message ADD COLUMN content_status TEXT NOT NULL DEFAULT 'READY';
ALTER TABLE agent_message ADD COLUMN safe_metadata_json TEXT NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_message_external
  ON agent_message(session_id, external_message_id)
  WHERE external_message_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_message_sequence
  ON agent_message(session_id, sequence_no)
  WHERE sequence_no > 0;

CREATE TABLE IF NOT EXISTS message_attachment (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES agent_message(id),
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  ordinal INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  declared_mime TEXT NOT NULL DEFAULT '',
  detected_mime TEXT NOT NULL DEFAULT '',
  declared_size INTEGER,
  size_bytes INTEGER,
  sha256 TEXT NOT NULL DEFAULT '',
  object_bucket TEXT NOT NULL DEFAULT '',
  object_key TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  failure_code TEXT NOT NULL DEFAULT '',
  retry_count INTEGER NOT NULL DEFAULT 0,
  source_credential_ciphertext TEXT NOT NULL DEFAULT '',
  source_credential_type TEXT NOT NULL DEFAULT '',
  source_credential_expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  expires_at TEXT,
  UNIQUE(message_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_message_attachment_job ON message_attachment(job_id);
CREATE INDEX IF NOT EXISTS idx_message_attachment_status ON message_attachment(status);

CREATE TABLE IF NOT EXISTS attachment_content (
  id TEXT PRIMARY KEY,
  attachment_id TEXT NOT NULL UNIQUE REFERENCES message_attachment(id),
  plain_text TEXT NOT NULL,
  segments_json TEXT NOT NULL DEFAULT '[]',
  parser_version TEXT NOT NULL,
  char_count INTEGER NOT NULL DEFAULT 0,
  truncated INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

COMMENT ON TABLE message_attachment IS '钉钉多模态消息附件元数据和安全处理状态；原始二进制保存在私有对象存储';
COMMENT ON COLUMN message_attachment.source_credential_ciphertext IS '短期媒体来源凭证密文，下载终态或过期后必须清除';
COMMENT ON TABLE attachment_content IS '附件受限解析产生的有界纯文本和分段索引';
