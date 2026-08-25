## 1. Runtime 1.4合同与数据边界

- [x] 1.1 从仓库级Runtime合同事实源建立唯一可执行的protocol 1.4目录，扩展request、event、terminal、errors、limits和golden fixtures以容纳构建身份与`tool_contract_observed`，并让生成类型、Worker和Python Runtime不再引用1.3可执行合同。
- [x] 1.2 为工具契约定义有界Schema、统一输入Schema hash算法、来源与逐项/整体状态枚举，加入缺失远端工具、Schema不一致、未授权effective、Prompt过度声明和观测无效的稳定错误及retry class。
- [x] 1.3 增加前向数据库migration与schema fact source：保存Prompt版本/hash、扩展安全Runtime provenance，并为Job增加只含汇总状态、最后观测invocation和observation hash的可重建投影；不得复制既有Job MCP Tool Snapshot或改写1.3历史事件。
- [x] 1.4 更新Publication兼容性与Job创建校验，使protocol 1.4只接受新发布事实，protocol 1.3终态记录保持只读且所有非终态1.3恢复、投影或模型执行入口失败关闭。

## 2. 多组件构建身份

- [x] 2.1 实现共享的安全Build Identity模型与格式校验，为Control Plane、Agent Worker、Python Runtime和File Service提供`component`、`source_revision`、`build_id`、`platform`和可选`image_digest`，并拒绝外部payload覆盖。
- [x] 2.2 更新受影响Dockerfile、Compose和构建流水线，从同一发布清单注入revision/build ID/platform并在可准确取得时注入digest；禁止Docker socket探测、可变tag冒充digest和日志输出环境Secret。
- [x] 2.3 让相关服务health/readiness安全声明必需构建身份和当前协议，使缺失、非法或不符合发布清单的身份在入口恢复前失败。
- [x] 2.4 在File Service已认证MCP `initialize` namespaced experimental capability中返回安全Build Identity，并为未授权读取、字段边界和脱敏增加测试。

## 3. File MCP实时对账与Runtime有效工具

- [x] 3.1 扩展Python Runtime File bridge，在同一Job Principal MCP Session初始化后完整读取分页`tools/list`，拒绝重复名、非法名、分页循环、超限和不可规范化Schema，并生成有序live toolset hash。
- [x] 3.2 将File MCP live与既有Job Snapshot逐项比较：冻结缺失和Schema mismatch失败关闭，额外远端工具标记`EXTRA_REMOTE_IGNORED`且不暴露；覆盖`file_create_commit_intent`缺失和同名Schema变化回归。
- [x] 3.3 建立唯一Runtime effective registry，记录SDK精确可调用名、逻辑名、Schema hash、授权结果及`frozen_mcp|runtime_derived|sdk_builtin`来源，并把`select_sandbox_output`绑定到冻结且live匹配的`file_create_commit_intent`授权前提。
- [x] 3.4 从Runtime effective registry生成SDK Tool配置、审批边界和Prompt当前可调用工具片段，定义Prompt `template_version`与contract hash，删除静态Prompt中的人工当前工具名单并拒绝陈旧`allowed_tools`与`PROMPT_OVERCLAIM`。

## 4. Invocation观测、失败关闭与恢复

- [x] 4.1 在任何自动物化和首次模型请求前完成File MCP live、effective registry、Prompt contract和构建身份对账，并发出有界脱敏的`tool_contract_observed`事件；失败路径也必须先保存可诊断观测再产生唯一终态。
- [x] 4.2 扩展Worker Runtime request/client和严格事件校验，绑定Job Snapshot hash、Worker Build Identity、`invocation_id`与`request_digest`，拒绝未知字段、不同digest和不同observation hash。
- [x] 4.3 复用`agent_runtime_event`唯一约束幂等持久化工具契约事件，并实现Job汇总投影的事务更新与从不可变事件重建；后续`MATCH`不得覆盖同Job先前`DRIFT`。
- [x] 4.4 扩展Runtime终态恢复、断线恢复和orphan路径测试，证明同一invocation复用同一观测、不二次调用模型，protocol 1.3终态历史只显示`NOT_OBSERVED`且不可重放。

## 5. 运行记录API与管理端

- [x] 5.1 扩展授权后的运行记录列表查询，返回`MATCH|DRIFT|NOT_OBSERVED`汇总、最后观测invocation和安全组件身份摘要，保持现有Application、Session和Job资源授权。
- [x] 5.2 扩展Job运行记录详情API，组合既有Job Snapshot与逐invocation不可变事件，返回构建身份、四层工具事实、Prompt版本/hash和逐工具状态矩阵，不返回完整Schema、描述、Prompt或原始payload。
- [x] 5.3 更新管理端类型与列表页面，展示三态工具契约徽标并明确`NOT_OBSERVED`不等于健康；工具契约状态不得与Job执行成功状态混为一列。
- [x] 5.4 更新Job详情按invocation展示组件身份和四层矩阵，明确标识`runtime_derived`、`EXTRA_REMOTE_IGNORED`及稳定漂移原因，并为长名称/hash提供有界展示与复制能力。
- [x] 5.5 增加API与前端测试，覆盖无权访问、历史1.3、首次漂移后重试匹配、派生工具、远端额外工具和敏感字段负向断言。

## 6. 合同测试、部署切换与新鲜验收

- [x] 6.1 更新并运行protocol 1.4合同生成一致性、JSON Schema、golden、Worker/Python Runtime双端和发布产物负向测试，证明1.0至1.3没有可执行解析、协商或恢复分支。
- [x] 6.2 增加Build Identity与跨平台合同测试，证明同revision/build ID和toolset hash在arm64/amd64 digest不同时仍可比较，并证明缺失必需身份、伪造tag或组件跨发布会失败。
- [x] 6.3 增加File bridge、Prompt renderer、Runtime event、repository、运行记录API/UI的聚焦回归，并执行相关静态检查、migration测试、`docker compose config --quiet`、strict OpenSpec校验和`git diff --check`。
- [ ] 6.4 在维护窗口预检并排空或显式取消所有非终态protocol 1.3 Job、outbox、delivery和队列事实；任一安全计数非零时停止切换，不运行双协议消费者。
- [ ] 6.5 使用同一发布清单整体重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，创建新的protocol 1.4 Agent/Application Publication，并验证各组件revision/build ID/platform及可得digest。
- [ ] 6.6 运行无附件文字Job、File MCP读取、`select_sandbox_output → file_create_commit_intent → file_deliver_version`、缺失提交工具失败关闭和断线恢复的新鲜Compose E2E，核对运行记录四层事实与实际ToolUse/ToolResult后再恢复入口。
