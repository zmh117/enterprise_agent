## ADDED Requirements

### Requirement: 管理后台使用可复现的 shadcn pnpm monorepo
系统 SHALL 将前端组织为 `frontend/` 内的 pnpm workspace，并使用指定的 `pnpm dlx shadcn@latest init --preset b0 --template vite --monorepo --pointer` 生成基线；生成前 MUST 校验 preset，且 MUST 在独立暂存目录完成生成和审查后再迁移现有代码。

#### Scenario: 初始化新的前端骨架
- **WHEN** 开发者执行前端重构初始化
- **THEN** 系统生成 Vite 应用、共享 UI package、workspace 配置和各 workspace 的 `components.json`
- **AND** 已有前端文件不会被 CLI 静默覆盖

#### Scenario: preset 无法解析
- **WHEN** 当前 shadcn CLI 无法解析 `b0`
- **THEN** 实施流程停止并报告错误，不得擅自改用其他 preset

### Requirement: 前端代码按业务上下文和 DDD 分层
系统 SHALL 将管理功能组织为明确的 bounded context，并在每个上下文内分离 domain、application、infrastructure 和 presentation；共享 UI package MUST 不依赖业务类型、业务 API 或具体权限编码。

#### Scenario: 新增业务页面
- **WHEN** 开发者新增 Agent、Skill、工具、Channel 或运维页面
- **THEN** 领域模型、应用用例、HTTP DTO 映射和展示组件分别放置在对应分层中
- **AND** 页面不得直接维护跨领域的巨型 DTO 类型文件

### Requirement: 管理后台提供统一 Shell 和模块导航
系统 SHALL 提供包含 Dashboard、用户、授权、Agent、Skill、API 工具、Channel、Webhook、队列、历史对话、附件和审计入口的响应式后台 Shell，并根据登录主体的权限隐藏或禁用不可访问操作。

#### Scenario: 有权限的管理员登录
- **WHEN** 具备相应管理权限的用户进入后台
- **THEN** 系统展示其可访问模块、当前位置面包屑和一致的页面标题区

#### Scenario: 无权限用户访问受限路由
- **WHEN** 用户直接访问其没有权限的管理路由
- **THEN** 前端展示安全的无权限页面
- **AND** 后端仍独立拒绝该请求

### Requirement: 管理页面使用一致的数据交互规范
系统 SHALL 使用统一 API Client、TanStack Query、表单校验、分页过滤、加载状态、空状态、错误状态和成功提示；错误展示 MUST 使用后端安全错误码和 correlation id，不得呈现密钥或未受限上游正文。

#### Scenario: 列表查询失败
- **WHEN** 管理页面的列表请求失败
- **THEN** 页面保留筛选条件并展示可重试错误状态及安全 correlation id

#### Scenario: 表单校验失败
- **WHEN** 用户提交不满足领域约束的配置
- **THEN** 页面在对应字段显示校验信息且不丢失用户已输入的非敏感内容

### Requirement: 旧前端仅在功能对齐后移除
系统 SHALL 为登录、用户/RBAC、默认 Agent 和 Webhook 现有流程建立回归基线，并在新页面通过单元、集成和浏览器验证后才移除旧页面及 npm 单包构建。

#### Scenario: 新页面尚未完成功能对齐
- **WHEN** 任一现有关键流程尚未通过回归验证
- **THEN** 发布流程不得删除其可工作的旧实现

#### Scenario: monorepo 构建验证完成
- **WHEN** 前端迁移完成
- **THEN** 锁定的 pnpm workspace 安装、类型检查、测试、生产构建和容器构建均可重复成功
