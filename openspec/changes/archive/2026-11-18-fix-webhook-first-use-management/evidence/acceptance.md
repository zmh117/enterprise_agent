# Webhook 首次配置修复验收

2026-10-25，修复代码、隔离验收和实际本地 Compose 部署验收完成，9/9 项任务完成。修复已部署到 `http://localhost:8080`；未提交、未推送、未归档。

## 原因与结果

初始只读查询确认：运行数据库只有一个钉钉 Stream Connector，Webhook 定义为 0。原页面强制选择已有入口并禁止空目录创建，后端也只登记依附于现有 Connector 的定义，卡片没有后续编辑入口。

现在 Web 创建会原子建立独立 managed_webhook 入站 Connector、服务账号和停用定义，并打开配置面板。通过现有 API 完成认证引用、映射、路由、Agent 发布选择、投递、限额、保存、校验、预览、发布及启停。创建失败回滚；未发布不能启用；未保存编辑不能操作旧草稿；none 投递无需虚构 Connector。用户仍需显式授权 Agent 和服务账号，系统不自动扩大业务权限。

## 验证结果

- 后端 38 项通过：`test_webhook_api.py`、`test_webhook_trigger_service.py`、`test_managed_multi_dingtalk_runtime.py`、`test_webhook_mapping_security.py`、`test_webhook_ingress_dispatch.py`、`test_webhook_architecture.py` 共 34 项；Outbox 与迁移/服务账号回归另 4 项。最终目录兼容修正后再次运行 API 5 项通过。
- 前端 3 个测试文件共 11 项通过：渠道页面/导航及新的首次配置交互回归。覆盖无入口创建、校验发布启停、未保存保护、错误 JSON、revision 冲突时保留输入。
- Ruff、变更 Python 源码 mypy、变更前端 ESLint、TypeScript/Vite 构建、Compose 配置和严格 OpenSpec 校验通过；`git diff --check` 通过。Vite 仍提示已有主包超过 500 kB，不影响构建，本次没有扩展成打包优化。
- 实际 Chromium + Playwright CLI，真实应用 API + 独立 SQLite：通用 JSON 创建、保存、缺少 Agent 入口授权时校验失败、显式合成 fixture 授权后校验通过、预览、发布、启用、停用、重开持久配置，以及 Grafana 首次创建与模板均通过。数据库核对 preview 后 Event=0、Job=0。详见 [结构化记录](browser-acceptance.json) 和 [页面截图](webhook-settings.png)。
- 浏览器验收发现并修复 HTML pattern 在 Unicode v 模式下的连字符转义和侧栏宽度优先级；最终实测桌面面板宽度 768 px。Vite 文件监听未及时刷新时重启本次独立测试服务器，再加载最终源码核对。
- 上述隔离验收的 Token、账号、消息和数据库均为合成 fixture，没有对既有数据库执行写入。后续经用户明确授权，在实际 Compose 库新增独立合成测试配置，范围和清理见下节。两个阶段均无真实 Provider 调用，未读取、复制或修改现有真实凭据；不把发布或 HTTP 202 当作业务执行成功，不覆盖公网 HTTPS 或生产调用。
- 已正常关闭本次浏览器和 API/Vite 测试服务，确认记录的 PID 已退出、15178/18765 端口不再监听。详见 [清理记录](cleanup.json)。

## 使用方式

1. 在“业务应用 → 渠道与触发器”点击“新建 Webhook”，填写编码、名称，选择通用 JSON 或 Grafana，点击“创建并配置 Webhook”。
2. 在凭据中心创建独立的强 Bearer Token，这里只填写或选择 `secret://platform/...` 引用；勿使用同一 Token 发布多个 Webhook。
3. 在 Agent 配置中分配新生成的“Webhook · 编码”入口并发布 Agent；回到 Webhook 点击“刷新配置目录”，选择该发布版本。
4. 配置消息映射与路由，选择结果投递（可为“不投递结果”），保存草稿、校验、用合成报文预览，发布并启用。
5. 在业务应用中绑定此 Webhook，为其服务账号分配业务角色和范围。界面显示的接收路径配合 `Authorization: Bearer` 使用。未完成应用绑定与授权时，不保证事件进入业务执行。

