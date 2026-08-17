-- Publish connection facts and data-scope bindings in one immutable Resource
-- Revision. Existing rows retain an empty list and must be republished before
-- Workshop-partitioned or Loki runtime use.

ALTER TABLE platform_resource_draft
  ADD COLUMN scope_bindings_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE platform_resource_revision
  ADD COLUMN scope_bindings_json TEXT NOT NULL DEFAULT '[]';

-- postgres-only
COMMENT ON COLUMN platform_resource_draft.scope_bindings_json IS
  '当前工具资源草稿的数据范围绑定；与连接配置共享内容哈希、验证和发布生命周期';

-- postgres-only
COMMENT ON COLUMN platform_resource_revision.scope_bindings_json IS
  '不可变工具资源版本内的数据库表前缀、Redis namespace 或 Loki exact selector bindings';
