## 1. 前置基线与合同锁定

- [x] 1.1 在 apply 前确认 `add-governed-dingtalk-mcp-mvp` 已同步并归档，重读相关 canonical specs；若前置未完成或语义不一致则停止实施并修订本 change
- [x] 1.2 锁定并记录实施时使用的官方钉钉 MCP/开放接口版本、七个 Profile 的 method/path/字段与所需权限，不复制动态 YAML 到运行时
- [x] 1.3 建立 27 个固定 Tool 的清单测试，精确断言 identifier、read/mutation、confirmation policy、operation code、risk、target policy 和明确排除项

## 2. 固定 Tool 合同与发布治理

- [x] 2.1 扩展 `DingTalkToolContract` 执行元数据，并为 18 个只读与 8 个新增 mutation 定义有界 input/output schema
- [x] 2.2 从合同目录生成 `MCP_TOOL_MANIFEST`、required scope、MCP annotations 和 schema hash，保持 `dingtalk_create_todo` 兼容
- [x] 2.3 更新 Agent/Application Publication、角色 Tool 目录和 Job Snapshot 校验，使 27 个 Tool 可精确选择且动态 Profile/未知 mutation 失败关闭
- [x] 2.4 更新管理 API 与管理端 Tool 展示，区分只读和需逐次确认的 mutation，并验证新 Revision/Publication 才能进入新 Job

## 3. Principal、目标解析与审计执行壳

- [x] 3.1 将 `DingTalkPrincipalResolver` 参数化为按实际 Tool 合同验证 scope、snapshot、effect、policy、角色和 Application，不再引用单一创建待办常量
- [x] 3.2 扩展受信目标解析，固定当前 staff ID/union ID、primary calendar、AI 表格 operator、来源会话、robot code 和本人通知接收人
- [x] 3.3 实现共享只读 Tool 执行壳，统一参数规范化、Principal、MCP 审计、超时、响应字节和安全错误分类
- [x] 3.4 实现共享 mutation 准备器，冻结模型参数与服务端目标事实并生成分 operation 的安全摘要和确认详情
- [x] 3.5 增加审计脱敏回归，证明联系人敏感字段、消息/日程正文、AI 表格值、Secret、Token 和原始 Provider 正文不进入普通日志或审计

## 4. 只读 Provider 与 Tool

- [x] 4.1 实现联系人固定 Client 与 `dingtalk_search_users`、`dingtalk_get_user`、`dingtalk_list_department_users`，加入字段白名单、分页和敏感字段删除
- [x] 4.2 实现部门固定 Client 与 `dingtalk_search_departments`、`dingtalk_get_department`、`dingtalk_list_sub_departments`
- [x] 4.3 实现 `dingtalk_list_todos`，由服务端注入当前 union ID 并限制状态、角色、游标与页大小
- [x] 4.4 实现 `dingtalk_get_calendar_event`、`dingtalk_list_calendar_events`、`dingtalk_list_calendar_attendees`，固定当前用户 primary calendar 和 31 天时间窗
- [x] 4.5 实现 AI 表格搜索、sheet、field 和 record 六个只读 Tool，固定当前 union ID operator 并限制 base/sheet/record ID、页大小和响应
- [x] 4.6 实现工作通知进度与结果两个只读 Tool，只允许查询同 actor/企业/Connector 的平台发送结果
- [x] 4.7 为每个只读 endpoint 增加 method/path/header/body、字段投影、分页、超限、权限拒绝和 Provider 错误合同测试

## 5. mutation Provider、确认与执行分派

- [x] 5.1 实现本人待办更新与完成的参数规范化、确认摘要和固定 Provider handler，保持 task path 的 union ID 服务端解析
- [x] 5.2 实现本人 primary calendar 日程创建与更新的时间/时区校验、确认摘要和固定 Provider handler
- [x] 5.3 实现 AI 表格记录新增与更新的批量/字段/字节上限、准备前目标预检、确认摘要和执行前二次预检
- [x] 5.4 实现当前来源会话机器人消息，按群聊/私聊服务端选择固定 endpoint，输入只接受有界标题与正文
- [x] 5.5 实现当前用户工作通知，固定 Connector Agent ID 和本人 staff ID，禁止用户列表、部门列表与全员发送
- [x] 5.6 将 external action worker 改为 Tool/operation 一一对应的固定 dispatcher，并在分派前复核 Manifest、授权、身份、Connector 和目标
- [x] 5.7 泛化现有确认卡片创建/终态文案，按 operation 展示有界目标和具体操作内容，同时保持模板 ID、opaque token、revision 与不可转发边界
- [x] 5.8 增加 mutation 重复调用、重复点击、拒绝、过期、撤权、身份换绑、operation 漂移、Provider 明确失败和不确定失败测试
- [x] 5.9 增加升级兼容测试，证明旧 `dingtalk_create_todo` Intent 和新旧 Job Snapshot 在允许范围内继续执行且不会错分派

## 6. Connector 配置与就绪门禁

- [x] 6.1 在 DingTalk Connector 非敏感元数据/API/UI 中增加 `work_notification_agent_id` 正整数配置与脱敏展示，不新增 Secret 字段
- [x] 6.2 实现按 Tool 的 readiness 校验：企业/App Secret、robot code、当前来源路由、Agent ID 和 operation handler 缺失时精确失败关闭
- [x] 6.3 更新 Compose/运行配置与运维说明，确认服务不消费 `ACTIVE_PROFILES`、官方 YAML、`ROBOT_ACCESS_TOKEN` 或动态 Provider 配置
- [x] 6.4 增加钉钉应用权限清单和 Profile 级稳定错误映射，权限不足不得回退其它 Connector、Credential 或 endpoint

## 7. 自动化验证

- [x] 7.1 完成 Tool registry、Principal、目标解析、只读执行壳、Provider、worker dispatcher、卡片和审计的单元/合同测试
- [x] 7.2 完成 Agent/Application/角色/Job Snapshot 的控制面集成测试，覆盖工具未发布、角色未授权、schema/effect/policy 漂移和 Connector 配置缺失
- [x] 7.3 运行钉钉 MCP/外部操作定向 pytest、相关后端完整测试层、Ruff/静态检查、Runtime 测试与类型检查
- [x] 7.4 重建受影响镜像并验证 `docker compose config --quiet`、migration/schema head、`dingtalk-mcp` 与 external action worker health/readiness
- [x] 7.5 运行 `openspec validate expand-governed-dingtalk-mcp-phase-2 --strict`、相关 canonical/全量 OpenSpec 校验和 `git diff --check`

## 8. 真实发布与 E2E 证据

- [x] 8.1 创建包含精确 Phase 2 Tool 的新 Agent/Application Publication 与角色 grant，并证明既有 Publication 和旧 Job 不会自动获得新 Tool
- [ ] 8.2 使用全新真实 DingTalk Job 分别验收 contacts、department、tasks、calendar、notable 和 notice-status 代表性只读调用，区分成功、无数据和权限不足
- [ ] 8.3 分别验收待办、日历、AI 表格记录、机器人消息和工作通知 mutation 的同意链，关联 Job、Tool Call、Intent、卡片、唯一 Provider attempt 与真实外部结果
- [ ] 8.4 分别验收上述 mutation 的拒绝链，证明 Intent 为 REJECTED、Provider 写入 attempt 为零且卡片终态不可再次执行
- [ ] 8.5 保存不含 Secret、Token 或无界业务正文的发布/回滚证据，确认排除的删除、撤回、DING、任意目标和结构修改 Tool 不可见
