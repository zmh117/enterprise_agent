CREATE TABLE browser_recording (
    id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES app_user(id),
    application_id TEXT NOT NULL REFERENCES business_application(id),
    publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
    scope_ref TEXT NOT NULL,
    local_recording_id TEXT NOT NULL,
    checkpoint BIGINT NOT NULL CHECK (checkpoint >= 0),
    projection_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('uploading','ready','upload_expired','expired')),
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    UNIQUE (id, scope_ref)
);
CREATE UNIQUE INDEX browser_recording_version ON browser_recording
    (scope_ref, local_recording_id, checkpoint, projection_version) WHERE state <> 'upload_expired';
CREATE INDEX browser_recording_expiry ON browser_recording(state, expires_at);
CREATE INDEX browser_recording_owner ON browser_recording(origin, user_id, state);

CREATE TABLE browser_recording_upload_attempt (
    scope_ref TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    PRIMARY KEY (scope_ref, attempt_id),
    FOREIGN KEY (recording_id, scope_ref) REFERENCES browser_recording(id, scope_ref) ON DELETE CASCADE
);

CREATE TABLE browser_recording_part (
    recording_id TEXT NOT NULL REFERENCES browser_recording(id) ON DELETE CASCADE,
    part_number INTEGER NOT NULL CHECK (part_number >= 0),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL,
    received_at BIGINT,
    PRIMARY KEY (recording_id, part_number)
);

CREATE TABLE browser_recording_evidence (
    recording_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('request','action')),
    source_id TEXT NOT NULL,
    offset_ms BIGINT NOT NULL CHECK (offset_ms >= 0),
    part_number INTEGER NOT NULL,
    line_number INTEGER NOT NULL CHECK (line_number >= 0),
    path_template TEXT,
    method TEXT,
    http_status INTEGER,
    business_outcome TEXT,
    action TEXT,
    PRIMARY KEY (recording_id, kind, source_id),
    UNIQUE (recording_id, part_number, line_number),
    FOREIGN KEY (recording_id, part_number) REFERENCES browser_recording_part(recording_id, part_number) ON DELETE CASCADE
);
CREATE INDEX browser_evidence_time ON browser_recording_evidence(recording_id, offset_ms, kind, source_id);
CREATE INDEX browser_evidence_kind ON browser_recording_evidence(recording_id, kind, offset_ms, source_id);
CREATE INDEX browser_evidence_status ON browser_recording_evidence(recording_id, http_status, offset_ms, source_id);
CREATE INDEX browser_evidence_path ON browser_recording_evidence(recording_id, path_template, method, offset_ms, source_id);
CREATE INDEX browser_evidence_outcome ON browser_recording_evidence(recording_id, business_outcome, offset_ms, source_id);
CREATE INDEX browser_evidence_action ON browser_recording_evidence(recording_id, action, offset_ms, source_id);

CREATE TABLE browser_recording_association (
    recording_id TEXT NOT NULL REFERENCES browser_recording(id) ON DELETE CASCADE,
    request_key TEXT NOT NULL,
    action_id TEXT NOT NULL,
    basis TEXT NOT NULL CHECK (basis IN ('observed','time_proximity')),
    PRIMARY KEY (recording_id, request_key, action_id, basis)
);
CREATE INDEX browser_association_action ON browser_recording_association(recording_id, action_id, request_key);

CREATE TABLE browser_session_recording (
    session_id TEXT PRIMARY KEY REFERENCES agent_session(id) ON DELETE CASCADE,
    recording_id TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    FOREIGN KEY (recording_id, scope_ref) REFERENCES browser_recording(id, scope_ref)
);
CREATE TABLE browser_job_recording (
    job_id TEXT PRIMARY KEY REFERENCES browser_message_receipt(job_id) ON DELETE CASCADE,
    recording_id TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    FOREIGN KEY (recording_id, scope_ref) REFERENCES browser_recording(id, scope_ref)
);

