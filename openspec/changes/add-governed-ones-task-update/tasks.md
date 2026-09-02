## 1. 合同与回归基线

- [x] 1.1 为 `ones_update_task` 增加失败优先的 Manifest/schema 测试，覆盖仅单个缺陷、mutation 元数据、`uuid` 必填、至少一个 Patch 字段、`additionalProperties=false`、`null`/状态/原始 Provider 参数拒绝以及非缺陷目标拒绝。
- [x] 1.2 为现有 ONES 只读 Tool 和全部钉钉 mutation 建立不变回归，确认新增 ONES mutation 不改变其 identifier、schema hash、effect、确认策略或可见性。
- [x] 1.3 为 Action Intent Provider 分离、资源快照幂等和现有钉钉记录兼容建立 migration/repository 失败用例。

## 2. Action Intent与通用worker基础

- [x] 2.1 编写 additive migration，增加确认渠道、执行 Provider、执行外部身份、Team scope、目标资源、前置条件、字段目录和 `intent_fingerprint` 字段及受约束索引，并验证既有钉钉 Intent 无破坏性回填。
- [x] 2.2 扩展 External Action domain/repository/service，以类型化事实创建 ONES Intent，使用快照感知指纹幂等，并保持 Card Outbox、revision、签名回调与终态状态机不变。
- [x] 2.3 将卡片公共投放/结果更新编排与 Provider 卡片内容渲染分离，复用现有钉钉 mutation 模板、按钮和状态，增加 ONES 缺陷中文差异渲染、独立 `outTrackId` 与 `detailText` 4000 字符完整展示预算校验。
- [x] 2.4 把通用 claim/lease、恢复、审计与分发迁入 Provider 中立 worker 模块，保留 Compose 服务名，并把现有钉钉逻辑封装为行为一致的适配器。
- [x] 2.5 运行钉钉外部操作合同、卡片回调、租约竞争、中断恢复和审计回归，证明 worker 抽取没有改变现有 mutation 行为。

## 3. ONES写字段合同与Provider适配

- [x] 3.1 扩展 ONES Tool contract 以声明 read/mutation 元数据，注册 `ones_update_task` 的固定 schema、operation code、风险、目标策略与钉钉逐次确认策略，并修正 Manifest 不再强制所有 ONES Tool 只读。
- [x] 3.2 建立仅适用于缺陷的 `task_update_field_catalog` 有界 schema、加载器、版本/摘要校验及 Team scope 校验，纳入 design 中列明的全部已验证语义字段和 Provider 映射但排除状态。
- [x] 3.3 增加从 `ones_mock/ones/查询条件字典.yaml` 提取白名单中文含义与静态选项的生成/一致性检查，拒绝同名多套字段、未知 type、重复 UUID、动态组织实体和只读字段。
- [x] 3.4 实现 Patch 规范化与编译器，覆盖未提供/经验证清空/非法 `null` 三态、未验证单值清空拒绝、标题与描述成对写入、安全富文本生成、缺陷字段适用性以及固定 `update3` payload。
- [x] 3.5 扩展 ONES Provider 客户端的固定 Task 详情/权限查询、动态实体验证、`update3` 调用和有界响应解析；禁止调用方控制路径、Team、Header 或认证材料。
- [x] 3.6 为字段目录、全部缺陷语义字段映射、状态排除、清空策略、动态实体唯一 UUID 解析、同名歧义、Provider 路径和 `bad_tasks` 解析增加参数化单元测试。

## 4. ONES MCP准备与确认流程

