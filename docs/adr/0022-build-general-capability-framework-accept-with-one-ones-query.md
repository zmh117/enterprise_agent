# 建设通用 Capability 框架，只用一个 ONES 查询验收

第一版交付受治理 API Connection、Authentication Profile、用户 Token 凭据、一体化 Capability 配置、固定 HTTP JSON Executor、受限 Mapping Plan、版本发布、应用绑定和运行时授权框架。框架支持 ADR-0033 定义的 Agent 能力组合，并用测试专用的两个 Capability Fixture 验证前一规范化输出可以由 Agent 组织成下一 Input Schema；真实端到端仍只验收 `cap__ones__work_item__search`：在当前用户绑定的默认 Team 中按关键词和需求、任务或缺陷类型返回有界摘要。详情、写操作、跨 Team 聚合、第二个生产 ONES Capability 和其他 Provider 延期。