-- postgres-only
COMMENT ON TABLE browser_recording IS '具有独立保留期和授权范围的封存录制版本';
-- postgres-only
COMMENT ON COLUMN browser_recording.id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_recording.origin IS '平台来源';
-- postgres-only
COMMENT ON COLUMN browser_recording.user_id IS '录制所属内部用户';
-- postgres-only
COMMENT ON COLUMN browser_recording.application_id IS '业务应用';
-- postgres-only
COMMENT ON COLUMN browser_recording.publication_id IS '确认共享时的应用发布';
-- postgres-only
COMMENT ON COLUMN browser_recording.scope_ref IS '用户和应用发布等授权边界的摘要';
-- postgres-only
COMMENT ON COLUMN browser_recording.local_recording_id IS '本地封存录制标识';
-- postgres-only
COMMENT ON COLUMN browser_recording.checkpoint IS '本地持久化检查点';
-- postgres-only
COMMENT ON COLUMN browser_recording.projection_version IS '投影格式版本';
-- postgres-only
COMMENT ON COLUMN browser_recording.manifest_digest IS '稳定清单摘要';
-- postgres-only
COMMENT ON COLUMN browser_recording.coverage_json IS '已核验结构的源端覆盖统计';
-- postgres-only
COMMENT ON COLUMN browser_recording.state IS '上传、就绪或到期状态';
-- postgres-only
COMMENT ON COLUMN browser_recording.created_at IS '创建时间的 UTC 秒数';
-- postgres-only
COMMENT ON COLUMN browser_recording.expires_at IS '暂存或已发布内容到期的 UTC 秒数';

-- postgres-only
COMMENT ON TABLE browser_recording_upload_attempt IS '上传尝试到原录制版本的幂等回执';
-- postgres-only
COMMENT ON COLUMN browser_recording_upload_attempt.scope_ref IS '用户和应用发布等授权边界的摘要';
-- postgres-only
COMMENT ON COLUMN browser_recording_upload_attempt.attempt_id IS '由插件在用户确认时生成的尝试标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_upload_attempt.recording_id IS '录制版本标识';

-- postgres-only
COMMENT ON TABLE browser_recording_part IS '清单内的分片与已提交回执';
-- postgres-only
COMMENT ON COLUMN browser_recording_part.recording_id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_part.part_number IS '从零开始的分片序号';
-- postgres-only
COMMENT ON COLUMN browser_recording_part.size_bytes IS '清单声明的展开字节数';
-- postgres-only
COMMENT ON COLUMN browser_recording_part.sha256 IS '展开字节的 SHA-256';
-- postgres-only
COMMENT ON COLUMN browser_recording_part.received_at IS '分片提交时间的 UTC 秒数';

-- postgres-only
COMMENT ON TABLE browser_recording_evidence IS '请求和操作的可检索索引';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.recording_id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.kind IS '请求或操作';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.source_id IS '采集器的唯一证据标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.offset_ms IS '相对录制开始的毫秒数';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.part_number IS '从零开始的分片序号';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.line_number IS '从零开始的分片行序号';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.path_template IS '可安全显示的路径模板';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.method IS 'HTTP 方法';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.http_status IS 'HTTP 状态码';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.business_outcome IS '独立于 HTTP 状态的业务结果';
-- postgres-only
COMMENT ON COLUMN browser_recording_evidence.action IS '操作类型';

-- postgres-only
COMMENT ON TABLE browser_recording_association IS '请求与操作的观测或时间邻近关系';
-- postgres-only
COMMENT ON COLUMN browser_recording_association.recording_id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_association.request_key IS '请求源标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_association.action_id IS '操作源标识';
-- postgres-only
COMMENT ON COLUMN browser_recording_association.basis IS '关联的依据';

-- postgres-only
COMMENT ON TABLE browser_session_recording IS '插件会话当前选择的录制';
-- postgres-only
COMMENT ON COLUMN browser_session_recording.session_id IS '已受理的插件会话';
-- postgres-only
COMMENT ON COLUMN browser_session_recording.recording_id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_session_recording.scope_ref IS '用户和应用发布等授权边界的摘要';

-- postgres-only
COMMENT ON TABLE browser_job_recording IS '已受理插件问题冻结的录制版本';
-- postgres-only
COMMENT ON COLUMN browser_job_recording.job_id IS '已受理的插件任务';
-- postgres-only
COMMENT ON COLUMN browser_job_recording.recording_id IS '录制版本标识';
-- postgres-only
COMMENT ON COLUMN browser_job_recording.scope_ref IS '用户和应用发布等授权边界的摘要';