## 实际本地 Compose 部署验收

用户随后明确授权恢复本地 Compose、部署修复并用合成数据验收。恢复前 PostgreSQL、RabbitMQ、API、Web 等容器均已退出，时间集中在 `2026-10-25T06:58:20Z` 附近；无 OOM 标志，磁盘剩余约 271 GiB。未确定是谁或什么操作停止了这些服务。启动原有 PostgreSQL、RabbitMQ、MinIO 后恢复依赖；重建受影响的后端镜像与 admin-web，执行 `docker compose up -d --no-build`。两个长期运行的 Runtime 在数据库恢复后仍报告数据库不可用，分别重启后 `/ready` 和健康检查恢复。未删除数据卷、未导入 seed、未更换配置凭据；数据库版本仍为 147。

- 部署核对：23 个常驻容器运行，其中 20 个有 Docker 健康检查且全部 healthy；admin-web 和两个 agent-worker 没有 Docker 健康检查，实际 Web 流程通过。migrator 与 minio-init 两个一次性任务均退出 0。部署 API 的 7 个变更源码文件 SHA-256 与工作区一致。
- 浏览器使用实际 `http://localhost:8080/applications/channels`，通用 JSON Webhook 的 13 个场景通过：首次创建、未发布启用门禁、保存认证/映射/路由/Agent/none 投递/限额、缺少 Agent 入口授权时拒绝、未保存保护、校验、预览、发布、启用、未认证请求拒绝、停用、停用后拒绝正确合成凭据、关闭重开持久配置。
- 新建编码 `synthetic-compose-webhook-20261025`，独立入口为 managed_webhook、ingress=1、delivery=0、secret_ref 为空。新建合成 Agent 的 r1 未分配入口，校验正确拒绝；显式分配新入口并发布该合成 Agent 的 r2 后，Webhook 草稿 r2 校验通过并发布。没有修改现有 Agent 发布。
- 预览前后 Event=0、Job=224，预览返回 `side_effects=false`。之后对已启用入口发送未认证合成请求，得到 `401 webhook_auth_failed`，按既有协议留下 1 条 REJECTED_AUTH 事件且无 Job；停用后携带正确合成凭据得到 `401 webhook_disabled`。最终 Event=1（仅该拒绝记录）、Job=224，合成 Agent Job=0。没有进行已认证事件分发或业务应用执行。
- 持久化发布保留冷却 0 秒、每分钟请求 5、最大在途 1、none 投递；启用时定义 r3、停用时 r4，关闭重开显示草稿/发布 r2 和已停用状态。
- 凭据保护：仅对数据库内摘要进行比较，不返回密文或明文。原有 7 个受管凭据的 metadata/版本/密文摘要、3 个人员密码记录、2 个外部身份凭据记录均与测试前一致。支持 fixture 的合成凭据与 Agent 由正常应用服务创建；临时验收管理员单独建立并记录审计，没有使用或重置现有账号密码。
- 清理：合成 Webhook、入口 Connector、服务账号、Agent、合成凭据和临时管理员均已停用；临时管理员角色停用、会话撤销、临时密码记录删除。保留合成定义、发布、拒绝事件及审计以便复核。本次 Playwright 会话正常关闭，记录的浏览器、daemon 和 6 个辅助 PID 全部退出，未操作用户浏览器。

结构化结果：[Compose 验收](compose-acceptance.json)。页面证据：[已发布并启用](compose-webhook-published-enabled.png)、[重开后已停用](compose-webhook-published-disabled.png)。Grafana 创建/模板沿用前述隔离浏览器证据，本轮实际部署验收覆盖通用 JSON 完整流程。当前 admin-web Nginx 代理管理 API，公开接收端口使用 API origin `http://localhost:8000`；公网 HTTPS、业务授权、真实 Provider 与结果投递不在本轮验收范围内。
