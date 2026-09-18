## Why

现有 5000 个 ONES 缺陷、8309 个分块已完成本机向量索引、零编码重放和重启验收，但当前代码仅提供受限运维 CLI，尚未提供角色授权、知识库 MCP 或 Web 配置。下一阶段需要先建立真实问法的评测基线，再打通“授权检索 → ONES 工作项定位 → 当前用户回源查询”的 Agent 使用链，不能把原文自查询成功当成业务召回率或读取授权。

## What Changes

- 建立本地评测入口和人工标注集格式，首批目标约 50 个真实业务问题；区分人工标注、合成用例和原文自查询，报告 Recall@10、MRR、延迟与失败分类，不编造目标值或自动生成正确答案标签。真实评测文本不提交仓库，不打印到会话、日志或外部服务。
- 提供代码固定的 `knowledge-mcp` 只读能力，首版拟包含“列出可访问知识库”和“检索知识库”两个工具；复用现有 Principal、精确 Tool Snapshot、发布子集、当前授权复核和安全审计，不新增任意 URL/SQL/Qdrant filter 执行入口。
- 为角色增加明确的知识库访问范围，并与当前用户 ONES 可读权限双重校验后才返回命中；不把 Environment/Base/Workshop 或资源 placement 复用为知识库权限，不因平台管理员、数据已入库或向量存在而自动授权。
- 在 Web“工具资源”内提供知识库管理入口，引用现有知识库和已验收索引，展示可用状态、版本及安全诊断；角色授权区选择知识库。首版复用本平台 PostgreSQL 与现有内部 Qdrant/Embedding，不为每个知识库复制部署，不允许模型或浏览器提交任意连接地址和凭据。
- 知识库召回输出需能定位原 ONES 工作项，保留版本、证据引用、去重与 partial 语义；首版保持引用优先，不返回缓存标题、摘要或正文。Agent 继续通过现有 ONES MCP 查详情，不把知识库 MCP 做成第二个 ONES 全功能客户端。
- 用户已确认全文链路只用本地/内网模型。对发布知识工具的 Agent、Job 和恢复会话实施模型数据边界检查，覆盖主模型、子 Agent、压缩/总结和 fallback；不能仅保证 Embedding 本地，却把 ONES 正文或检索结果交给外部聊天模型。
- 增加离线来源与可信 ONES 实例/Team 的显式核验步骤；保留离线来源、文档和索引身份，不猜测绑定、不覆盖历史证据。未确认的来源不得自动进入真实 ONES 回源链。
- 分阶段验收评测、授权/撤权、MCP 合同、Web 配置和真实新 Job；明确合成与真实 Provider 证据的区别，旧 Job/旧 Publication 不自动获得新工具。
- 不包含在线采集、定时增量、OCR/附件下载、工单/需求正文导入、混合召回、Reranker、多向量后端或 20 万缺陷容量承诺。本轮提案编写不执行 DDL、重建索引、发布授权、真实 ONES 请求或业务部署。

## Capabilities

### New Capabilities

无新增 canonical 领域；继续使用当前十领域导航。

### Modified Capabilities

- `platform-operations`：知识评测、离线来源核验和可选知识服务运行/验收边界。
- `builtin-tool-resource`：知识库管理资源和固定 `knowledge-mcp` 的注册、发布及安全可用性合同。
- `identity-access`：知识库业务范围、当前授权复核、独立 MCP audience，以及知识库授权与 ONES 权限的关系。
- `governed-api-capability`：知识召回与现有 ONES 本人身份回源之间的受治理定位合同。
- `agent-model`：知识数据全链路限定本地/内网模型的发布、运行和会话复用校验；不能假设现有模型连接已满足内网要求。

## Impact

### 当前代码事实

- `backend/app/modules/knowledge/vector_service.py` / `vector_repository.py` 提供 READY 索引检索、当前版本/收录检查、文档去重与证据定位；现有检索返回内部文档/块引用，没有角色或 ONES 当前用户可读性判断。
- `backend/app/modules/knowledge/import_service.py` 固定创建 `offline_unverified` 来源及 `storage_only` 知识库，并在重复导入时核对这些身份；不能直接改状态再假设原导入器与索引器仍兼容。
- `backend/app/shared/mcp_server_policy.py` 当前注册 tool-mcp、ones-mcp、dingtalk-mcp、file-service，尚无 knowledge-mcp。
- `backend/app/modules/platform_config/application/governed_resources.py` 当前资源 Provider 仅 Database/Redis/Loki；它的环境拓扑范围与知识库范围不是同一概念。
- `backend/app/modules/authorization_center/infrastructure/repository.py` 当前应用范围使用环境/基地/车间，不具备知识库授权；新增范围须进入现有授权事实源及摘要/撤权机制，而非旁路 ACL。
- 当前清洗分块和向量索引两个 change 均已完成任务但尚未归档；其 delta 不能冒充已同步 canonical baseline。后续设计必须显式保留这两个实现前提，并在其同步后重验本 change 的 delta。

### 涉及范围

knowledge 模块、受治理资源管理、RBAC/Principal、代码 Tool Manifest、Python Runtime 固定 MCP 接线、ONES 只读回源边界、Web 工具资源/角色页面、相关前向迁移与测试。迁移编号和表结构须在设计确认及实施前按当前 catalog 核对，不预占版本或修改历史迁移。

### 已确认决策与未就绪条件

- 用户已于本轮确认“角色知识库授权 + 当前用户 ONES 可读权限”双重校验，以及检索结果/ONES 正文全链路不得发送外部模型。
- 已完成变更的归档对象仍待选择；分页变更不在范围内。选定后须先展示 canonical 同步差异再确认同步方式，不能因本提案已创建而自动归档。
- 真实 ONES 实例/Team 的来源证明、可用且验收过的内网聊天模型、约 50 条人工相关性标注尚未取得。本 change 可先实现合成测试与接口，但这些缺口必须保持为真实上线/效果验收门槛，不能补勾。
- 本轮只编写提案及配套设计/规范/任务，不构成真实数据发布、授权配置或部署操作的执行记录；不得索取或保存明文凭据。
