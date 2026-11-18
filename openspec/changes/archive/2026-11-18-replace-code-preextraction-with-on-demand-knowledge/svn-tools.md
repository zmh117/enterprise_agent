# SVN 工具合同与检出目录分析流程

这是简化方案的设计附件，尚未实现或部署。当前问答 Agent 直接分析已检出的工作副本，不创建额外源码副本或独立提取 Agent。SVN 操作复用现有 `knowledge-mcp`、控制面和 `knowledge-sync`。

## 1. 服务与工具边界

Runtime → Knowledge MCP（当前 Job/发布/来源授权）→ 已认证控制面桥接（操作和占用记录）→ knowledge-sync（SVN CLI）。执行器可写受管工作副本；Runtime 同路径只读。所有工具只接收已登记 ID、仓库分支相对 POSIX 路径和结构化版本/时间条件，不接受任意 URL、宿主绝对路径、命令、参数串或凭据。

| 工具 | 固定输入/行为 | 返回 |
|---|---|---|
| `knowledge_svn_update` | `knowledge_base_id/source_id/checkout_id`、固定 `revision`、本 Job 的 `search_id`、缺证据理由、幂等键；需更新时独占写；已在该版本则共享读取并只读检查 | `operation_id` 和状态；完成返回服务端生成的 `analysis_id`、版本、范围及只读访问信息；占用忙返回 `WORKSPACE_BUSY` |
| `knowledge_svn_info` | 已授权仓库固定 revision 或已登记 checkout；可选相对 `path`；工作副本实际检查须取得相同版本的共享读占用，写入期间不可检查 | UUID、分支、解析版本；operative revision 范围、mixed/modified/switched、选中范围；last_changed_revision 单列 |
| `knowledge_svn_log` | 当前 `analysis_id`、`path`、latest/单 revision/revision_range/time_range 四选一、peg、limit/cursor、include_message | revision、时间、作者、允许说明、A/M/D/R 路径及复制信息、实际覆盖与分页 |
| `knowledge_svn_diff` | 当前分析、path、change_revision 或 from/to、peg、mode=summary/text、摘要 cursor | 两端版本及路径、文件/属性变化或单文件统一差异、摘要及不支持内容状态 |
| `knowledge_svn_blame` | 当前分析、单文件 path、固定 revision/peg、start_line/end_line | 原始行号、最后修改 revision、作者/时间；不代表业务因果 |
| `knowledge_get_source_operation` | operation_id、合法续页 cursor；当前授权及 Job 绑定 | 状态、阶段、安全错误码及原工具同等有界结果；不新建模型执行 |
| `knowledge_save_code_answer` | analysis_id、幂等键、分项结论/条件/证据引用/覆盖/未知项；版本与身份取自服务端分析记录 | 保存/索引状态、答案引用和固定 SVN 版本；完成校验保存后撤销读取并释放占用 |

历史工具只读 SVN；`update` 仅修改已登记本地工作副本，保存工具只产生经校验的知识记录。二者必须声明受限派生副作用，由正式发布与来源策略授权，不开放 commit/merge/switch/revert、任意 Shell 或 SQL。Runtime 不安装 SVN 写命令，不接触 SVN 凭据，也不 Docker exec。

分析 grant 绑定当前 Job/invocation、checkout/占用代次、仓库/分支、revision、允许路径及历史区间，只能在已冻结发布能力内收窄。首次 `knowledge_svn_update` 复核同 Job 的成功搜索、用户 requested_revision/问题关联与缺证据理由；较高版本线索的 matched_revision 不得改变更新目标；已经在目标版本则取得共享读取占用并核实，不调用 SVN update。缺失 checkout 应提示管理端先检出/登记，不自动建立源码副本或目录池。

`log -v` 中越授权范围的改动路径/复制来源须过滤并标识；提交说明无法安全投影时省略。源码、作者/说明和绝对宿主路径不进入普通业务回答或安全日志。结果、状态和缓存读取都重新授权；保存重放仅在当前合法 Job 内取回已提交结果，不重新更新目录。

