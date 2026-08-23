## ADDED Requirements

### Requirement: 开放测试文件域重置必须保持领域边界
开放测试文件域重置 SHALL 只删除File Service受管对象、文件域事实及其按外键拓扑强关联的终态测试Job、Delivery和Outbox事实。该命令 MUST NOT 识别、改写或删除Agent Definition/Publication、Business Application Revision/Publication、Route、Deployment、Tool/Skill/Channel/Webhook绑定；遗留Runtime、Profile或Publication配置 MUST 由单一合同migration失败关闭，不得由文件域重置自动解释或清理。

#### Scenario: 文件域为空但存在遗留配置
- **WHEN** reset预检发现文件域和受管对象已为空，但数据库仍有旧Runtime或旧Profile配置引用
- **THEN** reset不得删除或修改这些Agent/Application配置事实
- **AND** 后续单一合同migration保持失败关闭

#### Scenario: 文件域重置完成
- **WHEN** 非终态门禁通过且操作者提供精确确认后执行文件域重置
- **THEN** 命令只清空受管对象、文件域及强关联终态测试事实
- **AND** 不改变任何Agent/Application发布、路由、部署或工具绑定

### Requirement: Readiness只暴露有真实状态来源的字段
平台readiness响应 MUST 只暴露由配置验证、依赖探针、schema账本或当前Runtime合同计算得到的状态。系统 MUST NOT 为已删除的兼容检查保留恒真字段、固定成功占位或无当前消费者的旧状态别名。

#### Scenario: Runtime只保留当前实现
- **WHEN** readiness报告当前Python Runtime选择和运行探针
- **THEN** 响应包含当前runtime kind、protocol和真实探针结果
- **AND** 不包含恒为成功的旧runtime assembly兼容字段
