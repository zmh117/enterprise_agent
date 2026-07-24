ALTER TABLE agent_session ADD COLUMN business_application_id TEXT;
ALTER TABLE agent_session ADD COLUMN business_application_code TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_session ADD COLUMN conversation_mode TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE agent_session ADD COLUMN recent_message_limit INTEGER;
ALTER TABLE agent_session ADD COLUMN session_policy_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_agent_session_business_application
  ON agent_session(business_application_id, updated_at);

ALTER TABLE agent_job ADD COLUMN business_application_id TEXT;
ALTER TABLE agent_job ADD COLUMN business_application_code TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN business_application_publication_id TEXT;
ALTER TABLE agent_job ADD COLUMN business_application_deployment_id TEXT;
ALTER TABLE agent_job ADD COLUMN business_application_route_id TEXT;
ALTER TABLE agent_job ADD COLUMN business_application_config_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN business_application_runtime_status TEXT NOT NULL DEFAULT '';
ALTER TABLE agent_job ADD COLUMN business_application_route_decision_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_agent_job_business_application
  ON agent_job(business_application_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_job_business_application_publication
  ON agent_job(business_application_publication_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_job_business_application_deployment
  ON agent_job(business_application_deployment_id, created_at);

COMMENT ON COLUMN agent_session.business_application_id IS '稳定业务应用ID，用于隔离连续会话；历史会话为空';
COMMENT ON COLUMN agent_session.session_policy_json IS '创建会话时固定的业务应用会话策略安全摘要';
COMMENT ON COLUMN agent_job.business_application_id IS '创建Job时命中的稳定业务应用ID；历史或兼容路径为空';
COMMENT ON COLUMN agent_job.business_application_publication_id IS '创建Job时固定的不可变业务应用Publication';
COMMENT ON COLUMN agent_job.business_application_route_id IS '创建Job时命中的活动route ID，仅作历史来源，不建立会被停用删除的外键';
COMMENT ON COLUMN agent_job.business_application_route_decision_json IS '脱敏的运行时路由决策和组件状态摘要';
