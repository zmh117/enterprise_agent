# 统一身份 ONES MCP

本文按2026-09-16代码修订，是实现摘要；当前规范见[受治理业务API](../../openspec/specs/governed-api-capability/spec.md)和[身份授权](../../openspec/specs/identity-access/spec.md)。

`ones-mcp`是代码注册、身份感知的独立MCP Server。当前目录已覆盖工作项、项目、迭代、人员、条件与测试资产查询，以及受逐次确认保护的缺陷创建和更新；不是仅两个只读工具的旧MVP。准确Tool与字段见`backend/app/shared/ones_tool_contracts.py`和`services/ones_mcp_server/`。

## 查询与Provider边界

- `ones_work_item_search`由服务按固定GraphQL operation自动有界收集，不接受模型传入limit/cursor。
- 集合查询区分接口与集合上限：四类测试资产最多10000，其余相关自动收集集合最多1000；bucket/tasks/pageInfo按代码精确解析，不能用total代替实际明细。
- 项目、迭代、用户、查询条件和自定义选项由固定Tool解析，不允许模型提交任意GraphQL、REST路径、Header、URL或凭据。
- 显示名称与ID、接口时间单位、空关联占位和输出文件引用按Tool合同规范化；输出有界且标记为不可信外部数据。
- 查询结果可投影为Job临时只读文件，不能因此生成Workspace正式版本或扩大文件访问权限。

## MCP与身份

服务使用固定Streamable HTTP `/mcp`，先验证业务Principal、audience、精确Tool scope和当前Job事实。无认证、错误Host/Origin、超大请求、未知Tool或合同漂移失败关闭。

ONES身份由当前Web用户完成本人验证Challenge和Team选择；登录材料与当前凭据加密存储，与外部身份状态分别管理。管理员不能代替本人验证或读取密码/Token。解绑允许按当前唯一性规则重新绑定，不能照搬旧“永久占有已解绑主体”的描述。

Worker从固定Job/Publication/Tool Snapshot和当前授权签发短时Principal；Runtime只在受控内存Secret Context中转交。服务调用前复核用户、身份、Team、Credential、工具与业务范围，不从模型输入接受授权主体或Provider凭据。

Provider 401刷新遵守锁、revision和身份复核；刷新失败或主体/Team变化要求本人重新验证，不回退其他用户或旧Token。具体刷新状态和审计字段以身份领域代码为准。

## 缺陷创建与更新

模型调用mutation先准备冻结的Action Intent，完成字段、当前身份和权限预检，再向原用户请求逐次确认。用户确认不是直接向Provider提交任意请求；独立外部操作worker按代码固定operation执行，执行前再次核对主体和授权。

创建具有固定字段目录、关联校验、修订替代和防重复身份；更新使用严格Patch、当前快照差异和陈旧确认检查。无法确认外部结果时不能把请求当作普通瞬时错误安全重发。共享确认、卡片Outbox和执行状态见[执行与投递](../../openspec/specs/execution-delivery/spec.md)。

## 审计与验收

MCP操作审计关联Job、Tool Call、固定Provider operation、授权、Credential revision、耗时和安全结果。普通摘要不含认证材料或无界Provider响应；完整运行上下文审计是另一条授权存储边界。

本地测试替身可以验证合同、授权、刷新、分页、错误和mutation状态处理，但不证明真实ONES权限、字段布局或创建/更新结果。本次文档重建未调用真实ONES，也未完成真实钉钉确认链；归档任务中的未完成验收仍保持未完成。
