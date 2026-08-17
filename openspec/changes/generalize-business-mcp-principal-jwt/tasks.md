## 1. 基线与测试护栏

- [ ] 1.1 运行并记录现有Principal JWT、ONES MCP、Runtime HTTP、Python Runtime、File MCP、审计和沙盒聚焦测试基线，确认本变更开始前的可复现状态
- [ ] 1.2 为测试构造一个不进入生产Manifest的第二业务MCP固定策略与冻结Tool fixture，用于证明双Server token隔离而不宣称`dingtalk-mcp`已实现
- [ ] 1.3 先增加失败测试，覆盖通用签发的双audience/scope、未知或非业务Server、空/重复/漂移Tool、授权拒绝和Secret claims
- [ ] 1.4 先增加失败测试，覆盖Runtime逐Server Secret Header的成功、缺失、额外、重复、非法名称、超长、CR/LF和不落盘行为

## 2. 固定 MCP Server 鉴权策略

- [ ] 2.1 在代码拥有的MCP策略中定义`job-context`、`business-principal-jwt`和`file-principal-jwt`三种封闭鉴权模式，并为现有`tool-mcp`、`ones-mcp`和`file-service`建立唯一映射
- [ ] 2.2 扩展Manifest/Job快照验证，使每个Tool的`server_code`必须解析到唯一固定策略，并拒绝未知Server、模式缺失、重复Tool和schema/server漂移
- [ ] 2.3 实现业务Server code的header-safe规范化与唯一Header名称生成，拒绝不能无歧义映射的小写连字符格式
- [ ] 2.4 增加架构测试，禁止请求、数据库、Agent/Application配置或插件扫描创建Server、URL、鉴权模式和Principal传输策略

## 3. 通用业务 Principal 签发与验证

- [ ] 3.1 实现`issue_business_mcp_for_job(job_id, server_code)`并复用现有RUNNING Job、有效用户、Session和Agent/Application Publication事实校验
- [ ] 3.2 从已验证Job MCP快照精确筛选指定Server的唯一Tool集合，按identifier排序生成`mcp:<server_code>:<tool_identifier>:invoke`scope，并校验authorization hash
- [ ] 3.3 对筛选出的每个Tool逐项执行当前Business Application授权检查，任何空集合、重复、漂移或授权失败均整体拒绝签发
- [ ] 3.4 使用现有Ed25519/JWKS信任根签发`aud=server_code`且TTL不超过300秒的封闭claims，并确保claims不含Provider Credential、URL、Header、Prompt或Tool参数
- [ ] 3.5 将Principal签发成功/拒绝审计改为通用安全投影，保留audience、scope、Job、actor、kid、jti和稳定错误码且不记录JWT原文
- [ ] 3.6 将ONES调用迁移到`issue_business_mcp_for_job(job_id, "ones-mcp")`并删除`issue_for_job()`、固定ONES audience/scope签发分支及兼容包装
- [ ] 3.7 将业务Principal验证器改为构造时固定`expected_audience`，禁止从未验证claim、请求或Header后缀选择验证策略
- [ ] 3.8 在业务MCP调用前校验签名、issuer、audience、authorized party、时间/JTI、claims白名单和required scope，并重新读取RUNNING Job、用户、Publication、完整Server scope集合与authorization hash
- [ ] 3.9 更新ONES MCP启动装配使用`expected_audience="ones-mcp"`的通用验证器，并验证跨Server、File Principal和scope子集/超集均失败关闭
- [ ] 3.10 保持File Principal专用签发器、File验证策略、tenant/workspace和文件scope实现不变，并增加通用业务签发器显式拒绝`file-service`的回归测试

## 4. Control Plane 到 Runtime 的多令牌 Secret 传输

- [ ] 4.1 将Principal签发端口改为通用业务签发方法加独立File签发方法，并将`RuntimePrincipalTokens`改为只读`business: Mapping[server_code, token]`与`files`槽位
- [ ] 4.2 根据已验证Runtime请求中的冻结MCP bindings和固定鉴权策略确定所需业务Server集合，不从用户、模型或任意URL推断签发目标
- [ ] 4.3 为每个所需业务Server恰好签发一次JWT，拒绝未知模式、缺少issuer、空token、Server数量超限或总Secret Header字节超限
- [ ] 4.4 以唯一的`X-MCP-Principal-Token-<Server-Code>` Header逐Server传递业务JWT，继续以独立`X-File-Principal-Token`传递File Principal
- [ ] 4.5 确认业务token映射不进入Runtime请求JSON、request digest、Runtime Grant、Job payload、重试/恢复请求、事件或诊断，并扩展Header/key redaction规则
- [ ] 4.6 更新Runtime HTTP client测试，证明单ONES、测试双业务Server、业务+File、无Principal、签发拒绝和重试均使用精确且不复用的Header集合

