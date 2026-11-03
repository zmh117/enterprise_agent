## MODIFIED Requirements

### Requirement: 知识检索必须有界且只返回可读引用
`knowledge_search` SHALL 接受明确 `knowledge_base_id`、1–2000 字符非空查询和默认 10、范围 1–20 的 `top_k`，不得允许覆盖身份、Team、filter、collection、向量、排序模型或服务地址。目录和检索 SHALL 受最多 360 秒及当前 Job 剩余预算共同约束，重排不得另获一轮预算。检索 SHALL 只返回知识库/资源/索引身份、实际检索与排序方式、ranking profile 摘要，以及文档/修订/来源/工作项引用、编号、最终 `rank`、明确命名的 `retrieval_score` 和每项最多三条证据位置/hash；证据块分数 SHALL 同样命名为 `retrieval_score`，不得返回含糊的 `score`、重排 logit、缓存标题、摘要或正文。获取最新正文 SHALL 使用已有 ONES 详情工具。零命中、受限部分结果和依赖失败 MUST 分别表达；`partial=false` MUST NOT 被解释为全库穷尽。认证材料、查询原文和业务正文不得复制到普通安全摘要或日志。

#### Scenario: 延长硬预算仍继承较短截止
- **WHEN** 检索已超过原 240 秒，但未超过新的 360 秒、上游截止和 Job 剩余预算
- **THEN** 检索可以继续，并在原始剩余预算内完成后续阶段，不由中间客户端按旧的 240 秒上限提前终止
- **AND** 上游或 Job 更早到期时立即按原失败语义结束，不因进入重排或 ONES 核实重新获得 360 秒

#### Scenario: 合法检索
- **WHEN** 合同、索引与当前权限均有效且存在可读命中
- **THEN** 返回当前版本的有界引用与证据位置，并包含实际 `retrieval_mode`、`ranking_method`、`ranking_profile_hash` 和可读结果内连续的最终 rank
- **AND** 正文仍通过受治理 ONES 详情工具取得，响应不包含内部重排文本

#### Scenario: 预算或依赖失败
- **WHEN** 总预算耗尽、依赖异常或读取投影不完整
- **THEN** 返回稳定失败；正常有界搜索产生部分结果时明确 `partial`，不能将依赖失败报告为空库
- **AND** 重排故障不得静默回退为旧排序或伪装成成功的部分结果

#### Scenario: 返回数量已满
- **WHEN** 一次有界检索返回了请求的 top_k 条且 partial 为 false
- **THEN** 工具说明仍明确存在候选与文档上限，该状态不证明其他文档不存在相关结果

## ADDED Requirements

### Requirement: 知识检索必须在当前有界文档候选内重排
系统 MUST 在既有 dense 或 dense/BM25 RRF 召回之后校验点身份、payload、当前修订和块内容摘要，最多处理 200 点，按文档去重后依原排序保留最多 50 篇文档。系统 SHALL 为每篇构造最多两个已命中且校验有效的相关块文本，与本次完整 query 进行一次固定本地 Cross-Encoder 联合评分，并按重排分数、原检索分数和文档身份稳定排序。输入窗口、token 限额及截断规则 MUST 由固定 ranking profile 拥有；不得静默截断 query，也不得读取任意未命中的全文扩大输入。重排 MUST NOT 扩大候选集合、当前 KB 授权或 ONES 可读权限，不得写入文档、向量或资源发布事实。

#### Scenario: 多块属于同一文档
- **WHEN** 候选中同一文档命中多个块
- **THEN** 该文档只占一个重排名额，最多两个相关块共同组成一次文档评分输入，返回证据仍保留原始来源位置/hash

#### Scenario: 候选超过五十篇
- **WHEN** 200 点去重后包含超过 50 篇当前有效文档
- **THEN** 只对原检索顺序的前 50 篇重排，不增加一次隐式全库读取或第二轮召回

#### Scenario: 原检索低分文档经重排提前
- **WHEN** 两篇合法候选的 Cross-Encoder 顺序与原检索分数顺序不同
- **THEN** 最终结果遵循重排顺序，不因原检索分低于某个未经标定的阈值删除文档

