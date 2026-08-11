# 按操作语义而不是 HTTP Method 判断只读能力

Capability Handler 必须声明业务操作语义，第一版只支持 `QUERY`。查询可以使用 HTTP POST，但 GraphQL Document 固定在不可变 Handler Revision 中并拒绝 `mutation`；Agent 只能提供 Input Schema 允许的变量，不能提交原始 GraphQL、任意请求体或响应字段。写入类 `COMMAND` 延期到具备确认、幂等和增强审计的独立变更。
