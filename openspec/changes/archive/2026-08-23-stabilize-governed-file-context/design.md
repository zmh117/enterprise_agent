## Context

文件链路已经具备任务工作区、File MCP、Job File Manifest、Docling 只读表示和跨会话保留附件召回，但四个边界没有闭合：持久化 UTC 时间在 Agent 可见协议层被改写为 `+08:00`；日期解析器把构造失败的日期替换为当天；跨会话查询把“没有保留事实”视为可召回且没有同时校验附件和 binding 到期；Docling Profile 只验证代码枚举，直到附件 Job 创建时才检查工作区和 File MCP。管理端又只自动开启附件开关，导致可保存但不可运行的 Publication。

本变更跨越 File Service、Job 创建、Business Application 控制面和管理前端。既有 Runtime protocol 1.2/1.3、Publication/Job/Manifest 不可变性和 File Service 唯一文件事实边界必须保持不变。

## Goals / Non-Goals

**Goals:**

- 让所有机器可读文件时间稳定输出 UTC RFC 3339，并保持 Manifest hash 对同一 canonical 值可复算。
- 让非法日期、过期保留事实和矛盾 Docling 配置在读取正文或创建不可运行 Job 前 fail closed。
- 分离“平台确定绑定”和“Agent 根据元数据发现”：时间窗口不再触发正文预载。
- 让前端联动与后端保存、校验、发布使用同一依赖矩阵。
- 用聚焦回归覆盖协议、仓储、控制面和 UI 行为。

**Non-Goals:**

- 不发布 Runtime protocol 1.4，也不修改 1.2/1.3 的字段集合或数据库 CHECK。
- 不增加 Job 终态，不重放、回填或改写历史 Job、Manifest、Publication 和保留事实。
- 不改变 TXT/Markdown/LOG 与 Docling 格式路由，不增加任意 URL、模型、插件或原始 Docling options。
- 不让 Runtime、Agent 或 Processing Worker 直接访问对象存储。

## Decisions

### 1. 在机器协议边界统一规范化为 UTC

提供单一 UTC RFC 3339 规范化函数，处理 aware datetime、`Z`、带 offset 字符串和按既有约定存储的 naive UTC。Job Manifest 返回、File MCP 元数据、Runtime 自动物化元数据及工具说明全部使用该函数。Manifest hash 继续基于持久化 canonical UTC 值计算，响应不再进行 hash 之后的上海时区投影。

备选方案是保留 `+08:00` 并修改 canonical spec；拒绝该方案，因为机器协议不应把展示时区混入不可变事实，且会扩大跨语言比较和 hash 漂移风险。管理端如需本地时间，应在展示层格式化。

### 2. 日期解析采用“未出现、合法、非法”三态

日期构造失败、结束日期早于开始日期或显式区间任一端非法时，解析结果标记为非法。文件语义存在时，入口直接生成不创建 Job 的安全澄清通知；没有文件语义时仍按普通文字消息处理。解析器不得用当前日期或其它猜测值替换非法输入。

备选方案是继续返回 `None`；拒绝该方案，因为 `None` 无法区分“没有日期”和“用户明确给了非法日期”，会让后续指代或普通 Job 路径继续执行。

### 3. 时间窗口只产生有界元数据依赖

当前消息附件、显式 File/Version ID、引用消息和消息中出现的完整文件名仍可形成原能力依赖。时间窗口命中项无论用户最终想读取正文还是查询元数据，都以 `METADATA + TIME_WINDOW` 进入既有 file context，最多 20 项；Runtime 不预物化正文。Agent 必须基于元数据选定精确 File/Version ID 后调用受治理物化工具。部分或近似文件名不形成正文依赖；本变更不新增模糊匹配算法。

该设计复用 1.3 已有 `required_capability`、`reason` 和 File MCP 流程，不新增协议字段。代价是唯一时间窗口命中也会多一次受治理工具调用，但避免平台在 Agent 判断前注入正文。

### 4. 保留候选查询要求所有访问时事实同时有效

跨会话候选必须同时满足：附件处于可用终态、附件未过期、binding 的保留截止时间未过期、文件/版本仍可用，并存在至少一条当前未过期的 `file_retention_fact`。缺少任一事实即不返回；Cleanup Worker 延迟不影响授权结果。比较使用调用方传入的同一 UTC `now`，避免多次取时产生边界漂移。

备选方案是返回过期元数据并标为 `content_available=false`；拒绝该方案，因为跨会话发现本身也是受保留期控制的能力，不能依赖后台删除时机决定可见性。

### 5. Docling Profile 使用独立的组合校验器

新增可复用的 Profile 兼容性校验，保存草稿和发布校验均调用。`docling-text-v1` 要求：`workspace_enabled=true`、`file_mcp_enabled=true`、附件与连续会话开启、File MCP 读取工具已冻结并被应用选择，以及所选 Python Agent Publication 支持当前文件上下文 Runtime 能力。沿用已发布的 1.3 能力声明做兼容判断，但不改变协议版本。

前端选择 Docling 时使用现有 feature/tool helper 自动开启工作区和 File MCP、补选可用必需工具，并开启附件和连续会话；如果 Agent Publication 缺少能力，页面展示阻塞提示，后端仍是最终安全边界。

## Risks / Trade-offs

- [既有测试和调用方断言 `+08:00`] → 同步更新所有机器协议断言，并增加禁止 `+08:00` 的聚焦测试；UI 本地化单独测试。
- [UTC helper 重命名遗漏调用点] → 全仓搜索旧 helper 和上海时区说明，静态检查后再运行文件工作区回归。
- [严格保留查询使缺失历史事实的文件不可召回] → 这是预期 fail-closed 行为；不自动补造历史事实，需另行授权的数据修复 change。
- [选择 Docling 时 Agent Publication 缺少 File MCP 工具] → 前端展示缺失项且后端字段级拒绝，不自动发布或替换 Agent Publication。
- [时间窗口多一次工具调用] → 候选上限固定为 20，换取正文最小披露和选择可审计性。

## Migration Plan

1. 先部署后端和前端代码及测试，不执行数据库 migration 或历史数据脚本。
2. 既有 Publication 和 Job 保持不可变；新草稿保存和新 Publication 开始执行更严格组合校验。
3. 既有 Runtime 1.2/1.3 consumer 继续读取相同字段结构，只看到规范化后的等价 UTC instant。
4. 回滚时可回退应用镜像；由于没有 schema 或历史数据写入，回滚不需要数据恢复。

## Open Questions

无。协议升级、Job 新终态和历史数据修复均明确留给独立 change。
