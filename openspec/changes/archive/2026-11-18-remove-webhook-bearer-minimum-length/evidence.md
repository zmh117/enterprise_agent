# 验证记录

日期：2026-11-07。本次验证在本地 checkout 与 Compose 环境完成。

- 后端相关 Webhook 测试 53 项通过：`test_webhook_optional_authentication.py`、`test_webhook_trigger_service.py`、`test_webhook_mapping_security.py`、`test_webhook_ingress_dispatch.py`。
- 合成凭据分别使用 1、31、4096 字符，通过草稿保存、校验、发布、渠道 READY 与公共接口 202 接受；错误和缺失 Bearer 返回 401。非法格式、不可解析凭据与唯一绑定检查仍通过。
- 前端 Webhook 设置测试 8 项通过；相关 ESLint、TypeScript 和 Vite 构建通过。构建保留已有 bundle 大小提示。
- Ruff、`git diff --check`、OpenSpec strict 校验通过。
- 本地重建并更新 `api-server`、`webhook-worker`、`admin-web`；更新前未发现处于查询所列等待或运行状态的 Agent Job。
- 运行中的 API 镜像通过独立 Mock 凭据的短 Token 校验与鉴权检查，`/api/ready` 返回 HTTP 200；实际提供的管理前端静态资源已移除旧长度提示。

边界：未读取或修改真实 Token，未改绑、保存或发布用户的 Webhook 配置，未触发真实 Agent 或外部消息投递。短 Token 的发布与公共 HTTP 接受证据来自隔离测试；容器检查使用合成凭据。
