ALTER TABLE agent_job ADD COLUMN execution_policy_json TEXT;
ALTER TABLE agent_job ADD COLUMN execution_policy_tool_call_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_job ADD COLUMN execution_policy_exhausted INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN agent_job.execution_policy_json IS
  '创建Job时固定的v1执行策略，包含requested/effective/sources；维护迁移后强制非空且无默认值';
COMMENT ON COLUMN agent_job.execution_policy_tool_call_count IS
  '当前或最终执行attempt内进入内部MCP handler的调用尝试数';
COMMENT ON COLUMN agent_job.execution_policy_exhausted IS
  '最终执行attempt是否因执行策略耗尽而结束';
