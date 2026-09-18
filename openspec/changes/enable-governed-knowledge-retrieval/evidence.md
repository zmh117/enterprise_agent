# 受治理知识检索实施证据

## 实施前核对（2026-09-18）

- 实施起点 commit：`898a853`；开始时工作区干净。未执行 Docker 清理、真实部署、数据发布、授权配置或归档。
- 当前 canonical 的 platform-operations 仍只覆盖离线存储/导入，未同步清洗分块与本地向量索引 delta；前置两个 change 在 `openspec list --json` 中分别为 8/8、19/19。当前变更明确依赖其代码事实，不自动同步或归档它们。
- 当前 catalog 最后一项为 `136_expand_sandbox_v2_capacity.sql`。知识存储通过同库 `knowledge` schema；新增治理元数据不得改写 131/133/134 或原有文档、分块、向量身份。
- `VectorService.query` 仅为受限运维检索：READY/profile 检查、本地 Embedding、至多 200 个候选点、当前收录与版本核验、文档去重和每文档最多 3 个证据；尚无 KB/ONES 双权限或用户模型边界。
- 当前 MCP policy 尚无 knowledge-mcp；`PrincipalTokenVerifier` 校验 scope 必须恰好等于当前完整冻结集合，并核对 authorization_hash，不能为权限桥弱化为 scope 子集。
- 当前模型连接发布固定 revision/config hash；Runtime 通过主模型及 Opus/Sonnet/Haiku/Subagent 映射调用 Anthropic-compatible 服务。内部网关白名单只属于连接准入，不构成无外部转发认可。受保护 Session/摘要/产物传播仍需本变更实施。
- 已核对相关 canonical 的管理/业务权限隔离、同一事实源、固定 MCP、精确 Snapshot、模型发布和离线存储边界。本 delta 尚未发生前置同步冲突。

## 验收分层

| 层级 | 状态 | 证据边界 |
| --- | --- | --- |
| 代码与静态合同 | 实施中 | 按实际修改与检查记录，不代表已部署 |
| 合成单元/接口 | 待执行 | 不使用真实业务文本/凭据 |
| 隔离数据库/容器 | 待执行 | 不迁移正式库，不替代真实 Provider |
| 真实 ONES 来源和本人权限 | 未完成 | 待批次来源确认、技术交叉验证及两位测试用户 |
| 内网模型与出口 | 未完成 | 待实际模型/网关和所有映射出口证据 |
| 人工业务效果 | 未完成 | 待约 50 条人工标签及用户确认质量/时延目标 |

原文自查询、合成案例和真实人工评测必须分别记录。任何失败不得回显查询、标签、原始 Provider 响应、凭据或业务正文。

## 本地评测工具

- 新增严格 JSON 标注集合同和 owner-only 文件/目录读取；明确区分人工、合成、自查询。真实目录 `.local/knowledge-evaluation/` 被 Git 排除，只提交虚构样例。
- `evaluate_knowledge` 支持无数据库的 `--validate-only` 和当前 schema 的离线 dense 评测。复用现有 query，不写索引/来源；全部标签先解析到当前收录文档，再发查询，结束复核语料与实现摘要。
- 输出文档 Recall@10、MRR@10、无答案误报、nearest-rank 延迟、partial/bounded 和固定失败分类；调用失败不从有答案分母消失，无答案故障不伪装成正确拒答。问题、query_id、标签、命中明细和原始异常均不输出。
- 权限后可见相关集合的纯指标测试已覆盖，但离线 CLI 不执行真实用户权限/详情链路：`authorization_verified=false`、`end_to_end_latency=null`，不接受 JSON 自报 allowlist。
- 新增 30 项合成测试；知识评测/向量/分块/导入/Compose/测试治理组合回归：124 passed、3 skipped（38.61 秒）。跳过项要求显式隔离 PostgreSQL/Qdrant 端点，未使用正式库代替。
- 三个新增生产 Python 文件 Ruff 与严格 MyPy 通过，测试文件 Ruff 通过。没有读取真实问题、调用外部模型或更改部署；尚无真实 Recall/MRR 基线。
- 主/可选知识 Compose 配置、全仓库 Markdown 链接、严格 OpenSpec 与已跟踪/新增文件差异检查通过。当前进度 5/39，未提交、未推送、未归档。

## 实施暂停点：直接 Agent 的业务授权对象

任务 5.2 和 identity-access delta 要求直接 Agent 也有明确 KB grant，但目前设计未规定该 grant 归属的业务访问对象、委派及角色编辑合同。实际代码与数据库仅有业务应用路径：

- `rbac_role_application_access.application_id` 为非空外键；其 Tool/数据范围共同归属于该访问记录，没有直接 Agent 对等业务记录。
- `BusinessAuthorizationService.decide` 在找不到业务应用时返回 `application_not_found`；`PrincipalTokenIssuer.issue_business_mcp_for_job` 对每个工具都复核 `business_application_id` 的业务授权。
- `OnesPrincipalResolver.resolve` 同样通过业务应用授权服务复核详情 Tool。因此仅增加 KB 范围关系并不能让直接 Agent 完成 ONES 双权限链。

需要用户确认：首版只通过已有业务应用发布/运行知识 Agent（直接 Agent 继续拒绝），还是本轮增加直接 Agent 的角色业务访问记录、委派/Web 与 Principal/ONES 合同。不得默造应用 ID、借项目 use grant 或跨角色拼接绕过。当前尚未添加迁移、改写授权合同或注册知识 MCP；任务 3–11 保持未完成。收到选择后先同步本 change 的 proposal/design/delta/tasks，再继续 apply。
