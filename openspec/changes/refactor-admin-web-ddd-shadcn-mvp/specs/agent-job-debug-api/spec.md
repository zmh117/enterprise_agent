## ADDED Requirements

### Requirement: Job 查询 API 支持管理后台分页检索
系统 SHALL 提供受 RBAC 和数据范围保护的 Job 分页查询，支持按时间、状态、用户、Agent、Channel、项目、会话和 correlation id 筛选，并使用稳定排序和不透明分页游标或等价稳定分页契约。

#### Scenario: 按失败状态查询任务
- **WHEN** 运维用户查询指定时间窗口内的 failed 和 timeout Job
- **THEN** 系统只返回其授权范围内的任务摘要和稳定分页信息

#### Scenario: 未指定时间范围
- **WHEN** 调用方未提供时间窗口
- **THEN** 系统使用受限默认窗口和默认页大小，避免无界扫描

### Requirement: Job 查询 API 提供状态汇总读模型
系统 SHALL 提供指定时间和权限范围内的 Job 状态计数、重试等待、最终失败、超时和 Delivery 失败摘要，供 Dashboard 和运维页面使用。

#### Scenario: 汇总最近 24 小时任务
- **WHEN** Dashboard 请求最近 24 小时状态汇总
- **THEN** 系统返回明确时间边界、生成时间和权限裁剪后的计数

### Requirement: Job 详情关联会话和 Delivery 安全摘要
系统 SHALL 在授权范围内提供 Job 与 Session、Message、Steps、Tool Calls、Retry、Webhook Event 和 Delivery Attempts 的关联引用，MUST NOT 返回 Secret、私有推理或未脱敏 raw payload。

#### Scenario: 排查最终 Delivery 失败
- **WHEN** 运维用户查看已执行但投递失败的 Job
- **THEN** 系统返回执行状态、重试阶段和 Delivery attempt 的安全错误摘要及 correlation id
