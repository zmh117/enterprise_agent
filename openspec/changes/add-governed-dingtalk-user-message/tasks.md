## 1. 收敛前置 Phase 2 依赖

- [x] 1.1 在 `expand-governed-dingtalk-mcp-phase-2` 范围修复联系人搜索对字符串 userId、`hasMore` 和 `totalCount` 的固定投影，并增加真实响应形态的合同测试。
- [ ] 1.2 使用全新钉钉 Job 验证联系人搜索真实命中、分页和两个同名 userId，再完成 Phase 2 的剩余验收、严格校验、spec 同步与归档。
- [ ] 1.3 重新读取归档后 canonical 的相关 identity、channel、tool、execution 和 operations Requirement，对账并严格校验本 change 的 delta。

## 2. 注册官方映射 Tool 与发布治理合同

- [x] 2.1 新增 `dingtalk_batch_send_message_to_users_by_robot` 固定合同：模型输入为非空 `user_ids` 和 `msg_param={title,text}`，拒绝姓名、部门、全员、群、robot code、msgKey 和网络控制字段。
- [x] 2.2 注册 `effect=mutation`、确认策略、`dingtalk.robot.batch_send_message_to_users` operation、显式 userId 集合 target policy、Manifest 和安全输出 schema，并保持既有消息 Tool 的 schema hash 与语义不变。
- [x] 2.3 更新授权中心、Application Tool 目录和 Agent Tool 描述，明确按姓名发送应执行“搜索 → 必要时详情消歧 → 批量发送”，且不得复用历史 Job 授权结论或回退工作通知。
- [x] 2.4 增加 Publication、角色 grant 和 Job Snapshot 回归，证明新 Tool 只对新版本精确交集可见，旧 Publication、旧 Job 和既有 Intent 保持隔离。
- [x] 2.5 保留历史 `dingtalk_send_robot_message` identifier、schema、operation 和当前来源目标策略，只将管理面、Agent 描述和确认操作文案明确为“当前钉钉来源会话”，避免与官方 Profile 的任意用户批量发送能力混淆。

## 3. 实现官方参数规范化和确认摘要

- [x] 3.1 实现非空 `user_ids` 与 `msg_param` 固定 schema、标识/字段长度及全局 payload 字节校验；保持 userId 成员和顺序，不自动排序、去重、截断或拆批。
- [x] 3.2 实现稳定参数 hash 和单批单 Intent 复用；相同有序参数复用既有 Intent，不在发送 Tool 内隐式调用用户搜索或详情 endpoint。
- [x] 3.3 生成不可由模型覆盖的有界执行目标事实，区分确认 actor 与收件人集合，并确保其中不含 Token、Secret、手机号、邮箱或原始 Provider 对象。
- [x] 3.4 生成整批确认摘要：展示收件人数、可安全展示的候选名称或 userId 尾号、标题和正文，并验证单人及多人卡片的同意/取消动作可用。

## 4. 实现固定官方 batch Provider 执行链

- [x] 4.1 在固定 Provider client 中实现 `POST /v1.0/robot/oToMessages/batchSend`：`user_ids -> userIds`、`msg_param -> msgParam`、Connector `robot_code -> robotCode`，并固定 `msgKey=sampleMarkdown`。
- [x] 4.2 在 mutation catalog 和 external action worker 中注册唯一 operation handler，并在发送前重新授权 Job/Publication/角色/Tool/schema/effect/policy、原 actor、企业、Connector/Credential 和 robot code。
- [x] 4.3 全部执行事实通过后只创建一次 Provider attempt；不得在 worker 内逐人预查、修改收件人、切换 Connector、回退工作通知或将一批拆成多次发送。
- [x] 4.4 将 Provider 成功、明确拒绝和超时/断连/结果不确定映射到有界终态；不自动重放 `FAILED_UNCERTAIN`，重复确认或执行不产生第二次发送。

## 5. 补齐自动化回归与安全验证

- [x] 5.1 增加 Tool/schema 合同测试，覆盖单个/多个 userId、空数组、空 ID、非法 `msg_param`、非法控制字段、全局 payload 超限、有序参数 hash 和历史 Tool 合同不变。
- [x] 5.2 增加官方 Provider 投影测试，断言 endpoint、`userIds`、`msgParam`、服务端 `robotCode` 和固定 `sampleMarkdown` 精确映射，且模型不能注入服务端字段。
- [x] 5.3 增加联系人与 Agent 编排回归，覆盖字符串 userId、对象白名单、`hasMore/totalCount`、未知成员、两个同名候选、本轮 `dingtalk_get_user` 授权及选择前 mutation/Intent/Provider attempt 均为零。
- [x] 5.4 增加 Action Intent/卡片/worker 回归，覆盖一批一个 Intent/一张卡、同意、取消、过期、重复点击、只有原 actor 可确认、actor 或 Connector 漂移和 `FAILED_UNCERTAIN` 不重放。
- [x] 5.5 增加语义隔离与安全回归，断言普通私信不调用工作通知或当前来源 Tool，发送链不隐式逐人预查，日志/审计不保存正文、完整 userId 列表、目录数据、Secret、Token 或原始 Provider 响应。

## 6. 构建、发布与真实钉钉验收

- [x] 6.1 运行定向 pytest、相关后端测试层、Ruff、`docker compose config --quiet`、严格 OpenSpec 校验和 `git diff --check`，准确记录与本 change 无关的既有失败。
- [x] 6.2 重建并部署受影响的 API、DingTalk MCP 和 external action worker 镜像，验证新增 Tool/operation/handler readiness 一一对应且现有消息 Tool 仍可用。
- [ ] 6.3 创建新 Agent Publication、Application Publication 和角色 grant，并通过全新 Job 验证新 Tool 可见、未授权及旧 Job 不可见。
- [ ] 6.4 在真实钉钉环境验证两个同名人员的搜索与人工消歧、单人发送同意/取消、多人整批发送同意/取消和重复点击。
- [ ] 6.5 核对每条真实链的 Job、Tool Call、Intent、卡片、唯一 Provider attempt 与外部收件结果，保存有界脱敏证据并确认无凭据、正文或完整用户目录泄露。
