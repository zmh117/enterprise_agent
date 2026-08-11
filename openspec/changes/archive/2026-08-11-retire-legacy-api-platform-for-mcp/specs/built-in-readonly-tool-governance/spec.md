## MODIFIED Requirements

### Requirement: 内置只读工具实现必须来自代码 Manifest
系统 MUST 由 `tool-mcp` 从代码 Manifest 加载稳定 Tool Identifier、输入 Schema、模型描述、资源类型、只读限制和实现函数；数据库和管理 API MUST NOT 创建或覆盖实现，不再维护 Handler Version、Installation、Verification Evidence 或 Built-in Tool Release。

#### Scenario: 部署合法代码 Manifest
- **WHEN** 新部署包含格式合法且 Identifier/schema 未冲突的只读 MCP Tool Manifest
- **THEN** `tool-mcp` 注册该实现，Agent 管理目录可读取其非敏感定义

#### Scenario: 管理端提交动态实现
- **WHEN** 管理员尝试保存任意 HTTP、MCP、SQL、Shell、脚本、模板、函数或完整 URL 实现
- **THEN** 系统拒绝且不得保存或执行

### Requirement: 运行使用授权必须绑定稳定 Tool Identifier
系统 SHALL 以稳定 MCP Tool Identifier 作为 `tool:use` Grant 目标，并 MUST 在运行时校验 Agent Tool Envelope、Application Tool 子集、应用访问、数据范围和唯一资源解析；Grant MUST NOT 指定 Handler/Release/Server URL。

#### Scenario: 稳定工具授权命中 MCP Tool
- **WHEN** 用户具有某稳定 Identifier 的 `tool:use` 且 Job 冻结同一 identifier/schema hash
- **THEN** 授权进入资源和范围校验

#### Scenario: 应用未选择该工具
- **WHEN** 用户具有 Grant 但 Application Publication 未选择该 Tool
- **THEN** 系统拒绝且不向模型暴露该 Tool

### Requirement: 内置工具管理界面必须展示定义、证据、发布和生效差异
“平台治理 → 只读工具” SHALL 作为只读 MCP Tool Manifest 目录展示 identifier、描述、schema hash、资源类型、安装可用性和近期运行健康；MUST NOT 提供 reconcile、verify、publish、lifecycle 或动态实现编辑动作。

#### Scenario: 管理员查看工具目录
- **WHEN** 管理员具有工具目录读取权限
- **THEN** 页面显示代码 Manifest 和可用性，不显示已删除的 Handler/Release/Evidence 控件

## REMOVED Requirements

### Requirement: 部署对账必须产生明确 Installation 状态
**Reason**: Installation/Handler 版本治理层永久退役。
**Migration**: 启动时直接校验 MCP Tool Manifest 唯一性和依赖可用性。

### Requirement: Tool Release 发布必须依赖固定机器验证
**Reason**: Tool Release 与发布验证控制面永久退役。
**Migration**: 工具实现随代码测试和部署发布，不提供 Web 发布动作。

### Requirement: Built-in Tool Release 必须不可变且生命周期受控
**Reason**: MCP Tool 由代码版本拥有，不再维护数据库 Release 生命周期。
**Migration**: Agent/Application 冻结 identifier/schema hash；变更 schema 时发布新代码并显式重发 Agent/Application。

### Requirement: Release 生命周期与运行健康必须分离
**Reason**: Release 生命周期已删除。
**Migration**: 只保留 Manifest 安装可用性和运行健康。

### Requirement: 管理权限必须细分且互不隐式授予
**Reason**: reconcile/verify/publish/lifecycle 动作已删除。
**Migration**: 收敛为只读目录权限，工具使用权限仍独立保留。

### Requirement: legacy-v1 必须通过两阶段迁移退出活动运行时
**Reason**: 本次破坏性迁移直接删除 legacy Tool Release 兼容模型。
**Migration**: 可确定引用回填为 MCP Tool identifier/schema hash，不可确定活动引用阻止迁移。