- [x] 4.1 实现 `ones_update_task` Tool 入口，仅接受可验证的钉钉私聊/群聊来源 Job；在当前 Principal 下解析原始 ONES 身份/Team/Credential，并读取缺陷当前值、权限位和 `serverUpdateStamp`，Web/后台/无 Connector Job 在 Intent 前拒绝。
- [x] 4.2 实现字段级预检：证明目标为缺陷，验证普通编辑、关注者更新权限以及当前缺陷布局适用性；任一失败均在 Intent 和写调用前返回稳定中文错误。
- [x] 4.3 实现实际差异计算与无变化短路，使用相同卡片模板生成包含中文字段名/显示名称和完整“原值 → 新值”的安全确认摘要；超出 4000 字符时不创建 Intent 并要求拆分。
- [x] 4.4 使用 Job、参数、身份、Team、Task 更新戳和目录摘要创建或复用 Intent，确保 Tool 结果只表示“等待确认”或“无需更新”，不在 MCP 请求内执行写操作。
- [x] 4.5 增加准备流程集成测试，覆盖钉钉私聊/群聊私发卡片、Web 拒绝、同快照重复调用、Task/目录变化后新建 Intent、身份缺失、非缺陷、状态字段、字段越权、歧义名称、无变化、卡片超限和 Card Outbox 原子创建。

## 5. ONES确认后执行与恢复

- [x] 5.1 实现 ONES worker 适配器的执行时重新授权：内部用户、原始 ONES 身份、冻结 Team、当前 Credential、Job Tool Snapshot、角色/Application 授权与确认钉钉主体均须保持有效。
- [x] 5.2 在写调用前回读缺陷并校验工作项类型、`serverUpdateStamp`、字段目录、字段适用性和专用权限；任何更新戳变化（包括无关字段变化）均使确认失效，不访问写接口并更新结果卡片。
- [x] 5.3 调用固定 `update3` 请求，严格归一化 HTTP 状态、响应结构与 `bad_tasks`，成功后回读并逐字段核对确认值。
- [x] 5.4 对超时、连接中断和 worker 中断实现只读结果核对：可证明目标值时记录“核对后成功”，否则进入 `FAILED_UNCERTAIN` 并禁止自动重放。
- [x] 5.5 增加执行集成测试，覆盖确认后解绑/换绑、Team 移除、Credential 刷新、授权撤销、更新戳冲突、明确成功、部分失败、结果未知、双 worker 竞争和 Secret 拒绝持久化。

## 6. 发布授权与管理界面

- [x] 6.1 在授权中心和 Agent/Application Tool 列表中增加“更新 ONES 缺陷 `ones_update_task` / 完整说明 / 写入”展示，并标明仅钉钉来源可用且每次调用需要卡片确认。
- [x] 6.2 验证角色 grant、Agent Publication、Application 子集、Job Tool Snapshot 和 Runtime `tools/list/call` 对新 mutation 的交集控制，且不会自动授权现有角色、应用或 Job。
- [x] 6.3 增加管理 API/UI 回归，覆盖未知确认策略、schema/operation 漂移、只读/写入标识及未发布 Tool 的 fail-closed 行为。

## 7. 校验、部署与真实验收

- [x] 7.1 运行相关 `.venv/bin/pytest` 单元与集成套件、migration head/upgrade 校验、静态检查和 `git diff --check`，并如实记录任何既有基线失败。
- [x] 7.2 构建受影响 backend、ONES MCP 与 external-action-worker 镜像，执行容器内 import smoke，确认裁剪镜像包含 Provider 中立 worker、ONES 适配器和字段目录但不包含 mock 业务资料。
- [x] 7.3 运行 `docker compose config --quiet` 与目标服务健康/并发检查，部署 migration 和新镜像后验证现有钉钉 mutation 仍可用。
- [ ] 7.4 以新 Agent/Application Publication 和新 Job 完成真实 ONES 验收：钉钉私聊/群聊来源私发同模板卡片、Web 拒绝、单/多字段修改、状态/非缺陷拒绝、清空、超长差异、拒绝卡片、任意更新戳冲突、确认后解绑身份、Provider 失败以及成功回读。
- [ ] 7.5 保存不含 Secret 的 Action Intent、MCP call、Agent Tool Call、Job、卡片点击、Provider attempt 和结果卡片审计证据，并明确区分自动测试通过与真实端到端验收通过。
- [x] 7.6 运行 `openspec validate add-governed-ones-task-update --strict`，确认所有工件与最终实现一致后再进入 sync/archive。
