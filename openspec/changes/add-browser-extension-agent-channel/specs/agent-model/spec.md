## ADDED Requirements

### Requirement: Agent 发布固定允许收发的浏览器插件连接

Agent 配置界面和发布校验 SHALL 支持在入口与投递方向选择受管浏览器插件 Connector。Publication MUST 按方向冻结确切连接；只有两个方向均允许该连接时，业务应用才可用它配置插件问答。Agent 的模型、工具和项目上限继续由其发布快照决定。

#### Scenario: 管理员发布可供插件使用的 Agent
- **WHEN** 管理员为两个方向选择同一启用的插件连接并通过现有发布校验
- **THEN** 新 Publication 含有两个方向的对应连接，业务应用可据此保存并校验插件问答配置

#### Scenario: Agent 只允许入口或只允许投递
- **WHEN** 应用尝试使用该版本配置插件问答
- **THEN** 应用得到可定位到连接/方向的错误，不能借用草稿或另一 Agent 版本的许可
