-- 自动内容换版只可沿用管理员显式启用时的已发布资源配置。
-- postgres-only
ALTER TABLE knowledge.sync_binding ADD COLUMN resource_pins_json JSONB NOT NULL DEFAULT '{}'::jsonb;
-- sqlite-only
ALTER TABLE "knowledge.sync_binding" ADD COLUMN resource_pins_json TEXT NOT NULL DEFAULT '{}';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.resource_pins_json IS '启用时冻结的知识资源发布身份与配置摘要；自动换版时同事务更新，不含凭据明文';
