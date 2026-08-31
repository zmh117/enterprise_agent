## 1. 官方契约基线

- [x] 1.1 固定 `dingtalk-mcp@latest` 与最新官方 OpenAPI/SDK 的版本、校验值、取证日期和来源
- [x] 1.2 建立七个启用 profile 的全量 Tool 契约矩阵，覆盖系统已注册和显式排除能力
- [x] 1.3 标出每个现有 Provider operation 的 host、版本、method、path、请求字段、响应字段及 legacy 替代结论
- [x] 1.4 记录 AI 表格官方 MCP v1 + operator 成功与系统 v2 拒绝的真实对照，并修正等价性结论

## 2. 失败优先的契约测试

- [x] 2.1 为 AI 表格 sheets/fields 的官方 `value` 响应和 records 的官方响应增加回归测试
- [x] 2.2 为 HTTP 2xx 未知结构、错误容器类型和缺少必需标识增加 `dingtalk_response_invalid` 测试
- [x] 2.3 为七个 profile 的官方 method/path/request/response 样例增加参数化契约测试
- [x] 2.4 为 Tool 名称、描述、Schema、目标策略与官方契约矩阵的一致性增加 catalog 测试
- [x] 2.5 为 notable v1 + operator 以及非删除数据表/字段能力增加契约、身份冻结和失败关闭测试

## 3. Provider 契约修复

- [x] 3.1 将通用响应 fallback 替换为按 operation 的严格官方响应解析
- [x] 3.2 修复 AI 表格数据表、字段、记录和分页投影，并保留真实空结果语义
- [x] 3.3 迁移全部已有新式官方等价接口的 `oapi.dingtalk.com` 调用并更新错误映射
- [x] 3.4 对最新官方资料仍只支持的 legacy operation 增加隔离说明和防漂移测试
- [x] 3.5 将 AI 表格资源读写恢复为官方 notable v1 + operator，并实现数据表/字段非删除 mutation

## 4. Tool 语义与发布合同

- [x] 4.1 按官方 MCP 重写全部已注册 Tool 的模型可见描述，并分离平台治理限制
- [x] 4.2 用独立群聊发送 Tool 和批量个人单聊 Tool 替代新 Publication 中含混的通用机器人消息 Tool
- [x] 4.3 校验 Manifest 的 operation、effect、confirmation、target policy、profile、Schema 和官方映射
- [x] 4.4 更新 catalog、Agent/Application Publication 和 Job 快照测试，证明新旧合同不被混用
- [x] 4.5 在钉钉连接器控制面增加独立 `ROBOT_CODE` 字段，并验证保存、保留、展示和应用发布前置校验
- [x] 4.6 在角色授权页显式展示已从当前应用 Publication 下线的历史 Tool，并允许创建新 revision 移除旧授权
- [x] 4.7 约束确认型 mutation 必须实际调用 Tool，并在 Worker 投递前拒绝无 Tool Event 支撑的确认卡成功声明
- [x] 4.8 注册 AI 表格三个静态说明 Tool 与非删除 mutation，更新 Action Intent、Worker、目录和 Publication 快照合同

## 5. 验证与部署

- [x] 5.1 运行钉钉 Provider、Action Intent、Runtime、Publication 和安全回归测试
- [x] 5.2 运行静态检查、Secret 扫描、`git diff --check`、OpenSpec strict validation 和 `docker compose config --quiet`
- [x] 5.3 重建并检查 `api-server`、`agent-worker`、`dingtalk-mcp`、Action worker 和相关 Runtime 的就绪状态
- [x] 5.4 创建新 Agent/Application Publication 与新 Job，完成七个 profile 的真实只读和错误分类验收
- [ ] 5.5 对纳入的 mutation 完成卡片确认后 Provider 回查，记录有界证据并确认历史 Job 未被改写
- [ ] 5.6 重建修正后的服务并用新 Publication、新 Job 完成 AI 表格只读、记录写入和非删除结构 mutation 验收