#### Scenario: 排名靠前的事项不可读
- **WHEN** 重排前列文档未通过当前用户 ONES 可读性校验
- **THEN** 不返回该文档及其证据，从同一最多 50 篇池内继续补齐；返回 rank 连续编号，不暴露被拒文档的名次或数量

#### Scenario: 推理期间权限或文本变化
- **WHEN** 重排后返回前发现 Job/KB 授权、资源配置或实际重排输入的当前文档修订/块 hash 已改变
- **THEN** 调用失败，不返回基于旧授权或过期输入得到的顺序

#### Scenario: 没有当前有效候选
- **WHEN** 既有召回和当前版本校验没有产生可重排文档
- **THEN** 跳过模型推理，按既有有界搜索语义返回空结果，不伪造重排分数

### Requirement: 知识检索必须明确排序分含义并冻结版本
工具合同 SHALL 将召回方式标记为实际 `dense` 或 `hybrid_rrf`，将最终排序方法标记为 `cross_encoder`，并返回可验证的 `ranking_profile_hash`。`retrieval_score` MUST 仅代表该次、该种召回的排序分，不是概率、已确认相关度或根因可信度；最终顺序以 rank 为准。系统 MUST 在工具描述及 Runtime 知识指令中明确禁止 Agent 自设数值过滤阈值、按分数跨查询/跨库排序或将重排第一名当成已验证结论。该 breaking 合同 SHALL 通过 `knowledge_search` input schema 的固定 `$comment: knowledge-search-contract/v2` 进入既有 schema hash；该注解不得成为调用方可选参数，旧冻结 hash 不得静默改写。

#### Scenario: 混合检索分数较小
- **WHEN** hybrid_rrf 返回某文档较小的 retrieval_score
- **THEN** Agent 获得明确的分数解释和最终 rank，不得仅凭该数值把文档视为低概率相关而跳过核实

#### Scenario: 新输出运行在旧冻结合同上
- **WHEN** Job 或 Publication 仍冻结没有 v2 注解的 knowledge_search schema hash
- **THEN** 沿用既有合同不匹配拒绝流程，不自动更新快照或输出一个未被冻结的新合同

#### Scenario: 多次检索结果需要合并
- **WHEN** Agent 汇总多个 query 或多个知识库的返回
- **THEN** 按来源与工作项身份去重，依据已核实证据判断相关性，不直接比较、相加各次 retrieval_score

### Requirement: Agent 知识检索必须保持查询保真和核实边界
代码所有的知识指令 SHALL 要求首轮保留用户原始问题的对象、症状、否定词和已知条件；第一轮核实缺少足够证据且任务预算允许时，对同一知识库最多补一次保真的同义查询，不得加入未被用户提供或证据确认的现场条件。Agent MUST 按返回 rank 在预算内读取最新 ONES 详情，按 `(source_id, work_item_uuid)` 去重；未找到足够证据时不得仅因分数低而跳过剩余候选。Agent SHALL 说明已核实范围与未核实限制，区分症状符合、机制假设和现场根因；有界搜索、未读尾部、关闭状态或重跑结果均不得成为无证据确定性结论的依据。

#### Scenario: 首轮原始问题有两个并存症状
- **WHEN** 用户描述某业务动作已生效而流程状态未完成
- **THEN** 首轮查询保留这两个事实，不把问题替换成仅有其中一项的更宽泛描述
- **AND** 同义补查仍保持这两个事实，不加入未经确认的网络、版本或位置条件

#### Scenario: 低分尾部尚未核实
- **WHEN** 前列详情不足以回答，结果尾部仍有未读项且预算允许
- **THEN** Agent 继续按 rank 核实，不用未经标定的分数阈值丢弃尾部

#### Scenario: 核实预算已结束
- **WHEN** 候选尚未全部核实但任务预算不允许继续
- **THEN** 回答明确局限于已核实证据，不声称全库没有相符记录

#### Scenario: 相似机制没有现场验证
- **WHEN** 最新详情包含相似症状或可能机制，但没有该现场的必要佐证
- **THEN** Agent 将其表述为候选解释或排查方向，不认定现场根因及修复已覆盖现场版本

#### Scenario: 事后重跑找到候选
- **WHEN** 只有当前重跑结果而没有首次候选证据
- **THEN** Agent 只能说明重跑命中，不断言首次也返回过该项或首次漏报原因已经证实
