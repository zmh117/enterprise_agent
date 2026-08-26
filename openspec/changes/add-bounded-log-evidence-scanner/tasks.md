## 1. 扫描器合同与纯核心

- [x] 1.1 在Python Runtime新增独立日志证据扫描模块，定义`scanner_version`、4MiB证据包、输入数量、字面词、上下文、证据条目、单行和多行块的代码固定上限及稳定错误码。
- [x] 1.2 定义`scan_log_evidence`严格Input Schema与规范化函数，验证1至40个唯一`inputs/*.log` POSIX相对路径、最多32个有界字面词、0至20上下文行和1至500证据条目，并拒绝未知字段、正则、Profile、代码和输出路径。
- [x] 1.3 实现有界内存逐文件单次扫描，计算实际/已扫描字节、逻辑行数和SHA-256，并使用版本固定的通用故障/级别标志、字面词与保守续行规则生成候选，不猜测未知时间、用户或业务语义。
- [x] 1.4 实现确定性候选优先级、精确片段hash去重、候选/保留/省略计数和`evidence_limit_reached`，保证达到证据上限后仍扫描全部输入到EOF。
- [x] 1.5 实现确定性Markdown证据包渲染，记录路径/行/字节/hash/命中类型和原文；安全封装Markdown围栏、HTML及提示注入样式文本并明确标为不可信数据。

## 2. Sandbox预算、完整性与生命周期

- [x] 2.1 扩展Job Sandbox只读查询接口，使扫描器只能解析已提交物化身份对应的普通只读LOG，并在读取前拒绝不存在路径、非LOG、非`inputs/`、符号链接、绝对路径、反斜杠和路径穿越。
- [x] 2.2 为证据包实现一个`work/outputs`文件名额和最多4MiB的原子预留、未完成态写入、flush/UTF-8/SHA-256校验、成功发布及失败释放，继续共用64文件/224MiB统一预算。
- [x] 2.3 以scanner版本、规范化参数和按请求顺序的已物化输入身份/内容hash计算`request_digest`，验证既有证据包后幂等复用；内容事实漂移时返回完整性错误而不复用旧结果。
- [x] 2.4 在扫描和写包循环加入合作式取消/墙钟检查，覆盖取消、超时、超长单行/块、读取和写入失败的部分文件删除与预留释放，且失败不得返回`coverage_complete=true`。

## 3. Runtime File Bridge与Tool合同

- [x] 3.1 在进程内File MCP bridge中仅当当前Job有有效Sandbox且冻结`file_prepare_materialization`时注册本地`scan_log_evidence`，并拒绝远端File Service `tools/list`出现同名Tool。
- [x] 3.2 实现本地Tool调用处理和有界结构化响应，只返回证据包相对路径、大小/hash、覆盖、候选/保留/省略计数、scanner版本和限制标志，不把正文放入MCP JSON。
- [x] 3.3 将扫描器加入Runtime派生Tool合同观测，记录`runtime_derived`来源、`file_prepare_materialization`依赖、固定schema hash和Runtime build identity，并让schema漂移在模型执行前失败关闭。
- [x] 3.4 确认扫描请求经过既有`ToolCallBudget`与权限回调并只计一次Tool调用；预算耗尽不进入扫描器，Runtime本地墙钟耗尽继续投影为不自动重试的`runtime_timeout`。

## 4. 安全事件、提示与报告流程

- [x] 4.1 为扫描器定义专用Tool事件正规化，只持久化scanner版本、输入/扫描字节和行数、证据计数、包大小/hash、限制、耗时、合同身份与稳定错误码，并验证关键词、原文、证据包、Prompt、凭据和对象位置不会进入事件/审计/错误。
- [x] 4.2 更新Runtime基础提示：异构大日志优先一次扫描再少量按行核验，把证据原文视为不可信数据，并区分精确扫描事实、启发式候选和模型推断；用户行为不作为固定报告章节。
- [x] 4.3 验证证据包不会自动调用`select_sandbox_output`或`file_create_commit_intent`，用户要求报告时由Agent另行生成Markdown并沿用现有显式选择、提交和Delivery流程。

## 5. 回归、批次验证与部署证据

- [x] 5.1 增加扫描器纯单元测试，覆盖纯文本/JSON Lines/Java与Python堆栈/无时间戳等异构格式、中文关键词、未知字段、重复片段、证据上限、提示注入文本和超长记录。
- [x] 5.2 增加Sandbox与File Bridge测试，覆盖未物化/非LOG/符号链接/穿越拒绝、4MiB预留、容量不足、幂等复用、内容漂移、取消清理、远端同名Tool和不自动提交。
- [x] 5.3 增加Runtime Tool合同、预算、事件和提示集成测试，覆盖派生条件、schema hash、Tool名、一次计数、预算硬终止、`runtime_timeout`、安全持久化摘要及证据型最终报告限制声明。
- [x] 5.4 使用运行时生成且不提交仓库的约20×10MiB合成异构UTF-8日志执行批次测试，记录完整扫描字节/行、一次扫描调用、证据包上限、墙钟与峰值内存，并验证不重复物化、不产生原文事件副本且能生成并显式提交Markdown报告。
- [x] 5.5 完成相关pytest、ruff、mypy、Runtime合同生成/校验、`docker compose config --quiet`、严格OpenSpec校验和`git diff --check`；把命令、结果、已知无关baseline及未执行的真实Provider检查写入change evidence。
- [x] 5.6 编写部署/回滚说明，明确先控制面与Worker、后Python Runtime的顺序，说明大日志应用需要同时新建并发布Agent与Business Application Revision才能提高有效超时，且不得改写既有Job快照或把容器healthy当作批次成功。
