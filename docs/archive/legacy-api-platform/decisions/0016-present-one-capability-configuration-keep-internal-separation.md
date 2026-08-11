# 对管理员呈现一个 API 能力配置，内部保留 Capability 与 Handler 分离

管理员在一个工作台配置 API Capability 的业务契约和 Handler 调用规则。工作台固定包含能力定义、Agent 输入字段、Agent 输出字段、Handler 映射和测试预览五个区域；测试区按 ADR-0034 接受模拟 Agent 输入并展示请求与规范化输出预览。管理员只执行一次 Verify 和一次 Publish，平台按 ADR-0036 与 ADR-0046 在单一幂等事务中生成所需的 Capability Revision、Handler Revision 和单调递增的 Capability Release Revision。产品不要求管理员分别创建并手工绑定两个对象；平台内部仍分离业务契约与外部调用实现，以便接口映射变化时替换 Handler 而不改变 Agent 可见的 Capability Schema。