## 2. 时间、修订号和文件语义


- **固定查询锚点**：在本 Job 的一次分析内，以已确认的 `analysis_revision` 及授权历史区间查询；日志选择器“最新”只在获准历史范围内一次固定上限，不因分页期间新增提交漂移；用户问答目标必须另有明确数字 SVN，不因日志查询改为 HEAD。只有元数据观察可以单独报告仓库 HEAD，不能把它替换为现场分析版本。使用仓库 URL 查询，不依赖本地 working copy 的隐式 BASE。
- **时间范围**：ISO-8601 时间必须含 offset；日期选择器必须附 IANA 时区。用户“2026-10-01 至 2026-11-09，Asia/Shanghai”转换为 `[2026-10-01T00:00:00+08:00, 2026-11-10T00:00:00+08:00)`，含结束日全天。内部保存 UTC 和原时区。SVN `{date}` 是定位 revision 的语法，不能直接当作精确时间过滤；最终按 `svn:date` 在冻结数字范围内过滤。时间戳缺失或异常明确未知；不能假设 revision 与时间永远单调。超出扫描预算时返回覆盖不足和续查位置。
- **日志版本区间**：`revision_range(51000,52089)` 查询包含两端的提交，固定降序返回。想看“从 r51000 升到 r52089 新增的提交”应查询 `51001..52089`。path 可同时限制目录或文件；“全部历史”表示从明确历史起点到固定上限的可分页结果，不能一次无限返回。
- **差异版本区间**：`change_revision=52089` 比较 `52088→52089`；`from_revision=51000,to_revision=52089` 比较两端内容，不表示逐条提交。中间修改又恢复原样时，端点 diff 可为空，但 log 仍有提交；不能据空 diff 宣称期间没有变化。拒绝隐式与本地未提交内容比较。
- **文件身份**：记录 peg 与 operative revision，处理 A/M/D/R 和复制/重命名；只有两端和历史路径都获授权才追踪。删除文件用其存在的 peg 或父目录差异定位，同路径删除重建不得混为同一文件；找不到返回明确状态，不能偷偷改查 HEAD。
- **行归属**：blame 只说明目标版本该行最后修改的归属，不能单独认定缺陷引入者或行为变化点；后续应看对应 diff 与调用链。服务端取固定版本的原始行号，不能使用截断或改写后的模型文本行号。
- **历史来源**：目录 import 产生的是新仓库历史，不包含原公司提交。记录 repository_uuid/branch/history_floor/observed_at；原 revision 不存在时明确 unavailable，不用本地 r2 对应原 r52089。

分页 cursor 绑定工具、仓库、分支、固定上下限/peg、路径、时区筛选、来源配置及授权范围，后续调用仍复核当前授权。提交时间/作者/说明属于可修改的 revision 属性，结果保留观察时间和摘要；已经取得的证据不假装是未来不变的元数据。

### 初始有界策略

- log 默认 100 条/页、最多 200 条，单次最多扫描 10000 个 revision；达到上限标记 partial/has_more/paths_truncated，不假装完整。
- diff 摘要每页最多 1000 路径；文本限定单文件、两端固定版本，最多 256 KiB，超限明确拒绝。blame 每次最多 400 行，底层计算仍受预算限制。
- MCP 结果最多 512 KiB，保存输入同样有界。只读 SVN 操作最多 60 秒且受 Job 剩余预算约束，单次短等最多 10 秒后返回 PENDING；后续查询不延长原截止。
- update 使用显式部署的时间/磁盘/文件预算，并取 Job 剩余预算较小值；目录忙立即返回，不排队等待另一模型。占用最长时间不超过 Job 剩余预算，心跳不能无限续期。
- Job 结束/取消/撤权后停止其 SVN 操作和源码读取；未完成分析不转成后台模型任务。正常已提交的索引派生可独立完成。
- knowledge-sync 沿用有界并发/租约执行 SVN，长 update 不占住 ONES 同步；不新增通用消息系统或任务平台。

## 3. 用户命令示例到工具的映射


