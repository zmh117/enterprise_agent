## Context

用户已删除上一版管理 Web，目前 `frontend/` 是单包 Vite + React + shadcn Dashboard 模板，`App` 只渲染模板 Dashboard。模板已经具备 Sidebar、Card、Table、Chart、Badge、Tooltip、Drawer 等展示组件，但菜单、指标、图表和表格仍是通用英文示例，不能表达当前 Agent 平台的新系统边界。

目标产品已经从“管理数据库、Redis、Loki连接的 Agent 管理台”调整为“配置业务应用和受控 API Capability 的 Agent 应用控制台”。同时，统一内部用户不仅需要关联钉钉账号，还要关联 ONES 等业务系统账号；身份关联用于解析可信业务主体，但不代替平台和外部系统授权。

本变更只用于产品和信息架构评审。它不能依赖尚不存在的 `business_application`、`api_capability`、`workflow_run`、`api_invocation` 等后端模型，也不能为了让示例看起来真实而调用当前管理 API。

## Goals / Non-Goals

**Goals:**

- 将通用模板替换为中文 Agent 应用平台静态 Dashboard，并保留一致、克制的 shadcn 视觉语言。
- 在一个页面中完整表现业务应用、Agent Profile、Workflow、渠道与触发器、API Capability、运行中心和系统管理的目标信息架构。
- 通过三个代表性应用和可视化调用链，使使用者能够评审“一个 Runtime、多个 Profile、多个业务应用”的产品模型。
- 表现内部用户与钉钉、ONES及未来外部系统账号的一对多关系，并明确身份关联、业务角色和外部系统权限的边界。
- 让所有示例数据、状态和不可用动作都能被明确识别为原型，避免误导。
- 为后续真实页面预留清晰的 bounded context 目录，而不在静态原型阶段制造多余抽象。

**Non-Goals:**

- 不实现登录、会话恢复、RBAC、Capability Gate 或真实用户上下文。
- 不增加 React Router 业务页面，不实现列表详情跳转、表单提交、测试连接、绑定、发布、回滚或调用操作。
- 不调用任何后端 API，不读取数据库，不增加 API Client、TanStack Query 或持久化状态。
- 不修改后端领域、数据库迁移、运行时、内部 API 平台或现有 OpenSpec 主规格。
- 不实现 AntV X6 流程编辑器；只使用静态节点或步骤图表现未来编排能力。
- 不展示真实用户、Secret、连接地址、业务记录或运行指标。

## Decisions

### 1. 使用单页产品地图，而不是创建一组空白路由

本阶段只交付一个 Dashboard。Sidebar 展示目标一级模块和分组，Dashboard 用卡片、关系图、静态表格和状态区域呈现关键页面能力；尚未实现的入口统一显示“规划中”，不导航到空页面。

采用这一方案是因为多个空壳页面会制造“功能已经存在”的错觉，也会提前固化尚未验证的路由层级。等产品结构确认后，再为业务应用工作区和运行中心引入真实路由。

### 2. 保持当前单包 Vite 项目，并按业务上下文组织新增展示代码

当前只有一个 Web 应用，因此不恢复上一版 pnpm monorepo。shadcn 生成组件继续保留在 `src/components/ui`，避免破坏 CLI 约定；应用组合和业务展示使用以下目标结构：

```text
src/
├── app/
│   ├── shell/
│   └── navigation/
├── contexts/
│   ├── overview/
│   ├── applications/
│   ├── agent-profiles/
│   ├── workflows/
│   ├── api-capabilities/
│   ├── channels/
│   ├── external-identities/
│   └── operations/
├── shared/
│   ├── presentation/
│   └── formatting/
├── components/ui/
└── mocks/
```

静态原型不要求每个 context 都机械创建 domain/application/infrastructure/presentation 空目录。只有实际承载展示模型的 context 才创建所需目录，后续引入领域行为时再补齐分层。

### 3. 只允许展示层交互，禁止业务行为

允许 Sidebar 的响应式展开、Tooltip、主题切换等纯展示行为；所有可能被理解为业务命令的按钮必须禁用或标注“规划中”，包括创建应用、编辑流程、绑定身份、测试 Capability、保存、发布和回滚。

原型数据来自本地静态 fixture，并通过页面级“原型数据”标识和局部说明标识。实现中不得出现 `fetch`、XHR、WebSocket、EventSource 或后端 URL。

### 4. Dashboard 采用六个评审区域

页面自上而下组织为：

1. 原型说明和环境展示：标题、产品定位、原型标记、示例环境。
2. 平台概览：业务应用、Agent Profile、API Capability、示例运行数量。
3. 业务应用：私聊、群聊、Webhook三张应用卡，展示 Profile、触发器、Capability数量和发布状态。
4. 平台调用链：Channel → Business Application → Workflow → Agent Runtime → Capability Gateway → API Platform → Delivery。
5. 控制面预览：工作流步骤、API能力目录、最近运行与安全边界。
6. 身份与治理：内部用户到钉钉/ONES账号关联、角色权限交集、待关联/冲突状态和建设状态。

