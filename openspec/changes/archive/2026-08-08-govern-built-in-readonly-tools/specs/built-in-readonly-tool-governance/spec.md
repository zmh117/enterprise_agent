## ADDED Requirements

### Requirement: 内置只读工具实现必须来自代码 Manifest
系统 MUST 从代码 Registry 加载内置只读工具的稳定 Identifier、语义版本、Handler Version、输入/输出 Schema、模型描述、风险等级、所需权限、逻辑资源槽、固定 Verifier Plan 和 Implementation Digest；数据库和管理 API MUST NOT 创建或覆盖这些实现字段。

#### Scenario: 部署合法代码 Manifest
- **WHEN** 新部署包含一个格式合法且 Identifier 未冲突的内置只读工具 Manifest
- **THEN** 系统可以对账该 Manifest，但不会自动验证或发布 Release

#### Scenario: 管理端提交动态实现
- **WHEN** 管理员尝试为内置只读工具保存任意 HTTP、MCP、SQL、Shell、脚本、模板、函数或完整 URL 实现
- **THEN** 系统拒绝请求且不得保存或执行该内容

#### Scenario: Manifest 扩大安全边界
- **WHEN** 新 Manifest 扩大公开 Schema、风险等级、所需权限或资源访问边界但复用原稳定 Identifier
- **THEN** 系统将安装标记为 DRIFTED 并拒绝发布，要求使用新的稳定 Identifier

### Requirement: 部署对账必须产生明确 Installation 状态
系统 SHALL 通过幂等 reconcile 比较代码 Registry 与数据库 Installation，并为每个精确 Handler Version 和 Implementation Digest 产生 `INSTALLED`、`MISSING` 或 `DRIFTED` 状态；reconcile MUST NOT 自动创建可调用 Release。

#### Scenario: 代码与安装记录一致
- **WHEN** Manifest 的 Identifier、Handler Version 和 Implementation Digest 与 Installation 一致
- **THEN** reconcile 将 Installation 标记为 INSTALLED 并记录本次对账摘要

#### Scenario: 已发布实现不在当前部署
- **WHEN** 数据库存在 Tool Release 但当前代码 Registry 缺少其精确实现
- **THEN** reconcile 将对应 Installation 标记为 MISSING，后续新调用失败关闭

#### Scenario: 相同版本 digest 不一致
- **WHEN** 代码声明相同 Identifier 和 Handler Version 但 Implementation Digest 与数据库记录不同
- **THEN** reconcile 将其标记为 DRIFTED，不得把该部署视为已安装精确实现

### Requirement: Tool Release 发布必须依赖固定机器验证
系统 MUST 只运行 Manifest 声明且由代码实现的固定 Verifier Plan；成功证据 MUST 绑定 Installation ID、Handler Version、Implementation Digest、Verifier Version、规范化输入摘要和时间，内容变化后旧证据立即失效，且不得人工覆盖验证结果。

#### Scenario: 当前实现验证成功
- **WHEN** 授权管理员对 INSTALLED 的精确实现运行 verifier 且所有必需检查通过
- **THEN** 系统保存脱敏的成功证据并允许该精确实现进入发布校验

#### Scenario: 验证后实现改变
- **WHEN** Implementation Digest、Handler Version 或 Verifier Version 在成功验证后改变
- **THEN** 旧证据失效，Publish 必须拒绝直到新实现重新验证

#### Scenario: 管理员尝试手工通过
- **WHEN** 管理员提交手工备注、任意脚本结果或直接修改状态来替代机器验证
- **THEN** 系统拒绝将其作为发布证据

### Requirement: Built-in Tool Release 必须不可变且生命周期受控
系统 SHALL 从当前成功验证证据创建不可变 Built-in Tool Release，并 MUST 支持 `ACTIVE`、`DEPRECATED`、`DISABLED`、`ARCHIVED` 状态；内容字段发布后不得修改，生命周期动作必须审计。

#### Scenario: 发布已验证实现
- **WHEN** 授权发布者提交当前 Installation、成功证据和幂等键
- **THEN** 系统原子创建或复用同一个 ACTIVE Release，并冻结 Manifest、Handler Version、Implementation Digest 和证据引用

#### Scenario: 软废弃 Release
- **WHEN** 管理员把 ACTIVE Release 设为 DEPRECATED
- **THEN** 既有 Publication 可以继续调用并显示警告，但新 Agent Publication 不得选择该 Release

#### Scenario: 紧急禁用 Release
- **WHEN** 管理员把 Release 设为 DISABLED
- **THEN** 所有后续新调用失败关闭，历史 Publication、Job 和审计保持不变

#### Scenario: 恢复已禁用 Release
- **WHEN** 授权管理员确认精确实现为 INSTALLED、重新验证成功且依赖校验通过后恢复 DISABLED Release
- **THEN** 系统可将其恢复为 ACTIVE并记录原因、actor、证据和时间

