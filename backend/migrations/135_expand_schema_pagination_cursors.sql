CREATE TABLE mcp_schema_pagination_cursor (
    job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
    reference TEXT NOT NULL CHECK (length(reference) = 19),
    original_cursor TEXT NOT NULL CHECK (length(original_cursor) BETWEEN 1 AND 4096),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (job_id, reference),
    CHECK (expires_at > created_at)
);

CREATE INDEX idx_schema_pagination_cursor_expiry ON mcp_schema_pagination_cursor(expires_at);

-- postgres-only
COMMENT ON TABLE mcp_schema_pagination_cursor IS 'Schema 分页临时状态；短引用不是授权凭据，恢复后仍校验原始游标';
-- postgres-only
COMMENT ON COLUMN mcp_schema_pagination_cursor.job_id IS '唯一所属 Job；仅运行中任务可签发和恢复，删除 Job 级联删除';
-- postgres-only
COMMENT ON COLUMN mcp_schema_pagination_cursor.reference IS 'pg_ 加随机十六位十六进制字符；模型仅续传此短引用';
-- postgres-only
COMMENT ON COLUMN mcp_schema_pagination_cursor.original_cursor IS '内部有界原始游标，绑定上下文、请求和资源修订；不含认证材料';
-- postgres-only
COMMENT ON COLUMN mcp_schema_pagination_cursor.created_at IS '服务端 UTC 创建时间';
-- postgres-only
COMMENT ON COLUMN mcp_schema_pagination_cursor.expires_at IS '服务端 UTC 到期时间；24 小时有效，定期有界清理';
