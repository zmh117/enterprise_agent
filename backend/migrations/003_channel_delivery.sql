ALTER TABLE agent_session ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'dingding';
ALTER TABLE agent_session ADD COLUMN source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default';
ALTER TABLE agent_session ADD COLUMN external_conversation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN requester_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN requester_display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN routing_context_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agent_session ADD COLUMN reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}';

ALTER TABLE agent_job ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'dingding';
ALTER TABLE agent_job ADD COLUMN source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default';
ALTER TABLE agent_job ADD COLUMN external_event_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN requester_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN routing_context_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE agent_job ADD COLUMN reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}';

ALTER TABLE integration_connector ADD COLUMN allow_ingress INTEGER NOT NULL DEFAULT 0;
ALTER TABLE integration_connector ADD COLUMN allow_delivery INTEGER NOT NULL DEFAULT 0;
ALTER TABLE integration_connector ADD COLUMN secret_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE integration_connector ADD COLUMN endpoint_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE integration_connector ADD COLUMN host_allowlist TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS delivery_attempt (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  route_type TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  target_summary TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_delivery_attempt_job ON delivery_attempt(job_id);
CREATE INDEX IF NOT EXISTS idx_delivery_attempt_status ON delivery_attempt(status);

CREATE TABLE IF NOT EXISTS delivery_chunk (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES delivery_attempt(id),
  chunk_index INTEGER NOT NULL,
  chunk_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delivery_chunk_attempt ON delivery_chunk(attempt_id);

COMMENT ON TABLE agent_session IS 'Agent 会话表，记录一次外部 Channel 对话或请求上下文以及后续 Agent job 的会话归属';
COMMENT ON COLUMN agent_session.source_channel IS '请求来源 Channel 类型，例如 dingding、debug_api、grafana_alert';
COMMENT ON COLUMN agent_session.source_connector_id IS '来源 connector ID，用于关联入口配置、验签和审计';
COMMENT ON COLUMN agent_session.external_conversation_id IS '外部系统的会话 ID，例如钉钉会话、调试会话或告警分组';
COMMENT ON COLUMN agent_session.requester_id IS '归一化后的请求方身份，用户或服务账号均使用该字段做权限判断';
COMMENT ON COLUMN agent_session.requester_display_name IS '请求方展示名称，仅用于展示和审计摘要，不参与权限判断';
COMMENT ON COLUMN agent_session.routing_context_json IS '请求路由上下文 JSON，包含 project/environment/base/workshop/service 等诊断范围';
COMMENT ON COLUMN agent_session.reply_route_json IS '结果投递路由 JSON，描述 delivery type、connector、target 和投递选项';

COMMENT ON TABLE agent_job IS 'Agent 任务表，记录一次异步只读诊断执行请求及其状态、结果和 Channel 元数据';
COMMENT ON COLUMN agent_job.source_channel IS '创建该任务的来源 Channel 类型，例如 dingding、debug_api、grafana_alert';
COMMENT ON COLUMN agent_job.source_connector_id IS '创建该任务的来源 connector ID';
COMMENT ON COLUMN agent_job.external_event_id IS '外部系统事件 ID，用于 webhook 幂等和跨系统追踪';
COMMENT ON COLUMN agent_job.requester_id IS '归一化后的请求方身份，通常与 user_id 保持一致并用于权限和审计';
COMMENT ON COLUMN agent_job.routing_context_json IS '任务诊断范围 JSON，传递给 Agent 上下文和内部工具寻址逻辑';
COMMENT ON COLUMN agent_job.reply_route_json IS '任务结果投递路由 JSON，供 ResultDeliveryService 发送成功报告或失败通知';

COMMENT ON TABLE integration_connector IS '集成连接器配置表，记录内部工具平台、Channel 入口和 Delivery 出口的连接配置';
COMMENT ON COLUMN integration_connector.allow_ingress IS '是否允许该 connector 作为 Channel 入站来源，1 表示允许，0 表示禁止';
COMMENT ON COLUMN integration_connector.allow_delivery IS '是否允许该 connector 作为结果投递出口，1 表示允许，0 表示禁止';
COMMENT ON COLUMN integration_connector.secret_ref IS 'connector 密钥引用，可指向环境变量或受控密钥配置，不应存放明文敏感值';
COMMENT ON COLUMN integration_connector.endpoint_ref IS 'connector 目标地址引用，可指向环境变量或受控配置';
COMMENT ON COLUMN integration_connector.host_allowlist IS '允许投递的目标 host 白名单，多个 host 使用逗号分隔';

COMMENT ON TABLE delivery_attempt IS '结果投递尝试表，记录 Agent job 最终报告或失败通知的一次投递过程';
COMMENT ON COLUMN delivery_attempt.id IS '投递尝试 ID';
COMMENT ON COLUMN delivery_attempt.job_id IS '关联的 Agent job ID';
COMMENT ON COLUMN delivery_attempt.route_type IS '投递路由类型，例如 none、dingtalk_webhook_robot、dingtalk_enterprise_robot、email、webhook';
COMMENT ON COLUMN delivery_attempt.connector_id IS '投递使用的 connector ID，none 路由可为空';
COMMENT ON COLUMN delivery_attempt.target_summary IS '投递目标安全摘要 JSON，不包含 token、secret 或完整敏感 URL';
COMMENT ON COLUMN delivery_attempt.status IS '投递尝试状态，例如 STARTED、SUCCEEDED、FAILED、SKIPPED';
COMMENT ON COLUMN delivery_attempt.error_message IS '安全错误摘要，投递成功时为空';
COMMENT ON COLUMN delivery_attempt.created_at IS '投递尝试创建时间';
COMMENT ON COLUMN delivery_attempt.finished_at IS '投递尝试完成时间，未完成时为空';

COMMENT ON TABLE delivery_chunk IS '结果投递分片表，记录长报告按目标平台限制拆分后的每个发送分片';
COMMENT ON COLUMN delivery_chunk.id IS '投递分片 ID';
COMMENT ON COLUMN delivery_chunk.attempt_id IS '关联的 delivery_attempt ID';
COMMENT ON COLUMN delivery_chunk.chunk_index IS '分片序号，从 1 开始';
COMMENT ON COLUMN delivery_chunk.chunk_count IS '本次投递总分片数';
COMMENT ON COLUMN delivery_chunk.status IS '分片发送状态，例如 SUCCEEDED 或 FAILED';
COMMENT ON COLUMN delivery_chunk.payload_summary IS '分片内容安全摘要 JSON，记录标题、长度等非敏感信息';
COMMENT ON COLUMN delivery_chunk.error_message IS '分片发送失败时的安全错误摘要';
COMMENT ON COLUMN delivery_chunk.created_at IS '分片记录创建时间';