这一结构同时回答“平台有什么”“一个应用由什么组成”“一次请求怎么运行”“人员身份怎么传递”四类评审问题。

### 5. 业务应用是界面的首要管理对象

Sidebar 中“业务应用”是主要入口。应用详情的目标页签通过静态关系卡展示为：概览、流程设计、渠道与触发器、能力授权、发布管理。Agent Profile、Workflow、Channel和Capability都作为应用发布时引用的版本化配置，而不是彼此平行、缺少装配关系的资源列表。

应用原型必须展示：

- 钉钉私聊诊断助手：按人员会话，使用消息发送人身份。
- 钉钉群聊诊断助手：按群保存会话，但调用权限按当前发送人解析。
- Webhook告警分析助手：使用服务账号和固定API节点，再由Agent综合分析。

### 6. API Capability 是业务能力，不暴露底层数据源

能力卡只展示 `log.query.application`、`order.query.detail`、`cache.query.status` 等业务编码、用途、风险、环境和可用状态。页面不得出现数据库DSN、Redis地址、Loki地址、SQL、Redis命令、LogQL、任意HTTP URL或底层Secret引用。

页面使用静态权限交集表达最终有效能力：平台发布 ∩ 应用授权 ∩ Workflow节点授权 ∩ Agent Profile授权 ∩ 当前主体数据权限。

### 7. 统一内部用户是身份中心，外部账号只是映射

身份区域以内部用户为中心，展示一个内部用户可以关联多个外部账号：钉钉用于消息入口与投递，ONES用于需求/任务/缺陷业务主体，其他系统作为扩展占位。

身份卡必须区分：

- 身份来源：钉钉、ONES或其他Provider。
- 租户/连接：账号所属的可信外部系统实例。
- 外部主体ID：使用明显的虚构示例值。
- 用途：消息来源、投递目标、业务主体或目录引用。
- 状态：已验证、待关联、冲突或停用。

“身份已关联”不得展示成“已经授权”。页面需同时展示角色、应用权限、Capability权限、API平台权限和ONES原生权限仍独立生效。

### 8. 系统管理和应用级配置不得重复

系统管理展示全平台共享资源：外部系统接入、用户与外部身份、角色与授权、Webhook/服务账号、审计和环境。业务应用只展示对已配置Channel、身份策略、Capability和发布版本的引用。

钉钉AppKey/AppSecret、Webhook签名凭据和API平台凭据均不出现在本原型；只展示“已配置”“待更新”等非敏感状态。

### 9. 响应式和可访问性属于原型验收范围

桌面使用分组侧栏和多列内容，窄屏使用可收起侧栏及单列卡片。信息不能只靠颜色表达；状态同时使用文字、图标或Badge。禁用动作必须具有明确的无障碍名称和不可用原因，静态流程图在窄屏允许纵向排列而不是横向溢出。

## Risks / Trade-offs

- [静态示例被误认为真实运行数据] → 页面全局和区域同时标记“原型数据”，不使用真实日期、用户ID、地址或业务记录。
- [一次展示过多模块导致Dashboard拥挤] → 使用清晰的六区结构、渐进信息密度和响应式布局，优先展示关系而不是完整字段。
- [Sidebar项目可见却不可进入造成困惑] → 使用“规划中”Badge或禁用状态，并在页面说明本阶段用于信息架构评审。
- [静态原型目录过度DDD化] → 不创建空分层；只建立Shell、overview和实际展示组件，目标目录作为后续演进约束。
- [旧工具资源术语再次出现] → 用内容测试和文本扫描禁止 Database Tool、Redis Tool、Loki Tool、SQL、LogQL 等旧产品入口。
- [身份关联被理解为权限同步] → 在身份卡和权限交集区域重复表达“关联不等于授权”，ONES权限仍由ONES/API平台决定。
- [模板遗留英文和无关示例] → 验收时扫描 Revenue、Visitors、Documents、Projects、Acme 等模板残留，并执行桌面/窄屏视觉检查。

## Migration Plan

1. 记录当前模板构建结果和可复用 shadcn 组件，不恢复已删除的旧前端实现。
2. 建立新的 App Shell、导航配置和静态原型fixture，保持所有数据与后端隔离。
3. 依次替换模板 Header、Sidebar、指标卡、图表和DataTable为六个Dashboard评审区域。
4. 增加业务应用、平台调用链、Capability、安全边界和外部身份关联展示。
5. 执行模板残留、网络调用、禁用动作、响应式、可访问性、lint、typecheck和production build验证。
6. 若原型评审不通过，可回滚前端静态文件；本变更没有数据库和后端回滚步骤。

## Open Questions

无。原型统一采用虚构静态数据，不接登录、不接API、不实现任何业务操作；产品评审通过后再单独提出后端控制面和真实页面变更。
