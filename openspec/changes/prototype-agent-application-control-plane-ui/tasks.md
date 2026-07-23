## 1. 模板基线与原型边界

- [x] 1.1 记录当前 `frontend/` 的依赖、shadcn组件、lint、typecheck和production build基线，确认不恢复已删除的旧管理前端
- [x] 1.2 盘点并标记需要移除的Acme、Revenue、Visitors、Documents、Projects、Lifecycle等模板演示内容
- [x] 1.3 建立静态原型验收清单，明确禁止登录、路由业务页、后端API、数据库读取、业务命令和模拟成功Toast
- [x] 1.4 设计虚构fixture的命名与脱敏规则，确保人员、外部账号、运行记录、时间和数量不会使用真实数据

## 2. 前端目录与应用Shell

- [x] 2.1 按设计建立实际需要的 `app/shell`、`app/navigation`、`contexts/overview`、业务展示context、`shared/presentation`和`mocks`目录，不创建空DDD分层
- [x] 2.2 保留 `src/components/ui` 作为shadcn生成目录，并删除或停止使用与新原型无关的模板业务组件
- [x] 2.3 实现中文“Agent应用平台”Header、示例环境状态和全局“原型数据”标识，不显示登录用户或真实租户信息
- [x] 2.4 实现总览、业务应用、Agent配置、API能力、运行中心和系统管理的分组Sidebar，未实现菜单统一展示“规划中”且不进入空页面
- [x] 2.5 验证Sidebar展开、收起和窄屏off-canvas仅属于展示行为，不触发路由、数据加载或业务命令

## 3. Dashboard平台概览与调用边界

- [x] 3.1 将模板收入与访客指标替换为业务应用、Agent Profile、API Capability和示例运行数量卡片，并在区域内标记静态原型
- [x] 3.2 实现Channel、Business Application、Workflow、Agent Runtime、Capability Gateway、API Platform和Delivery的静态调用链
- [x] 3.3 实现Agent平台与独立API平台职责边界卡，明确Agent Web不配置数据库、Redis、Loki或底层连接凭据
- [x] 3.4 实现安全边界卡，展示禁止SQL、Redis命令、LogQL、Shell、任意HTTP和高风险写操作
- [x] 3.5 实现“概念原型/后端已有基础/需要适配/尚未实现”的建设状态区域，避免把展示误标为已交付功能

## 4. 业务应用控制台展示

- [x] 4.1 实现钉钉私聊诊断助手、钉钉群聊诊断助手和Webhook告警分析助手三张静态应用卡
- [x] 4.2 为每张应用卡展示Agent Profile、Workflow、触发器、Capability数量、输出渠道、示例环境和发布状态
- [x] 4.3 实现应用概览、流程设计、渠道与触发器、能力授权和发布管理五个目标工作区的静态关系展示
- [x] 4.4 实现钉钉私聊、群聊和Webhook三种静态Workflow预览，并区分固定API节点与Agent自主Capability
- [x] 4.5 展示群会话用于上下文、当前消息发送人用于权限解析的差异，不使用群共享业务身份
- [x] 4.6 实现API能力目录预览，只展示业务编码、名称、描述、风险、环境和可用状态
- [x] 4.7 实现平台发布、应用授权、Workflow节点、Agent Profile和当前主体数据权限的Capability交集展示
- [x] 4.8 实现应用发布快照预览，展示Profile Revision、Workflow Revision、Capability Version、Channel Binding和策略版本
- [x] 4.9 确保创建、编辑、测试、保存、发布和回滚控件全部禁用或明确标记“规划中”，且没有模拟业务反馈

## 5. 多外部系统身份展示

- [x] 5.1 实现以内部联系人为中心的身份关系卡，展示同一人员关联钉钉、ONES和未来其他系统账号
- [x] 5.2 为外部身份展示Provider、虚构外部主体、租户或连接、消息来源/投递目标/业务主体等用途和验证状态
- [x] 5.3 实现已验证、待关联、冲突和停用身份的静态状态摘要，并说明手工绑定、自助验证、目录匹配和迁移等来源
- [x] 5.4 实现“身份关联不等于授权”说明，展示内部角色、应用权限、Capability、API平台和ONES原生权限仍独立生效
- [x] 5.5 展示群聊中不同发送人可关联不同ONES账号和数据范围，不展示群级共享ONES身份
- [x] 5.6 实现外部系统接入、用户与外部身份、角色与授权、Webhook/服务账号、审计和环境管理的信息架构预览
- [x] 5.7 确保页面不展示钉钉AppSecret、ONES凭据、Webhook Secret、内部Secret URI或任何真实身份数据
- [x] 5.8 确保绑定、解除绑定、自动匹配和冲突处理入口均不可执行

## 6. 静态性、安全与内容验证

- [x] 6.1 增加渲染测试，覆盖Agent应用平台导航、三个业务应用、调用链、Capability安全边界和多外部身份关系
- [x] 6.2 增加模板残留检查，拒绝Acme、Revenue、Visitors、Documents、Projects等旧示例文案重新出现
- [x] 6.3 增加静态性测试，验证页面渲染不调用fetch、XHR、WebSocket、EventSource或任何后端URL
- [x] 6.4 增加不可操作性测试，验证创建、绑定、测试、保存、发布、回滚等动作禁用且不显示成功Toast
- [x] 6.5 增加内容边界检查，拒绝DSN、数据库方言配置、Redis/Loki地址、SQL、Redis命令、LogQL、Shell、任意HTTP和Secret URI入口
- [x] 6.6 检查所有fixture均有原型标识且不包含当前数据库中的真实用户、任务、外部账号或运行数据

## 7. 响应式、可访问性与交付验证

- [x] 7.1 验证桌面多列Dashboard的信息层级、卡片间距、长文本截断、状态Badge和调用链可读性
- [x] 7.2 验证窄屏Sidebar、单列卡片、纵向调用链、表格替代布局和页面无阻断性横向溢出
- [x] 7.3 验证键盘焦点、图标名称、禁用原因、文字状态、颜色对比和不依赖颜色的状态表达
- [x] 7.4 运行前端lint、typecheck、测试和production build，确保当前单包Vite构建可重复成功
- [x] 7.5 使用真实浏览器检查桌面和移动端原型，确认控制台无错误且Network中没有后端业务请求
- [x] 7.6 执行 `openspec validate prototype-agent-application-control-plane-ui --strict` 并逐项核对三个规格中的全部场景
