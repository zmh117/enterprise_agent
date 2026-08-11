ALTER TABLE agent_definition
  ADD COLUMN runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1'));

ALTER TABLE agent_publication
  ADD COLUMN runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1'));

CREATE INDEX IF NOT EXISTS idx_agent_definition_runtime_kind
  ON agent_definition(runtime_kind, status);
CREATE INDEX IF NOT EXISTS idx_agent_publication_runtime_kind
  ON agent_publication(runtime_kind, status);

COMMENT ON COLUMN agent_definition.runtime_kind IS
  'Agent创建后不可变的执行Runtime；只能为python-v1或typescript-v1';
COMMENT ON COLUMN agent_publication.runtime_kind IS
  '发布时从Agent Definition冻结的Runtime投影；legacy schema v1确定性回填python-v1';
