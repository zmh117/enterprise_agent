## 1. 工具契约与分页协议

- [x] 1.1 更新 `ones_work_item_search` 输入输出 schema、Tool 描述和固定 schema hash 相关断言
- [x] 1.2 为续页游标实现 Job、查询、授权、身份与 Team 绑定以及 500 条累计上限

## 2. Provider 与服务实现

- [x] 2.1 将解码后的 `after` 注入固定 ONES GraphQL pagination 变量并保留单页 50 条边界
- [x] 2.2 规范化 `returned/cumulative_returned/truncated/next_cursor/pagination_limit_reached` 并对缺失续页位置失败关闭
- [x] 2.3 保持个人 Credential、401 单次刷新、Provider 审计和固定 Operation 安全边界

## 3. Mock 与自动化验证

- [x] 3.1 更新 ONES Mock 的分页请求校验和多页响应
- [x] 3.2 覆盖第一页、合法续页、终页、非整除 500 条上限及 Provider 缺失 endCursor
- [x] 3.3 覆盖篡改、跨 Job、跨查询、跨授权、跨身份和跨 Team 游标拒绝且 Provider 零调用
- [x] 3.4 运行 ONES MCP、Principal、Runtime、管理契约和 schema drift 相关回归及静态检查

## 4. 发布与验收

- [x] 4.1 严格校验 OpenSpec，重建并替换本机受影响服务，验证健康状态和固定 Tool schema
- [ ] 4.2 重新发布 Agent 与业务应用后，用超过 50 条的真实只读结果完成续页与终页验收；若无可用数据则明确保留为真实环境待验收
