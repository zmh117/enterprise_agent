# API Capability 拥有公开 Schema，Handler 实现该契约

Agent 可见的输入、输出和业务语义 Schema 归不可变 API Capability Revision 所有。Capability Handler 只负责通过受限 Mapping Plan 把该契约映射到外部接口，并在发布前证明输出满足 Capability Schema。外部接口或字段位置变化但业务契约不变时只发布新 Handler Revision；公开 Schema 或业务语义不兼容时才发布新的 Capability Version。