以下只描述等价业务意图，不在本机执行提供的 Windows 命令。`source_id=mes-code` 为示意编码，实现使用平台实际来源 ID；`knowledge_base_id`、当前分析 ID 和 Job 身份省略。历史工具在成功更新/检查取得分析占用后调用。

| 用户的人工操作 | 结构化工具请求示例 |
|---|---|
| `log -v -l 100` | `knowledge_svn_log(path="", selector={kind:"latest"}, limit=100, include_message=true)`，latest 在准入时固定 |
| 10 月 1 日至 11 月 9 日 | `knowledge_svn_log(path="", selector={kind:"time_range",start_time:"2026-10-01T00:00:00+08:00",end_time:"2026-11-10T00:00:00+08:00",timezone:"Asia/Shanghai"})` |
| `log -v -r 51000:52089` | `knowledge_svn_log(path="", selector={kind:"revision_range",from_revision:51000,to_revision:52089})` |
| `info` 查看工作副本 | `knowledge_svn_info(target={kind:"checkout",checkout_id:"已登记工作副本 ID"})`；混合版本返回 min/max，不能只报根目录 revision |
| `log -q -l 100` | latest + `include_message=false`，仍返回版本/作者/时间，固定授权范围内的文件信息可按 UI 折叠 |
| `log -v -r 52089` | `knowledge_svn_log(path="", selector={kind:"revision",revision:52089})` |
| `diff -c 52089 --summarize` | `knowledge_svn_diff(path="", selector={kind:"change",change_revision:52089},mode="summary")` |
| `diff -r 51000:52089 --summarize` | `knowledge_svn_diff(path="", selector={kind:"range",from_revision:51000,to_revision:52089},mode="summary")` |
| 某个文件的全部 log | `knowledge_svn_log(path="set_server/pubclass/Control/EquipUnit.cpp",selector={kind:"revision_range",from_revision:1,to_revision:52089},peg_revision=52089)`；历史下限须被实际来源支持并授权，结果分页 |
| 某文件在 r52089 的改动 | `knowledge_svn_diff(path="set_server/pubclass/Control/EquipUnit.cpp",selector={kind:"change",change_revision:52089},mode="text",peg_revision=52089)` |
| 某文件第 120–160 行归属 | `knowledge_svn_blame(path="set_server/pubclass/Control/EquipUnit.cpp",revision=52089,peg_revision=52089,start_line=120,end_line=160)` |
| `update -r 52089` 后分析代码 | `knowledge_svn_update(checkout_id="已登记工作副本 ID",revision=52089,search_id="本 Job 成功检索 ID",reason="关键证据不足",request_key="固定幂等键")`；需要更新时服务端独占写并转成读占用；已在该版本可直接加入共享读取 |

后台使用固定 `/usr/bin/svn` 和参数数组，不拼接 Shell 字符串。info/log/blame 和 diff 摘要解析有界 XML，文本 diff 单独处理；log 需要作者/时间/说明时不得使用 `--with-no-revprops`。`svn update -r N` 只能在平台已取得目录独占且全部读取者已结束后执行，固定现有选中范围，不接受任意深度/externals/目标路径参数。

## 4. 目录占用与完整流程

| 阶段 | 可读取源码 | 可更新目录 | 占用规则 |
|---|---|---|---|
| 空闲且有效 | 可原子取得当前版本读占用 | 无读写者时可取得独占写权限 | 在同一目录记录上判定 |
| UPDATING | 禁止新读者，且进入前必须已无旧读者 | 仅当前代次的 knowledge-sync 操作 | 一个写者，更新完成前不发 grant |
| ANALYZING | 同一版本可有多个 Job，各自独立读占用 | 全部禁止，包括已持有读取的 Agent 再次 update | 最后一个读者结束后才可修改 |
| 单个 Job FINALIZING | 该 Job 停止新读取并等待自己的在途调用；其他读者继续 | 仍禁止 | 校验/保存完成只释放自己的占用 |
| 失效/待恢复 | 不再准入新读取；异常时终止受影响分析 | 仅确认所有旧执行停止后可受控恢复 | 到期不等于旧进程已停止 |

