# 验证记录（2026-11-12，本机部署）

- 8 个相关测试文件共 413 项用例通过；覆盖编码与底层库编码不同、编码/ID 二选一、授权拒绝、失效资源、资源替换、ONES 权限、代码环境与 SVN 版本、MCP 合同和 Runtime。
- Ruff、9 个实现文件的 mypy、OpenSpec change/canonical 严格校验及 git diff --check 通过。上述自动化测试使用合成数据，不等同现场检索验收。
- 已构建并更新 API、Agent Worker、Job/Channel/Webhook/Delivery Dispatcher、各相关 MCP、File Service、knowledge-sync 和两个 Python Runtime。
- assist03 激活应用发布第 75 版，绑定 Agent 第 58 版；保留原工具选择、业务权限、执行策略、会话策略、触发器与交付配置。发布的 knowledge_search schema hash 与当前合同匹配，冻结 Skill 包含 resource_code 用法。
- API、Agent Worker、Channel Dispatcher、Webhook Worker 的被动就绪检查均通过；两个 Runtime 的 Prompt 均为 agent-system-prompt-v18，状态 MATCH。
- 真实模型调试任务 job_aea363d411b54bf297f297287909d7b3：提问只给 mes_story 资源编码和打印失败检索内容，未提供 UUID。任务 SUCCEEDED，执行约 41 秒，仅一次 knowledge_search 调用且成功，未调用目录、ONES 查询或源码分析工具；工具合同 MATCH。调试交付方式为 none，未发送外部消息。
- 安全检索摘要确认命中 mes_story 对应知识库，返回 10 项，partial=false，执行了重排；该部署为既有 offline 访问模式，本次未更改访问模式。
- 核验仅读取任务状态、发布信息、工具状态和安全检索摘要；未读取原始业务正文或凭据。代码分析审计按既有规则省略工具参数正文，未为本次测试放开审计保护。
- 此记录证明本机发布与实际检索流程；其他部署环境仍需更新服务并发布对应应用。