#### Scenario: 归档 Release
- **WHEN** Release 仍被活动 Publication 或非终态、可恢复 Job 引用
- **THEN** 系统拒绝 ARCHIVED；只有依赖归零后才允许进入不可恢复的 ARCHIVED 终态

### Requirement: Release 生命周期与运行健康必须分离
系统 MUST 分别计算 Release 生命周期和 Installation/Resource/Policy 运行健康；`MISSING`、`DRIFTED`、`DEGRADED` 或 `EMPTY` MUST NOT 自动改写 Release 生命周期，但运行时必须依据两者共同失败关闭。

#### Scenario: ACTIVE Release 的实现缺失
- **WHEN** Release 为 ACTIVE 但精确 Installation 为 MISSING
- **THEN** 管理端同时显示 ACTIVE 与 MISSING，运行时拒绝调用且不自动禁用或换版

#### Scenario: Loki 长期无数据
- **WHEN** Tool Release 依赖的已发布 Loki Scope Policy 健康为 EMPTY
- **THEN** Release 状态保持不变，查询继续使用原强制范围并返回空结果告警

### Requirement: 管理权限必须细分且互不隐式授予
系统 MUST 分别执行 `builtin_tools.read`、`builtin_tools.reconcile`、`builtin_tools.verify`、`builtin_tools.publish`、`builtin_tools.lifecycle`，且这些权限 MUST NOT 隐式授予 `tool_resources.*`、Agent/Application 发布权限或运行 `tool:use` 权限。

#### Scenario: 只读管理员查看目录
- **WHEN** 管理员只有 `builtin_tools.read`
- **THEN** 可以查看非敏感 Manifest、Installation、Evidence 摘要和 Release 历史，但不能 reconcile、verify、publish 或改变生命周期

#### Scenario: 发布者缺少资源权限
- **WHEN** 操作者有 `builtin_tools.publish` 但没有 `tool_resources.publish`
- **THEN** 可以发布满足条件的 Tool Release，但不能发布或修改 Tool Resource

### Requirement: 运行使用授权必须绑定稳定 Tool Identifier
系统 SHALL 以稳定 Tool Identifier 作为 `tool:use` Grant 目标，并 MUST 在运行时继续校验精确 Release、Application Allowlist 和数据范围；Grant MUST NOT 单独指定或浮动解析 Release 版本。

#### Scenario: 稳定工具授权命中精确 Release
- **WHEN** 用户具有某稳定 Identifier 的 `tool:use` 且 Job 冻结了该 Identifier 的可调用精确 Release
- **THEN** 授权可进入后续资源和范围校验，不需要为每个兼容 Release 重建 Grant

#### Scenario: 应用未选择该工具
- **WHEN** 用户具有稳定 Identifier 的 `tool:use` 但 Application Publication 未选择该 Tool Release
- **THEN** 系统拒绝调用且不向模型暴露该工具

### Requirement: legacy-v1 必须通过两阶段迁移退出活动运行时
系统 MUST 把 `legacy-v1` 视为名称级旧绑定标记而非版本，并 SHALL 通过 additive/cutover 和 removal 两阶段迁移；迁移期间不得根据 latest、默认值或第一个候选猜测精确 Release。

#### Scenario: 第一阶段开始后写入旧绑定
- **WHEN** 任何 API、导入器或运行时尝试创建新的 `legacy-v1` 名称级绑定
- **THEN** 系统拒绝写入并要求精确 Tool Release 与资源策略快照

#### Scenario: 旧 Job 只有一个可证明候选
- **WHEN** 非终态、待重试或可 replay Job 可从其原 Publication、代码 digest 和资源事实唯一确定精确绑定
- **THEN** 迁移在幂等事务中物化 Execution Snapshot 并记录迁移证据

#### Scenario: 旧 Job 候选不唯一
- **WHEN** 旧 Job 对应零个或多个可能 Release、Resource 或 Policy
- **THEN** 系统隔离该 Job 并阻止重试/恢复，不得自动选择候选

#### Scenario: 移除兼容路径
- **WHEN** 新 legacy 写入、活动 Publication legacy 引用、非终态及可恢复 Job legacy 引用均为零，且真实运行与投递链验收通过
- **THEN** 系统删除 legacy 兼容读取、写入和旧 Publication 激活入口，同时保留终态历史记录供审计

### Requirement: 内置工具管理界面必须展示定义、证据、发布和生效差异
“平台治理 → 只读工具” MUST 展示 Code Manifest、Installation 状态、Verification Evidence 摘要、Release 生命周期、依赖 Publication 和 Effective 状态，并按细粒度权限控制动作。

#### Scenario: Release 已发布但部署漂移
- **WHEN** 管理员查看一个 ACTIVE Release 且当前 Installation 为 DRIFTED
- **THEN** 页面同时显示冻结 digest、当前 digest、DRIFTED 和不可调用原因，不得只显示“已发布”

#### Scenario: 管理员查看验证失败
- **WHEN** verifier 失败并产生包含敏感上游错误的原始响应
- **THEN** 页面和 API 只显示脱敏错误类别、步骤和 correlation id，不返回凭据或无界原始响应