1. 管理员在代码知识库的源码配置里保留完整检出和文件/文件夹多选，选择匹配的已完成检出绑定为受管工作副本，绑定 source/UUID/branch/范围。一个真实工作副本只能有一个登记身份，拒绝路径别名或重叠登记，避免同目录绕过协调。
2. 当前 Agent 按用户指定数字版本先相等检索，缺证据时可取最近更高版本线索，但 update 和代码核验仍针对用户版本。若目录已核实为 N、无写者且未失效，服务在同一事务中加入 N 的共享读者；实际只检查，不运行 update。其他 N 版本读者可并发，不同目标版本返回 WORKSPACE_BUSY。
3. 必须更新时，服务仅在无任何读写者时取得独占，绑定 Job/invocation/代次/截止，knowledge-sync 检查无本地修改/冲突/switched、身份/范围相符后执行 update。dirty 拒绝，不 revert；中断/混合版本标失效，不交给 Agent。
4. 核实全部选中项 operative revision、UUID/branch 和范围；last_changed_revision 较旧正常。写者完成后原子转为本 Job 的共享读取占用，再发 grant，其他同版本读者随后可加入。`.svn`、未跟踪项、越界链接和未授权 externals 不得交给模型。
5. 每个 Agent 在自己的原 Job 中通过 Read/Glob/Grep 追踪问题；log/diff/blame 通过 MCP 查询固定历史，不修改工作副本。读任务独立记录版本、文件/行号/hash 和历史操作引用，互不混用证据、输出或权限。
6. 结果保存工具停止本 Job 新读取，等自己的在途调用结束，在其读占用内核对证据与版本。支持的结论保存答案，partial/conflicted 仅存分析记录；完成后只释放自己的读占用，其他分析继续。格式错误允许在预算内修正；Qdrant 派生不占目录。
7. 一个 Job 同时只持有一个工作副本的读占用。需要切换 revision，先保存/结束当前分析并释放自己的占用，再申请更新；若仍有其他读者则忙，不能在持读状态等待升级、抢占或偷偷改目录。取消某读者不能释放其他读者。
8. Job 返回带 SVN 版本的回答。全部读者结束后，任何合法 writer 才可更新；更新不删除旧版本缓存，历史证据按 SVN 原版本取回，不依赖永久副本。
9. 失败/结束/取消时先停止该 Job 文件读取与 SVN 子进程，确认退出后回收其占用。租约到期或 Runtime 无心跳不直接删除锁并放行更新；旧 owner 尚可能运行时保持写阻塞。正常其他读者不因一个 Job 结束被取消。

读者数量判定、加入读者、取得写权限和写转读都由 PostgreSQL 同一目录记录的事务协调，不能依赖两个 Runtime 各自的进程锁或 SVN 自身锁。没有后台模型等待链：目录忙立即返回，不无限排队；同一请求重放只返回原操作/读占用，不增加读者计数或重新 update。

受管目录禁止宿主或其他容器绕过平台写入。容器只读不能限制这些外部写者；检测文件/版本异常即终止受影响分析并拒绝缓存确定答案。证据按实际读取文件检查，不生成整仓 manifest 或复制文本树。

## 5. Windows、macOS、Linux 部署合同

| 宿主 | 执行环境 | 路径示例 |
|---|---|---|
| Windows 10/11 | Docker Desktop/WSL2，Linux containers | `D:/Enterprise Agent/.local/code-svn/checkout`；从 WSL 启动使用实际 WSL 路径 |
| macOS | Docker Desktop，Linux containers | `/Users/mhz/Develop/enterprise_agent/.local/code-svn/checkout` |
| Linux | Docker Engine + Compose | `/srv/enterprise_agent/.local/code-svn/checkout` |

示例不硬编码。三平台统一运行容器内 SVN，不依赖 TortoiseSVN、PowerShell 或宿主原生 SVN。