## 5. Python Runtime 多业务 MCP 装配

- [ ] 5.1 将`InvocationSecretContext`和Executor端口从单一`principal_token`改为只读`mcp_principal_tokens`映射加独立`file_principal_token`，并保持安全`repr`
- [ ] 5.2 在Runtime HTTP入口按固定前缀解析逐Server Header，并要求业务Header集合与请求中`business-principal-jwt` bindings集合完全相等
- [ ] 5.3 对重复、未知、额外、缺失、非法名称、空值、超长和CR/LF token失败关闭，且错误、审计、Invocation ledger和terminal ledger不回显Secret
- [ ] 5.4 将Python Runtime Executor、fake provider和MCP调用辅助路径改为按当前`server_code`精确读取业务token，不允许默认、首个、ONES或File fallback
- [ ] 5.5 将固定业务MCP URL装配收敛为只读`business_mcp_server_urls[server_code]`，只允许启动装配从代码固定策略和显式部署配置构造，当前生产集合仍只包含`ones-mcp`
- [ ] 5.6 将SDK MCP配置改为为每个冻结业务Server创建独立URL/Header配置，并只注入该Server对应Bearer Token
- [ ] 5.7 通用化SDK Server alias和allowed-tool名称映射，保证不同header-safe业务Server得到无冲突固定别名且不影响Tool事件的原始`server_code`
- [ ] 5.8 保持`tool-mcp`无Authorization、`file-service`独立File Principal、进程内File bridge、File Transfer Context、任务沙盒和文件操作策略不变
- [ ] 5.9 增加Runtime服务与SDK装配集成测试，使用测试固定第二业务Server证明同一Invocation的双token隔离、并发调用和跨audience拒绝

## 6. 等价性、安全与残留检查

- [ ] 6.1 更新`test_principal_jwt.py`及相关身份架构测试，覆盖通用claims、完整scope相等、授权复核、审计安全投影、TTL/JWKS和全部拒绝路径
- [ ] 6.2 更新ONES MCP测试，证明查询、Provider Credential隔离、Job/用户/Publication复核和统一MCP Operation Audit行为与迁移前等价
- [ ] 6.3 更新Runtime HTTP与Python Runtime测试，证明token映射不会进入请求正文、摘要、事件、账本、日志、错误、模型上下文或Tool参数
- [ ] 6.4 运行File Service、File bridge、文件传输、工作区、审计和沙盒回归，证明File Principal特殊claims、scope和行为未改变
- [ ] 6.5 增加生产代码残留扫描，禁止`issue_for_job()`、`issue_dingtalk_for_job()`、其它`issue_<server>_for_job()`、业务单一`principal_token`槽位和旧通用`X-MCP-Principal-Token`Header；File专用命名除外
- [ ] 6.6 增加依赖与架构检查，证明未引入动态MCP注册、插件扫描、任意URL/Header/Token输入、第二套JWT信任根、MCP专用RBAC或Provider Credential泄漏

## 7. 最终验证与证据

- [ ] 7.1 运行Principal、ONES MCP、Runtime HTTP、Python Runtime、File MCP、统一MCP审计、身份和沙盒全部聚焦测试并记录结果
- [ ] 7.2 运行完整backend测试套件、Ruff、Mypy和compileall，修复全部由本变更产生的失败
- [ ] 7.3 运行主Compose与相关测试overlay配置校验，重建受影响Control Plane/Worker和Python Runtime镜像并检查服务健康及Worker镜像不含SDK/Runtime实现
- [ ] 7.4 在独立测试数据中执行ONES业务Principal调用和测试固定双业务Server调用，证明同一Job多audience/scope隔离；证据不得表述为真实`dingtalk-mcp`可用
- [ ] 7.5 创建`evidence.md`记录Confirmed-current测试、静态检查、Compose/镜像和验收结果，并明确DingTalk Server/Tool/Provider Credential/真实E2E仍属后续变更
- [ ] 7.6 运行`openspec validate generalize-business-mcp-principal-jwt --strict`、`openspec validate --all --strict`、Markdown链接检查、Secret残留检查和`git diff --check`
- [ ] 7.7 复核git diff只包含本change实施与必要测试，保留其它未提交工作，不同步canonical specs、不归档、不提交、不推送
