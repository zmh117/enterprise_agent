## MODIFIED Requirements

### Requirement: Python Runtime必须实现版本化执行协议
Python Runtime MUST 只实现`python-v1` protocol 1.3的执行、事件、取消、终态恢复和错误schema。协议 SHALL 固定runtime kind、invocation、attempt、request digest、Publication/hash、模型连接、执行限制、Tool allowlist、correlation ID和schema v5文件上下文；Runtime URL不得来自Agent、Application、外部请求或模型输出。Worker、Runtime健康声明、合同生成代码和恢复路径不得支持、协商或投影protocol 1.0、1.1或1.2。

#### Scenario: 合同用例运行于Python Runtime
- **WHEN** contract suite以protocol 1.3对Python Runtime执行accepted、tool、completed、failed、cancel、有文件和无文件fixture
- **THEN** Runtime返回schema合法、sequence单调且唯一终态的结果

#### Scenario: Runtime协议版本不受支持
- **WHEN** Worker或Runtime收到1.3以外的协议版本、非`python-v1` runtime kind、非schema v5文件上下文或超限事件
- **THEN** 调用以稳定协议错误失败关闭且不执行模型

#### Scenario: 请求尝试指定任意Runtime地址
- **WHEN** Agent/Application配置或外部payload包含自定义Runtime URL
- **THEN** 系统拒绝该字段，只使用平台固定Python Runtime client

#### Scenario: 健康检查声明合同
- **WHEN** 运维读取Python Runtime无副作用健康信息
- **THEN** 响应只声明`python-v1` protocol 1.3和Manifest schema v5
- **AND** 不把旧协议列为可接受、可恢复或降级目标

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job创建事务 MUST 固定任务工作区ID、schema v5 Job File Manifest、`workspace_catalog_revision_id`以及当前附件、明确引用和已选Working Set中的精确File/Version ID；对需转换文档还 MUST 固定精确Markdown Representation ID、kind、size和SHA-256。该清单 SHALL 以有界、无正文、无凭据、无对象位置形式原样交给Python Runtime protocol 1.3，不得投影为旧Manifest。Runtime按需物化或交付时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界、source Version与representation血缘；不得读取清单外、Working Set上限之外、之后产生或已经内容不可用的版本/表示。

#### Scenario: 执行期间当前版本或表示变化
- **WHEN** Job固定source V3和representation R1后另一Job提交V4或处理器产生R2
- **THEN** 当前Runtime仍只把R1用于阅读并把V3用于原件身份
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: Representation与源版本不匹配
- **WHEN** Manifest或传输请求把属于另一source Version的representation绑定到当前文件
- **THEN** File Service在读取对象前拒绝并记录安全完整性错误

#### Scenario: Worker尝试投影旧Manifest
- **WHEN** Agent Worker准备protocol 1.3请求时取得的Job File Manifest不是schema v5
- **THEN** Worker在调用Python Runtime前以稳定合同错误终结执行
- **AND** 不进行v5到v4或任意旧schema投影

#### Scenario: 空文件上下文执行普通文字Job
- **WHEN** Job没有任务工作区附件、明确引用或已选Working Set
- **THEN** Worker发送合法的schema v5空文件上下文
- **AND** Runtime正常执行模型且不构造旧格式占位值

## ADDED Requirements

### Requirement: 当前执行合同不得包含旧协议实现
活动代码、生成合同、容器镜像和测试矩阵 MUST 只包含Runtime protocol 1.3与Manifest schema v5的当前实现。旧协议目录、类型、解析器、投影器、hash实现、fixture和条件分支 MUST 从运行源与发布产物删除；migration和OpenSpec中的历史标识只可用于说明被拒绝或被删除的事实。

#### Scenario: 构建当前Runtime镜像
- **WHEN** CI构建Agent Worker和Python Runtime镜像并检查安装内容
- **THEN** 只存在protocol 1.3合同与Manifest v5解析代码
- **AND** 不包含v1.0-v1.2合同模块或Manifest v1-v4运行fixture

#### Scenario: 旧终态Job尝试恢复
- **WHEN** 开放测试重置前发现使用旧协议或旧Manifest的终态Job
- **THEN** 重置删除该测试运行事实而不是恢复或重放
- **AND** 当前Runtime不提供旧Job恢复入口