| 数据 | knowledge-sync | Runtime A/B | code-svn |
|---|---|---|---|
| `CODE_SVN_CHECKOUT_HOST_ROOT` 指向的同一检出根 | `/var/lib/code-svn/checkout` 可写 | `/var/lib/code-svn/checkout` 只读，按 Job grant 限定子目录 | 不挂载 |
| 可选本地 SVN 仓库服务状态 | 仅必要连接配置/凭据，不挂仓库本体 | 不挂载 | `/state` 提供服务，初始化沿用既有 admin 入口 |

不再为新流程配置 `CODE_SOURCE_SNAPSHOT_HOST_ROOT` 或额外源码根。平台保留工作副本自身 `.svn`，不为模型复制另一套源码；Job 工具守卫阻止模型读取 SVN 元数据。

Compose 使用长格式 bind mount；缺失目录不隐式误建，Windows 盘符只在部署层处理。嵌套控制器使用真实 daemon Mounts.Source，网络/服务从部署配置获取，不硬编码 `/host_mnt`、`/run/desktop` 或项目网络。更新后文件变化应在 A/B 的同一挂载中可见，无需重建镜像。

预检验证中文/空格路径、UID/ACL、只读拒写、同一目录身份、大小写/Unicode 文件名及平台锁跨节点生效；不兼容文件系统明确拒绝。现有 checkout 临时发布机制仍按实际平台验收，但不新增快照封存阶段。凭据隔离沿用当前固定消费者和私有 tmpfs 合同。linux/amd64 与 linux/arm64、三种宿主分别记录证据，单台 Mac 成功不能代表全部通过。

## 6. 验收与参考依据

必须覆盖：同 Job 首次查代码/缓存/再命中、分析中实际修改目录的 update 被拒、同目录同版本两个 Runtime 并发读取、修改之间互斥且读写互斥、超时但旧读取未停、取消与半更新恢复、Job 收尾释放、不同版本缓存并存、旧目录更新后历史证据复核；另验证下列历史语义及三平台真实挂载。测试仓库的规则变化不冒充 MES 实际历史。

