# API Capability 拥有公开 Schema，Handler 实现该契约

Agent 可见的输入、输出、业务语义 Schema 和业务 `description` 归不可变 API Capability Revision 所有。`description` 同时供 Agent、应用配置展示并作为模型 Tool 描述；管理端版本备注按 ADR-0041 与之分离。Input Schema 可声明字段名称、类型、说明、必填性、枚举、默认值以及字符串、数值、对象和数组边界，并成为 Agent 组织单次或组合调用参数的唯一契约。Capability Handler 只负责通过受限 Mapping Plan 把该契约映射到外部接口，并在发布前证明输出满足 Capability Schema。外部接口或字段位置变化但业务契约不变时复用 Capability Revision 并发布新 Handler Revision；公开 Schema 变化时在同一稳定 Capability Code 下创建新 Capability Revision；业务含义变化时必须创建新的 Capability Code。
