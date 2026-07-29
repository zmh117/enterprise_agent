## ADDED Requirements

### Requirement: 工具资源运行时只能消费 PostgreSQL 已发布版本
DB、Redis、Loki runtime MUST 只从 PostgreSQL Published Resource Revision 和应用发布 binding 构建快照；YAML、环境变量或代码默认值不得在数据库版本无效时成为资源回退。

#### Scenario: 数据库存在有效发布版本
- **WHEN** Internal API Platform 构建工具资源快照
- **THEN** 它只消费已发布 revision、具体 binding 和 `secret://platform/` 引用

#### Scenario: 发布版本无效但 YAML 可用
- **WHEN** 数据库 revision 无法装载且部署中仍有旧 YAML
- **THEN** 运行时必须保持 Last Known Good 或阻止相关应用，不得使用 YAML 替代

### Requirement: YAML 和 env 只能参与 bootstrap 或显式 import
系统 SHALL 允许部署必需的 bootstrap 配置继续来自 env/文件，并允许显式导入旧资源配置；导入后必须经过 Draft、验证和发布流程。

#### Scenario: 导入旧 env Secret
- **WHEN** 管理员显式执行旧资源迁移
- **THEN** env 值只读取一次并转换为平台 Secret，运行时资源不再直接引用 env

### Requirement: 资源快照必须支持无锁读取和原子 generation 切换
运行时 MUST 为每个请求捕获单个不可变 effective generation；热加载不得让同一请求混用两个 Resource Revision。

#### Scenario: 请求执行期间发生热加载
- **WHEN** 新 generation 在一个工具请求执行中完成激活
- **THEN** 当前请求继续使用启动时捕获的 generation，后续请求使用新 generation
