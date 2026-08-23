## Context

当前 checkout 已实现单一文本规则、单一 Docling Profile、Manifest v5 和 Runtime protocol 1.3，但部分实现仍沿用多版本时期的容器、Registry、兼容错误和健康字段。最新文件域 reset 又新增了 Agent/Application Publication 完整性识别与级联删除，使一个一次性文件清理命令跨越 File Workspace、Agent Config 和 Business Application 三个领域，并重复实现已有发布快照 hash/协议判断。

本变更只做删除和收窄，不改变 File Service 对象存储边界、Manifest v5、Working Set、Docling 表示、Runtime 1.3、RBAC、Delivery 或 migration 119 的单一合同约束。

## Goals / Non-Goals

**Goals:**

- 列出并删除当前没有业务价值的恒真字段、不可达分支、测试残留和错误码。
- 让固定文本规则和唯一 Docling Profile 以直接常量/函数表达，不保留虚假多实现结构。
- 让开放测试文件域 reset 只负责文件对象、文件域事实和强关联终态运行事实。
- 保留 migration 119 对遗留 Runtime/Profile/Manifest 引用的失败关闭，不在 reset 中复制配置完整性判断。
- 让测试验证公开行为和安全不变量，而非精确提示文案、私有方法或 SQL 拼接。

**Non-Goals:**

- 不新增配置清理命令、兼容迁移、回填、旧合同解释或运行时开关。
- 不改变支持的文件格式、Docling options/hash、Manifest payload、File MCP schema 或授权范围。
- 不删除 `DocumentProcessingProfile`、`TextFormatDefinition`、`DoclingServeProvider`、对象存储 Protocol 或 reset 的 service/CLI 边界。
- 不处理遗留 Agent/Application 配置；如部署仍存在这些事实，migration 119 继续失败关闭。

## Decisions

### 1. 文件域 reset 不识别或删除配置域事实

删除 reset 中当前 Runtime/Profile 常量、Publication snapshot/hash 解析、遗留配置 inventory、跨域 delete/update helper 和对应结果字段。`report/apply` 只计算文件域表、强关联终态运行事实、非终态 blocker 和两个受管对象命名空间。

选择该方案是因为 migration 119 已是配置合同收缩的唯一失败关闭边界；在 reset 中再次判定 Publication 是否“当前”既重复能力，也会把破坏范围扩展到 Route、Deployment、Tool/Skill/Channel/Webhook 绑定。备选方案是保留只读配置计数，但仍需维护重复的快照解释逻辑，因此不采用。

### 2. 固定规则使用直接定义，不保留单元素容器

文本规则保留三个 `TextFormatDefinition` 和一个固定 tuple，由按 code、按名称函数直接遍历解析；删除 `TextFormatPolicy`、`CURRENT_TEXT_FORMAT_POLICY` 和 `get_text_format_policy()`。Docling 保留完整不可变 `DOCLING_LAYOUT_OCR_V2` 与 hash，解析函数只分支处理 `NONE` 和该常量；删除 `PROFILE_REGISTRY` 及单元素遍历。

选择直接函数是因为当前合同明确禁止运行时切换和旧版本兼容。映射或 Registry 会暗示尚不存在的扩展能力。

### 3. Schema head 例外只表达一个明确前序版本

将 `allowed_previous_heads: frozenset[str]` 收窄为单个显式 `previous_head`，仅允许当前 catalog head 或调用方声明的一个已知前序 head。普通服务的 `require_current()` 继续严格；reset CLI 固定声明 `118`。

该设计满足 migration 119 前运行 reset 的当前需要，不为未来未知维护工具预留多 head 策略。

### 4. 删除只改善误调用提示的授权分支

`file_get_metadata` 对非初始 Manifest 条目继续使用既有拒绝；删除为了区分冻结目录候选而增加的第二次目录查询、专用 method 和错误码。目录候选的正确路径仍由工具描述指向 `file_prepare_materialization`，物化授权本身不变。

### 5. Readiness 只返回可计算状态

删除 `core.runtime_assembly` 及其测试断言，不用新的常量或兼容 alias 替代。`runtime_selection` 和 `agent_runtimes` 继续报告当前 runtime kind、protocol 和真实探针状态。

### 6. 测试围绕公开行为收敛

- 删除通过错误 Python 函数签名证明“无版本参数”的测试，保留管理 API 对旧字段的合同拒绝测试。
- 工具提示测试只检查“目录候选直接物化”和“原始二进制不进 Sandbox”两个稳定安全不变量；实际授权/物化由服务行为测试覆盖。
- reset 测试只通过 `report/apply` 断言 blocker、确认、inventory drift、对象与数据库最终状态；删除调用 `_clear_database_rows()` 并匹配 SQL 文本的 fake PostgreSQL 测试。

## Risks / Trade-offs

- [删除跨域配置清理后 migration 119 可能继续被遗留配置阻断] → 这是预期失败关闭；本变更不猜测或自动删除配置域事实。
- [删除专用 metadata 错误后 Agent 获得的提示更通用] → 工具描述仍给出正确调用顺序，授权和物化行为不变。
- [删除精确提示文案断言可能漏掉说明性文字变化] → 保留少量稳定安全不变量，并以实际工具行为测试作为主要门禁。
- [移除 readiness 字段影响未知外部消费者] → 仓库内搜索确认没有当前消费者；作为未规范化恒真字段按 breaking removal 处理。

## Migration Plan

1. 先删除 reset 的跨域 inventory/delete 逻辑及对应测试数据构造，确认文件域 reset 公开行为保持通过。
2. 收窄 Schema head validator，再依次简化文本规则、Docling Profile 和 catalog metadata 拒绝分支。
3. 删除 readiness/错误码/fixture 残留并收缩测试。
4. 运行聚焦后端测试、前端测试、静态旧标识搜索、OpenSpec strict、Compose config 和 diff 检查。

本变更不需要数据库迁移。回滚仅恢复代码和测试；不得借回滚恢复跨域自动删除行为后直接执行生产数据清理。

## Open Questions

无。
