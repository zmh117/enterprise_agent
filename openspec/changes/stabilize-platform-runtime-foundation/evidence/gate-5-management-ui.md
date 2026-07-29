# Gate 5：管理 API 与界面

记录日期：2026-07-29

Phase 5（任务 9.*）状态：**PASS**

聚合 Gate 5 状态：**BLOCKED**。检查器按设计同时包含任务 9.* 和维护窗口任务
10.*；本证据只完成了管理 API/UI 子阶段，未执行 10.1–10.9 的备份、旧授权/
RabbitMQ 清理和验收资源发布。

## 实现结果

- “平台治理 → 凭据中心”提供受权限保护的列表、一次性明文创建、轮换、停用和
  依赖查询。页面只展示 `secret://platform/...`、用途、版本和状态，不显示明文、
  密文或 Master Key。
- Vault/KMS 只显示为未实现说明，不能从界面创建或发布；Master Key 仍只由部署侧
  固定只读文件提供。
- “平台治理 → 工具资源”提供 type/scope/lifecycle/activation 筛选，并分别显示
  Draft、Published、Effective、Last Known Good、degraded/blocked 和受影响应用。
- MySQL、SQL Server、Oracle 11g、Redis、Loki 使用 canonical 表单。Oracle 是
  Host/Port + Service Name/SID 二选一；Secret 只能从凭据中心 Combobox 选择。
- 资源生命周期提供 Draft 新建/编辑/删除、技术验证、发布、从 revision 建 Draft、
  disable 和 archive；发布版本不可原地修改。
- “运行中心 → 发起调试”只消费服务端授权选项，默认 Delivery 为 none，不提供
  `user_id`、任意 Agent/Resource Revision/Connector/reply route 输入。
- Job 详情改用当前用户授权的证据 API，分别显示 Agent、Dispatch Outbox、
  Tool Call 和 Delivery 时间线。

## 自动化验证

```text
.venv/bin/pytest -q
652 passed, 20 skipped, 2 warnings, 4 subtests passed

cd frontend
node node_modules/vitest/vitest.mjs run
11 test files passed, 53 tests passed

npm run lint
PASS

npm run build
PASS；2673 modules transformed
```

Phase 5 新增/聚焦测试覆盖：

- 资源管理 API 登录/权限、生命周期、Secret 脱敏和非法 `env:`/任意引用字段拒绝。
- Job evidence API 创建人/应用运维/平台管理员授权边界。
- 凭据元数据、引用依赖类型、Oracle canonical 字段、关系库 Database 文本类型、
  Secret-only 序列化和 Debug DTO 白名单。

## 真实浏览器验证

使用当前 Docker Compose 管理端 `http://127.0.0.1:8080` 和本地种子管理员执行，
未保存任何资源 Draft、未创建/轮换/停用 Secret、未发起 Debug Job。

- 空资源页明确显示 reset 后资源为 0。
- MySQL `Database` 为文本输入、`Port` 为数字输入；Redis DB 仍由契约保持数字。
- Oracle 11g 表单显示 Port 1521、Service Name/SID 二选一。
- Sheet 内 Secret Combobox 可聚焦、展开并选择现有
  `secret://platform/...`；取消后页面仍为空资源。
- 修复 Base UI `items` 数据源后，有选项时不再错误显示 Secret 空状态。
- 凭据中心仅有一个一次性 password 输入，无 Master Key 输入、无 ciphertext；
  依赖视图能显示模型连接版本、运行配置、状态和引用字段，不再显示“未知依赖”。
- 当前空资源/发布状态下 Debug 页 fail closed，显示“没有可用的调试应用”，且没有
  任意身份、资源、Connector 或路由输入。
- 既有 Job 详情成功显示 Agent、Dispatch、Tool Call、Delivery 独立时间线，页面
  无 password、ciphertext 或 Master Key。
- 浏览器控制台 error 数量为 0。

## 数据与运行状态

```text
branch=master
head=debb504
worktree=dirty（保留既有未提交工作；未创建 commit）

schema_head=023
schema_checksum=cc5f3692797611c62a9d47e1af09c5f76516da8eae88eb42d6989008f8da9cb0
platform_resource=0
platform_resource_draft=0
platform_resource_revision=0
business_application_resource_binding=0
platform_resource_binding=0
platform_secret=3
agent_job=19
```

`api-server`、`internal-api-platform` 和 `dingtalk-runtime` 均为 healthy；
API `/api/ready` 返回 200。DingTalk Runtime 健康端点返回 200、
`lease=true`、`total=0`，符合资源/连接从空配置开始的当前状态。

管理端重建时发现 API 与未重建 DingTalk Runtime 的部署 Secret 漂移。使用两个
运行中容器的既有挂载 Secret（只比较长度/摘要，不输出内容）重建 API 后，租约、
配置和状态请求恢复 200；中转文件已物理删除。

## 明确延期

- 本机没有 Oracle；真实 Oracle Database 11.2.0.4 连接、权限探针和发布保持
  deferred，不以表单、单元测试或 19c Thick Client 镜像替代真实连接结论。
- 当前数据库按用户要求继续保持 DB/Redis/Loki 资源全空。本阶段通过 API/数据库
  生命周期测试证明可从空配置建立、验证、发布和激活，但没有为了 UI 测试向实际
  配置写入验收资源。
- 任务 10.* 的维护窗口切换和任务 11.* 的真实 Grafana→Agent→工具→DingTalk
  验收尚未执行，聚合 Gate 5/6 仍应保持 BLOCKED。
