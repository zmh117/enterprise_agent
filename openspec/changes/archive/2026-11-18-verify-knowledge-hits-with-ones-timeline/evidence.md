# 验证记录（2026-11-12）

## 已确认

- 相关回归 522 项通过：消息分页、ONES 接口/运行时/HTTP、消息文件桥、知识工具合同及 Python Runtime。
- 最后补充类型和安全摘要调整后，消息/基础接口 33 项及基础接口/MCP 52 项复核通过；这些子集与上述回归重叠，不累加为测试总数。
- 变更 Python 文件 Ruff、6 个实现文件 mypy、OpenSpec 严格校验及 git diff --check 通过。
- 合成 101 条消息跨两页：第二页“现场未换包，回归仍复现，重新打开”保留到 Job 只读结果文件；模型摘要携带完整性字段，Job 结束删除。该验证不使用真实业务正文。
- 覆盖 0/1/99/100/101/1000/1001 条、短页续页、页数上限、重复消息/时间倒序异常、空续页、协议错误、后页权限失败、时间/容量上限、长正文截断、脱敏和禁止模型指定游标。
- 已构建并更新 API、相关 Worker、MCP、knowledge-sync 和两个 Python Runtime；保留两个 agent-worker 副本，不更新向量集合或索引。
- assist03 激活应用第 76 版，绑定 Agent 第 59 版；执行策略、权限、工具选择、触发与交付配置保持原配置。API 与 Worker 的 ones-query Skill 内容和当前源码一致。
- 两个 Runtime 的 Prompt 均为 agent-system-prompt-v19；被动就绪检查通过，新 Job 合同状态为 MATCH。
- 目录独立复测 Job `job_e80c0c439d964a0e8fcb873c2dfb8397` 的 knowledge_list_bases 在 MCP 审计中为 SUCCEEDED。
- 最后一次模型链路复测 Job `job_45b5a477f9224e8c892f55507d39c322`：knowledge_search 成功，Agent 随后调用 ones_get_work_item_detail 和 ones_list_work_item_messages。两者 AUTHORIZATION 均成功、PROVIDER 均返回 ones_provider_unavailable。确认知识检索及命中后调用链生效；未取得评论文件，不能证明真实分页或模型已阅读评论。

## 真实链路尚未验收

- 首次模型复测 Job `job_19aa6204e5fd495f9739a869b8b7ea34` 未到详情或评论读取：知识工具失败，随后 ONES 查询返回 ones_provider_unavailable。Job 最终 SUCCEEDED 仅表示模型正常结束，不表示工具链通过。
- 当前本机 ones-mcp 的受管配置指向本机测试端点 host.docker.internal:19121。只读 TCP 检查返回 IPv4 ECONNREFUSED（111）、IPv6 ENETUNREACH（101），未取得 ONES 响应；没有修改其连接设置、身份绑定或凭据。
- 不以合成多页测试或 Runtime 健康检查代替真实 ONES 接口兼容性、权限和模型阅读行为验收。后续需在可达的授权 ONES 环境复测，确认详情/消息工具成功、实际 Read 结果文件，以及最终回答对未读完整范围的披露。
- 验证记录仅保留安全状态、错误分类、版本和 Job 标识，不保存原始业务消息、请求认证或评论正文。
