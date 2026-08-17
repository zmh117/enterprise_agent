## MODIFIED Requirements

### Requirement: 原型提供Agent应用平台静态Shell
系统 SHALL 将现有通用模板替换为中文“Agent应用平台”Shell，并展示总览、业务应用、Agent配置、MCP工具、运行中心和系统管理的目标导航；除总览外的未实现模块 MUST 明确标记为规划中或不可操作。

#### Scenario: 查看平台原型导航
- **WHEN** 用户打开前端根页面
- **THEN** 页面展示Agent应用平台品牌、分组侧栏和总览内容
- **AND** 不展示Acme、Revenue、Visitors、Documents、Projects等模板术语

#### Scenario: 查看未实现模块
- **WHEN** 用户查看业务应用之外的规划菜单或动作
- **THEN** 页面以规划中、禁用或说明文本表达尚未实现
- **AND** 不导航到空白业务页面或伪造成功反馈

### Requirement: Dashboard明确区分原型数据与真实运行数据
系统 MUST 在页面全局和使用示例指标的区域标记“原型数据”或等效说明，所有人员、标识、数量、时间和运行记录 SHALL 使用非敏感虚构数据。

#### Scenario: 查看概览指标
- **WHEN** 用户查看业务应用、Agent Profile、MCP Tool和示例运行指标
- **THEN** 页面明确说明指标为静态原型
- **AND** 不暗示这些数字来自后端、数据库或实时监控

### Requirement: Dashboard展示目标控制面全景
系统 SHALL 在单一Dashboard中展示平台概览、代表性业务应用、完整调用链、Workflow预览、MCP Tool预览、示例运行记录、安全边界、外部身份关系和建设状态。

#### Scenario: 评审一次请求的目标链路
- **WHEN** 用户查看平台调用链区域
- **THEN** 页面按Channel、Business Application、Workflow、Agent Runtime、`tool-mcp`、Published Resource Revision和Delivery的顺序展示关系
- **AND** 能区分Agent Runtime、标准MCP传输和只读资源适配器的职责

#### Scenario: 评审系统建设状态
- **WHEN** 用户查看建设状态区域
- **THEN** 页面区分概念原型、后端已有基础、需要适配和尚未实现的能力
- **AND** 不把静态展示标记为已交付业务功能