- [SVN update：更新到指定 revision](https://svnbook.red-bean.com/en/1.7/svn.ref.svn.c.update.html)
- [SVN log：范围、文件与输出](https://svnbook.red-bean.com/en/1.7/svn.ref.svn.c.log.html)
- [SVN revision/date](https://svnbook.red-bean.com/en/1.7/svn.tour.revs.specifiers.html)
- [SVN diff：单提交与两端差异](https://svnbook.red-bean.com/en/1.7/svn.ref.svn.c.diff.html)
- [SVN blame：行归属](https://svnbook.red-bean.com/en/1.7/svn.ref.svn.c.blame.html)
- [SVN peg/operative revisions](https://svnbook.red-bean.com/en/1.8/svn.advanced.pegrevs.html)
- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

以上是已有命令/挂载语义参考，实际实现仍需用镜像内 CLI 做合同测试。工具字段与预算是本项目设计。

## 7. GitHub SVN MCP 候选评估（2026-11-09）

此前方案阶段已只读核对公开仓库 metadata、README、package、工具注册及测试配置，以下保留当时的选型记录，未安装、执行项目或做供应链/生产验收。星数仅反映核对时的规模，不作为质量结论。

| 候选 | 本次看到的事实 | 接入判断 |
|---|---|---|
| [shrishailrana-maker/svn-agent-mcp-v1](https://github.com/shrishailrana-maker/svn-agent-mcp-v1) | TypeScript、Apache-2.0；源码 package 1.9.1；4 stars；log/diff/blame、只读开关与有界结果；CI 配置 Windows/Ubuntu/macOS | 首选试验候选。stdio 不能直接替换平台固定 HTTP MCP；需验证只读工具映射、完整性、日期/peg/行区间和持久恢复 |
| [gcorroto/mcp-svn](https://github.com/gcorroto/mcp-svn) | TypeScript、MIT、package 0.1.4、24 stars；已有 info/log/diff/checkout/update 及测试；README 仍把 blame 标为开发中 | 可参考或复用部分实现，当前功能不足以完整覆盖本需求；不因星数略多认定更成熟 |
| [manavdesai27/mcp-server-svn](https://github.com/manavdesai27/mcp-server-svn) | Python/FastMCP、0 stars；README 提供基础 log/diff/update 等，未列 blame；本次仓库 metadata 未识别 license | 不作为首选依赖；需先核实许可及缺失合同，Python 技术栈相同并不代表适配工作少 |

首选候选本次树 SHA 为 `6a1fca44be07542b081e3cae25ffee13d9fc7884`，对照源 package 为 1.9.1；GitHub releases 接口最近一条为 v1.8.3，不能把 main/package/npm/GitHub Release 当成同一个已验证发布。实现时选择可追溯制品并锁定版本、commit、校验和及许可证，不使用运行时 `npx ...@latest` 下载。其 package 要求 Node >=24.18.0/npm >=11.16.0；需评估对现有 Python Worker 镜像的依赖成本。

已直接核对的关键差距：

- [src/index.ts](https://github.com/shrishailrana-maker/svn-agent-mcp-v1/blob/6a1fca44be07542b081e3cae25ffee13d9fc7884/src/index.ts) 使用 stdio；平台仍以 `knowledge-mcp` Streamable HTTP 对 Runtime 提供工具，内部协议转换由 Worker 承担。
- [src/guards.ts](https://github.com/shrishailrana-maker/svn-agent-mcp-v1/blob/6a1fca44be07542b081e3cae25ffee13d9fc7884/src/guards.ts) 有 `SVN_AGENT_READONLY=1`/`--readonly`；但 `review` profile 仍包含写流程工具，不能把 profile 名称当作只读授权。只读历史后端仍限定为已准入子集；平台 update 走自己的受管入口，不能通过上游通用写工具绕过目录占用。
- 上游 `svn_snapshot` 是工作副本状态/版本摘要；本简化方案不引入额外源码快照，不需要该工具来生成副本。
- README 指出 diff/blame 默认忽略 EOL 变化，游标证据主要留在进程内；精确证据模式要显式控制 EOL 语义，持久任务的重启/摘要验证由平台负责，不能直接把进程内 operationId 当平台持久操作 ID。
- [CI 配置](https://github.com/shrishailrana-maker/svn-agent-mcp-v1/blob/6a1fca44be07542b081e3cae25ffee13d9fc7884/.github/workflows/ci.yml) 有三平台矩阵和临时 SVN 测试入口；本次没有执行这些测试，也没有证明本项目三平台部署通过。

实施阶段先做最小合同试验：info 的 mixed/modified；固定版本 log 的作者/日期/路径；单提交与两端 diff；中文文件和历史删除/重命名；指定行 blame；非法路径/越版本拒绝；只读模式拒绝变更；超限和取消。能减少实际代码和维护成本且满足合同才采用，否则沿用现有受控 CLI，保留候选评估记录即可。

页面配置、每次问答记录、较高版本线索与增量索引流程统一见 [knowledge-ui.md](knowledge-ui.md)。

## 8. 原文结果返回

按用户已确认的 [瞬时传输合同](svn-result-transport.md)，knowledge-sync 增加仅内部可用的结果端点；PG 操作状态与响应摘要保持持久，diff 原文和提交说明仅经有界内存返回。Runtime 不获得内部服务凭据，不直连执行器。

### 实施选型结论（2026-11-09）

再次通过 GitHub 官方连接核对上述固定 commit 的 package.json、LICENSE 与 stdio 入口，以及第二候选 package 0.1.4/MIT。继续采用现有 Python 受控 SVN CLI，不安装上游 MCP/Node，也不复制其实现。现有镜像内临时合成仓库已通过 8 项真实 CLI 合同测试：固定版本/分页、改后还原、中文空格路径、blame、dirty/mixed、sparse 更新、复制授权、删除重建、日期/缺失 revprops、EOL/keywords。增加 Node 和 stdio 桥接不能替代本项目持久协调/授权/原文通道，当前没有减少维护量的证据。未运行上游测试，不声称上游三平台质量或本系统三平台验收通过。
