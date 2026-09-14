# 验证与部署说明（2026-09-14）

## 修复范围

- Environment/Base 表单联动仅为非 Loki 资源重置 Workshop 字段。
- 新建 POST 和编辑 Draft PUT 共用请求清理逻辑，仅从 Loki 范围副本移除空 Workshop 占位值。
- 不改变顶层资源身份、Selector、数据库/Redis 的 Workshop/前缀字段，不放宽后端字段校验。

## 验证结果

- 修复前，新增测试复现 6 个失败：两个范围切换场景，以及新建/编辑请求携带空串或 null 的 Workshop 字段。
- 前端专项测试：32 项通过，覆盖全局/环境级 Loki 范围的 Environment/Base 选择、清空 Base、label 发现及精确 selector 保存。
- 前端全量 `npm test`：15 个测试文件、152 项通过。
- 后端相关回归：`test_resource_scope_bindings.py`、`test_governed_tool_resource_api.py`、`test_governed_tool_resource_lifecycle.py` 合计 32 项通过、1 项跳过；跳过项需要外部 PostgreSQL 测试库。
- `npm run lint`、`npm run build`（包含 TypeScript 项目构建）、相关 Python Ruff 检查通过。
- `docker compose config --quiet`、严格 OpenSpec 验证、`git diff --check` 通过。
- 构建保留现有 Vite 配置兼容及大 chunk 提示，无新增依赖或配置调整。

## 部署与真实验收边界

本次没有重启运行中的服务，没有读取或修改真实凭据、资源 Draft、发布版本或 Loki 数据。前端交互测试使用模拟 HTTP，后端契约测试使用本地测试环境，不代表用户资源已经保存成功。

无需数据库迁移、无需更新后端、无需归档重建资源。部署机器取得本次代码后，更新前端即可：

```bash
docker compose build admin-web
docker compose up -d --no-deps admin-web
```

刷新浏览器以载入新前端，重新打开原 Loki Draft，按需选择 Environment/Base、保留有效精确 selector 后保存。请求中的 `scope_bindings` 应不再含空 `workshop_code`。保存后仍按原流程重新技术验证和发布，不自动发布。
