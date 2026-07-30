# 对管理员呈现一个 API 能力配置，内部保留 Capability 与 Handler 分离

管理员在一个工作台配置 API Capability 的业务契约和 Handler 调用规则，并通过一次验证与发布操作原子生成 Capability Revision、Handler Revision 和 Capability Release。产品不要求管理员分别创建并手工绑定两个对象；平台内部仍分离业务契约与外部调用实现，以便接口映射变化时替换 Handler 而不改变 Agent 可见的 Capability Schema。
