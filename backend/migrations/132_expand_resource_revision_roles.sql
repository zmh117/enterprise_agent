-- Preserve the historical identity selector without changing published hashes.
ALTER TABLE platform_resource_draft
  ADD COLUMN placement TEXT NOT NULL DEFAULT '';
ALTER TABLE platform_resource_revision
  ADD COLUMN placement TEXT NOT NULL DEFAULT '';

UPDATE platform_resource_draft
SET placement = COALESCE((SELECT placement FROM platform_resource
                         WHERE platform_resource.id = platform_resource_draft.resource_id), '');
UPDATE platform_resource_revision
SET placement = COALESCE((SELECT placement FROM platform_resource
                         WHERE platform_resource.id = platform_resource_revision.resource_id), '');

-- Old draft hashes did not cover the role. Save and verify again before publish.
UPDATE platform_resource_draft SET status = 'DRAFT';

-- postgres-only
COMMENT ON COLUMN platform_resource_draft.placement IS
  '可自定义资源角色；保存后纳入内容哈希，验证发布前不影响运行解析';
-- postgres-only
COMMENT ON COLUMN platform_resource_revision.placement IS
  '已发布版本的精确资源角色选择值；空值未指定，不属于授权维度';
