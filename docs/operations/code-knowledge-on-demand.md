# 按需代码知识库运维

实现变更：`replace-code-preextraction-with-on-demand-knowledge`。2026-11-09 已在本机 Mac 完成旧候选退役、数据库迁移 160、容器切换、真实 SVN 检出和代码索引发布。assist03 已启用新工具，业务 E2E 的 4 名成员已获授权，原 ONES 权限保留。已验证两个 Runtime 同目录 r2 并发读取、真实业务答案入 PG/Embedding/Qdrant，以及同版本命中只新增问答记录、不读源码或重复编码。Windows/Linux 宿主、真实 MES 跨版本变化与 ONES 并发重排负载仍待验收；详见变更的 implementation-evidence.md。

## 使用流程

在“工具资源 → 知识库”新建**代码知识库**，输入已由部署端登记的 SVN 地址，浏览并选择文件/文件夹检出，或者选择已登记的完整工作副本。保存源码配置后，显式初始化、验证并发布代码答案索引。PostgreSQL 使用平台内容库，Qdrant 使用当前受管服务中的独立代码集合；不接受 ONES 外部只读连接作为自动写入目标。Embedding 和重排复用现有服务，状态显示在同页“知识库服务”。

代码问题必须明确包含一个环境和 SVN 数字版本，例如“环境：prod，SVN r100，工单发布提示数据异常，为什么”。代码目录使用 `source_kind=code` 和精确 `environment` 编码，仅选择关联该环境、当前获准且已发布的知识库；同环境多个库时请用户选择。搜索、全文读取、源码操作和保存必须保持同一环境。知识搜索先查 r100；最近且有权限的更高版本仅作线索，必须检查 r100 源码才能形成 r100 答案。缺少环境或版本时澄清，不从 HEAD、当前目录、应用默认或历史回答猜测。纯 ONES 问题不要求提供 SVN 版本；同一 Job 的附件读写继续使用原文件沙箱权限。

完整答案注明适用条件和版本。每次有效问答由结果收尾写入私有 `code_qa_record`；仅完整核验的知识结论进入共享文档和增量索引，命中缓存不会重复分块或 Embedding。当前 Job 读取源码后可保存受支持答案，原 Job 负责回答，不再运行预提取 Agent。

默认回复使用业务语言，说明结论、触发条件、操作影响和必要的待确认项，保留环境、SVN 版本与适用业务端。源码、路径、行号、内部字段、工具回执和保存/索引过程不进入普通回复；状态业务名称和现场根因未核验时不猜测。历史答案即使含技术细节，也应重述后回答，保留完整条件和例外。用户明确要求技术分析时仍须满足当前授权。

业务答案正文与详细证据分开保存。模型只对实际采用且本次成功读取/保存的答案，在回复末尾逐条附 `<!-- code-answer:<document_id>@<revision_id> -->` 内部标记；结果收尾核验同任务、环境、来源与版本后写入私有问答的结构化引用，在会话、报告、Job 结果和投递前移除标记。标记本身不授权、不证明答案有效，无 ID 时不得编造；已有源码证据记录保留路径、行号和校验信息，不为追溯额外保存源码全文。

本回答约束使用 Prompt v16。更新 API、Agent Worker、Job Dispatcher、Channel Dispatcher、Webhook Worker、knowledge-mcp 与两个 Runtime，使 Prompt 版本及工具说明一致；`code-business-query` 内容冻结在 Agent Publication 中，需保存新草稿并发布 Agent，再由业务应用更新绑定并重新发布，以新 Job 验证。修改 Skill 文件不会覆盖既有发布或历史任务。此次调整不需要数据库迁移或重建知识索引。

同版本纠错先读取完整原答案，再用它的 `question_text` 重新 exact 检索，并以这次检索申请源码授权。保存时沿用原问题和身份条件，带实际读取的 `expected_current_revision_id`；新的用户纠错说明不能直接替代原问题身份。已准入的分析不能中途换题，冲突时不要移除 CAS 字段后另建文档冒充纠错。真正不同的业务条件应作为独立问题记录，并明确原答案是否仍适用。

## 容器与目录

代码问答可用 Write 在当前执行的 `work/notes/` 保存 Markdown/TXT 分析笔记（版本、证据引用、已查范围、未知项），其他目录及源码继续按原权限限制。笔记仅作临时推理，不是源码证据，不自动入库；Write 仍计轮次，Read/Glob/Grep 保留审计并免计任务轮次。SDK 停止后统一清理，异常残留使用已有恢复扫描。

源码 Grep 支持授权目录和 `glob` 文件模式，最多 64 文件/32 MiB；目录候选枚举最多 10000 项。`output_mode=content` 返回原路径行号，`-A/-B/-C` 各为 0–5、`head_limit` 为 1–200。Runtime 只从已核验的受管源码生成本次调用的 UTF-8 只读搜索输入，共享 Job 沙盒配额，调用结束即删除；Agent 不能访问内部缓存目录。敏感或非文本跳过会标记不完整，超限要求缩小范围。命中仍须 Read 原文件取得正式证据，Read 单次上限 400 行保持不变。这些缓存不是长期源码快照，不跨任务复用。

上述权限派生使用 `code-source-capability/v3`，与本次业务回复规则共同使用 Prompt v16。API、Worker、Runtime 与 knowledge-mcp 需协调构建更新；不要改写已冻结的历史 Job。已有 Skill 发布内容需按平台发布流程更新，单独修改磁盘 Skill 不覆盖旧发布。

- `code-svn` 是可选的本机 SVN 服务，真实部署也可以连接现有 SVN。
- `knowledge-sync` 含 SVN CLI，负责浏览、检出、update/log/diff/blame 和代码答案增量索引；新增结果端点仅容器内网络的 8096 端口，不发布宿主端口。
- 两个 Runtime 都只读挂载 `/var/lib/code-svn/checkout`，没有 SVN 凭据和源码写权限；源码只允许经过路径守卫的 Read/Glob/Grep，SVN 操作通过已有 MCP。混合文件任务的 Write/Edit 只能作用于原文件沙箱授权区域，不能写源码。
- `CODE_SVN_CHECKOUT_HOST_ROOT` 为 Docker daemon 实际看到的目录；`CODE_SVN_LOCAL_STATE_ROOT` 提供受管登记和 SVN 客户端认证配置。运维控制器通过实际挂载解析 Windows/WSL2 路径，不能把 PowerShell 的 `C:\...` 拼进 Linux 容器命令。
- 主 Compose 的 `code-storage-init` 一次性准备这两个根目录；仅源码与 SVN 状态目录允许自动创建，消费者等待实际权限探测成功。保留现有凭据文件，只传文件引用，不输出内容。
- 启动前需单独预检时，先运行 `docker compose run --build --rm --no-deps code-storage-init`，再运行 `deployment_check.py check --require-code`；普通 `up -d --build` 已包含目录初始化。
  执行器为 10003:10010，A/B 通过 supplementary group 10010 只读访问。SVN 子进程使用
  0027 创建掩码，身份标记为 0640，凭据入口的私有掩码不变。旧目录权限不符合时保留数据并
  按部署手册处理；权限错误为 `CODE_CHECKOUT_PERMISSION_DENIED`，不再误报身份变化。

三个宿主系统均运行 Linux 容器和同一套 SVN CLI；无需把 TortoiseSVN 安装到 Runtime。当前真实 CLI 验证是在 Mac Docker 的 Linux 容器中完成，不代表另外两种宿主已经通过。

首次检出通过 `mkdir` 独占创建最终目录，保留数据库 `preparing` 状态和写占用；SVN 下载、版本/范围/身份核验全部成功后，才在事务中标为 `ready` 并允许绑定、分析。目录在宿主盘上出现不代表任务已完成。此流程不依赖 `renameat2(RENAME_NOREPLACE)`，不使用“检查不存在后普通 rename”的覆盖风险回退，也不额外复制整份工程，适用于不支持该改名标志的 Windows Docker Desktop 9p 绑定盘。已有文件、空目录、符号链接及并发任务占用的同名目标均拒绝复用。

检出下载失败或取消时仅清理本次持有的目录；目录被替换、清理失败或进程异常退出时保留残留并保持不可分析，不自动覆盖或续接。旧版 `code_checkout_publish_failed` / `code_checkout_atomic_publish_unavailable` 记录不会因升级变成成功；如果旧 `.partial-*` 已清理，需要重新发起检出。失败记录仍保留目录名预留，新任务应填写新的子目录名，避免 `CODE_CHECKOUT_OVERLAP`；不要手工删除数据库记录来冒充成功。更新前等待现有 SVN 操作结束，然后执行 `docker compose up -d --build --no-deps knowledge-sync`；提示文案随 `admin-web` 更新。本修复不需要数据库迁移，不需要重建 Runtime 或重新发布 Agent。Windows 9p 的真实验收仍须在目标机器用新任务完成；本地真实 SVN 加禁用改名的故障注入不能代替现场证据。

代码问答已纳入唯一主入口 `docker-compose.yml`，不再使用额外的代码知识库 overlay。主文件同时给 API 和两个 Runtime 挂载专用凭据与固定环境配置。`CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE` 可指定已有专用凭据文件；留空使用 `${HOME}/.config/enterprise-agent/code-runtime-bootstrap-token`。新环境使用 `scripts/bootstrap_agent_runtime_secrets.sh` 幂等生成此文件，已有环境继续使用原文件，不轮换或复用 ONES 凭据。后续构建、更新只使用主文件：

```sh
docker compose -f docker-compose.yml up -d --build --no-deps api-server agent-worker job-dispatch-worker channel-dispatch-worker webhook-worker knowledge-mcp python-agent-runtime-a python-agent-runtime-b
```

Windows PowerShell 同样使用上述 `-f` 参数；凭据宿主路径根据该机器配置。不要把凭据值放进命令或日志，也不要复用 ONES 的凭据。

涉及 Prompt 或工具合同升级时，先在维护窗口暂停新请求并等待现有执行退出，再更新上述服务。`channel-dispatch-worker` 接收钉钉任务，`webhook-worker` 接收 Webhook 任务；两者创建 Job 时也会检查 Runtime Prompt 版本，不能漏更。仅更新 API 和 Runtime 会造成页面能激活应用、钉钉请求却报“所选 Agent Runtime 当前未就绪”。更新后分别从 API、Channel Dispatcher、Webhook Worker 核对被动 Runtime 检查结果为 READY、Prompt MATCH；容器 heartbeat healthy 不能代替这项检查。修复后发送新请求验证，不重放已拒绝消息。

缺少代码分析运行配置的 Job 应直接返回 `code_runtime_unavailable` 与明确中文提示，不自动重试；恢复部署后通过新的 Job 验证，不改写历史失败记录。

## 从 schema 159 切换

此步骤会删除清单内旧代码候选。普通 API/Worker 启动只校验 schema，不执行该清理。

1. 提前构建新镜像，完成本变更测试。保存安全盘点（`python -m app.cli.code_knowledge_inventory`），核对来源、KB、文档/修订、旧构建、checkout、发布引用和非代码文档计数。盘点只包含元数据。
2. 在维护窗口停用旧代码入口并排空旧任务，停止旧 API、调度 Worker、两个 Runtime 和 knowledge-sync，确认容器及 SVN 子进程已经退出。不要仅凭 Job 状态或租约过期判定停止。其他 ONES 数据保留，停止共享服务期间其检索/同步会暂停。
3. 在使用新代码、既有部署连接环境的临时维护进程再次运行盘点。以**本次实际输出**的摘要执行：

   ```sh
   python -m app.cli.retire_code_preextraction --inventory-digest <本次盘点摘要> --old-containers-stopped
   ```

   `--old-containers-stopped` 是运维人员已完成第 2 步的声明，工具不会自动停止 Docker。数据库端仍检查 schema、摘要、未确认停止的 invocation、运行中的旧 SVN 操作和混合来源引用。当前批准清单没有代码向量索引；若发现旧索引，工具拒绝并要求先核实精确集合清理计划，绝不按名称删集合。旧 checkout 操作摘要留在盘点中；源码目录和 Job/audit 表不删除。
4. 使用现有 Migrator 升级到 160。若失败，保持新旧写者停用，检查固定错误码；不要绕过清理门禁或使用 DROP CASCADE。此迁移无旧候选兼容读取路径。
5. 仅在 knowledge-sync 的既有配置、认证和 checkout 挂载环境下登记旧工作副本。例如：

   ```sh
   python -m app.cli.register_code_checkout --registration mes-local --directory mes-r2 --select set_server --select set_web/EBR --select set_web/JTH
   ```

   `--select` 必须与该工作副本完整内容一致；整仓使用省略 `--select`。命令执行只读 info/status 核实，拒绝混合版本、修改、冲突、符号链接、来源或路径不符；不 checkout/update/revert，不复制源码。
6. 应用新 API、knowledge-sync、两个 Runtime、knowledge-mcp 和前端版本。读库服务账号的最小列权限随 `database_policy.py` 更新；用既有凭据文件运行原有授权准备流程，勿打印密码。重新验证和发布 Agent/Application 的新工具集合，旧冻结 Job 不自动获取新能力。
7. 在页面建立/绑定代码 KB，初始化独立集合，验证并发布。验证一个指定版本的未命中问答、证据、PG 私有记录、共享答案与索引，再验证同版本命中不占用源码目录。确认 ONES 同步/检索仍正常。

退役先移除旧内容，再执行 DDL；这不是跨 PostgreSQL/Qdrant/文件系统的原子事务。任何失败都保持代码资源未发布，依据盘点恢复操作步骤，不恢复旧候选为有效答案。

## 并发与恢复

### 页面连接真实 SVN

在具体代码知识库的「SVN 工程检出」中只填写一次本机或远端 SVN 服务的仓库/分支地址（http://、https://、svn://）。选择「无需认证」并点击「浏览目录」时，按填写地址直接连接，不套用部署登记中的地址映射；建立资源所属的匿名连接，不创建凭据。匿名连接以空 secret_ref 表示，不加载其他已保存账号。localhost/127.0.0.1 指执行容器自身，连接宿主机 SVN 必须填写容器可访问的实际地址。

需要认证时选择「配置用户名密码」，点击「保存连接并浏览」。操作者需要知识管理和凭据创建权限。账号密码保存到既有加密凭据中心，浏览、检出和后续问答只引用连接 ID。保存后保持账号模式，清空密码输入并显示已保存；本次表单未修改地址、用户名或密码时，点击「浏览目录」复用该连接，不重复创建凭据。修改地址或账号后需重新填写密码，输入新密码会保存新连接。旧发布继续固定原连接，重新浏览、检出/绑定、验证和发布后启用新配置。页面不展示“已保存 SVN 连接”下拉框；刷新页面后不会回填或读取密码。

首次连接自动识别并固定仓库 UUID 和分支。支持 HTTP、HTTPS 和 SVN 协议，不需要预先登记 URL，不支持 file:// 或 SSH 隧道，不在 URL 中嵌入密码，不提供跳过证书验证选项。企业自签 CA 可以安装到系统信任链，或把公开 PEM 证书以 `.crt` 扩展名放入部署的 `client/trusted-ca/` 目录（容器内 `/run/code-svn-auth/trusted-ca/`，沿用只读挂载）。页面连接每次从该目录生成临时 CA 配置，目录可缺省；损坏或链接证书会返回证书错误。不要放入私钥或账号文件。本地 SVN 初始化自动把公开 CA 写入 `trusted-ca/local-svn.crt`，证书更新后重新初始化会同步该文件，不改变其他 CA。SVN 使用 `--password-from-stdin` 和 `--no-auth-cache`，密码不进入命令行、工作副本或 Agent。认证、证书和网络失败会分别提示；修复配置后再重试。

`code_svn_request_failed` 表示 SVN 进程以非零状态退出，且数字错误号没有命中已知分类；仅凭该码或运行时长不能断定是网络、权限、磁盘或工作副本错误。新的浏览/检出失败会在现有操作记录 `result_json.diagnostic` 中保存固定操作名、退出码及最多 8 个 `E` 加六位数字的 SVN 错误号，关闭弹框后仍能读取；页面展示这些详情和任务 ID。原命令、URL、参数、stdout/stderr 原文不落库、不写日志。已知分类同样保留数字错误链；无标准错误号时显示「未提供」，负退出码不直接认定为 OOM。旧失败记录无法追溯已丢弃的错误详情；更新 `knowledge-sync` 与 `admin-web` 后，使用新目录名发起新任务获取证据，不要求提供完整日志、账号密码或直接执行绕过平台的 SVN 命令。本诊断补充不需要数据库迁移，也不代表已经修复现场 SVN 失败的根因。

工作副本错误按 [Apache Subversion 的错误定义](https://subversion.apache.org/docs/api/latest/svn__error__codes_8h_source.html) 分类：`E155037` 对应 `CODE_SVN_WC_CLEANUP_REQUIRED`（上一次操作未完成），`E155004` 对应 `CODE_SVN_WC_LOCKED`（工作副本写锁），`E155032` 对应 `CODE_SVN_WC_DB_FAILED`（工作副本元数据数据库异常）。具体工作副本状态优先于通用连接包装错误，并保留同次返回的数字错误号。分类只用于诊断，不会自动执行 `svn cleanup`、删除锁或重试 update；维修仍需确认实际进程停止、取得独占并重新核验。独立探测中中断 update 后复现 `E155037`，只能证明该探测的状态，不能据此补写历史任务的根因，也不能直接认定为 9p 故障。

「源码与目录绑定」只选择已完成的检出目录，系统从唯一成功检出记录自动关联原始 SVN 连接，只读展示实际地址和认证方式，不再手选访问登记。同地址新增连接不会改变原目录的关联；保存接口不接受 `svn_access_ref`。连接归属、摘要或仓库身份不匹配，以及缺少成功检出来源的维护登记目录，不能新绑定；需在当前知识库配置连接并检出后选择新目录。既有发布仍固定原配置，未引用的历史连接也不会自动参与匹配。

关闭弹框不会删除已经保存的 SVN 连接或成功检出记录。重新进入时应打开检出时的同一知识库；页面连接归属于该知识库，同一个 SVN 地址不代表不同知识库可以共用其连接。目录下拉中连接无法用于当前知识库的项标为「当前知识库不可用」并禁选。若已有绑定的连接变更或丢失，页面保留该项并显示原因、阻止保存；先核对目录所属知识库和原始连接，不要仅因提示就重复检出。

「关联环境」复用工具资源中的环境，可以多选；同一代码知识库可服务多个环境。环境归属随源码配置修订保存并发布，知识目录返回环境编码和名称；关联不增加知识库授权或数据库访问权限。

### 从旧设备号登记升级

新检出将持久身份标记保存在 `.svn/enterprise-agent-identity` 中，正常重挂载不会改变该身份；Runtime 在每次分析期间仍检查本地设备号/inode，检测执行中的目录替换。不要删除、复制或修改身份标记来绕过保护。

先更新 API、knowledge-sync 和两个 Runtime，确认目录没有未释放读占用或未停止 SVN 操作，再在 knowledge-sync 的部署上下文中执行：

```sh
python -m app.cli.register_code_checkout --registration <已有部署登记键> --directory <既有检出子目录> --select set_server --select set_web/EBR --select set_web/JTH --repair-identity
```

命令持有目录行锁，完整核验 SVN 来源、范围、干净状态和原 revision，再升级旧身份并递增代次；不检出、不更新、不回滚源文件。新协议的标记不匹配仍拒绝，不能自动重建。`WORKSPACE_BUSY` 时先等待真实执行停止，不能改数据库强行释放。

迁移 161 新增连接元数据和环境关联表。升级已有 knowledge-mcp_reader 账号时，在受信管理连接执行以下固定列授权；新建账号使用更新后的 `services.knowledge_mcp_server.database_policy` 即可。不授予连接表或 Secret 读取权限：

```sql
GRANT SELECT (revision_id, environment_id) ON knowledge.code_resource_environment TO knowledge_mcp_reader;
GRANT SELECT (display_name, status) ON platform_environment TO knowledge_mcp_reader;
```

同一目录同版本可多个读者并行；修改独占，更新后原子转为当前 Job 的读占用。读者到期、Job 结束或网络失联不代表读取停止。只有 Runtime 实际停止工具/SDK，并记下对应 invocation 的停止证明后才释放。取消一个 Job 不释放其他 Job 的占用。

SVN 子进程继承 `.executor-locks` 中对应操作的 OS 文件锁。Worker 重启仅在锁已释放且 owner/claim 与数据库一致时确认旧执行结束；update 不自动重放。未知或损坏的停止证明需要维护核查，不能删除锁文件强行放行。该机制面向同一 Docker daemon 上的共享文件系统，不支持未经验证的多宿主网络盘。

索引任务在 PG 中与答案同事务提交，失败有界重试，达到上限后在代码 KB 内重试。暂停只暂停派生工作，不阻止问答记录。向量点包含任务代次，召回先限定当前 PG ready 代次；迟到请求不会覆盖新代次。移除只删除捕获上限及以下代次，不影响之后重新收录的点。响应丢失时检查前 8 个代次的不可变向量并复用，不重新运行问答模型。失效旧点即使尚待物理清理，也不能作为有效答案。

SVN diff/提交说明只在有界内存保留，单响应不超过 512 KiB，总缓冲 8 MiB，最长 60 秒且不超过任务截止。只读结果丢失可以在原授权/版本下重新取得并比较摘要；摘要变化则拒绝。不要把日志、原文或凭据写入排障报告。

代码分析会话设置 `--no-session-persistence` 和 `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`，防止 SDK 将源码读取及 SVN 原文另存为会话转录。审计只保留工具、版本、授权范围等安全元数据。不要为排障打开包含完整请求/响应的 SDK debug 日志。

管理页面的目录预览不含源码或提交正文，允许最多 2 MiB 的固定字段路径清单，仍受总内存 8 MiB、60 秒过期和管理员权限约束。只有管理 browse 分支启用该限额；问答 SVN 原文维持单响应 512 KiB。两端校验目录预览结构，不能以该标记传递 diff 或任意正文。

### 大仓库目录预览

目录预览首次只查询所填地址的直接文件和文件夹，展开文件夹时才加载该层。服务端使用 `svn list --xml --depth immediates`，每次携带首次浏览固定的数字 SVN 修订；后续新提交不会改变这棵浏览树或提交检出的版本。文件、目录均可勾选，选择父目录会覆盖尚未展开的子项。折叠不清空已加载内容和选择，单个子目录失败可局部重试；修改地址、认证配置、版本或重新浏览会重置旧浏览树。

`code_svn_response_too_large` 表示 SVN 输出超过容量上限，并不等同于认证失败。旧实现为显示目录递归列出整个分支，大工程可能超过 8 MiB XML 上限；按层查询避免了这一需求。单层预览仍有容量限制，不静默截断，也不自动放大缓冲。如果单层仍超限，可以将 SVN 地址缩小到所需子目录后重试。完整检出的清单、磁盘与执行时间检查仍独立生效；按层预览不代表任意规模工程都可一次检出。

本次修复无需数据库迁移、Runtime/Agent 重新发布或模型调用。在目标机器更新到本次代码后，先构建，等待现有 SVN 检出/更新操作结束，再更新这三个服务：

```sh
docker compose build api-server knowledge-sync admin-web
docker compose up -d --no-deps api-server knowledge-sync admin-web
```

刷新浏览器并重新点击「浏览目录」，验证根目录、两层子目录、文件选择和固定 SVN 修订。三个服务需一起更新，否则前端子目录请求可能找不到新接口，或仍从旧执行器拿到递归清单。以上命令适用于 Windows CMD/PowerShell 与 macOS/Linux Shell；本次已通过本机合成仓库的真实 SVN CLI 验证，真实 Windows 仓库尚待现场验收。验证范围见 [按层浏览修复记录](../../openspec/changes/fix-large-svn-directory-browse/evidence.md)。

### 检出执行失败分类

旧错误 `code_svn_unavailable` 同时包含命令超时、命令启动失败和本地读写异常，不能据此判断服务器离线、账号错误或证书问题。历史记录无法还原被丢弃的分类，不修改原失败结果；新实现用固定错误码区分原因，不保存原始命令、密码、路径或标准错误文本。

| 错误码 | 含义与排查方向 |
| --- | --- |
| `CODE_SVN_INFO_TIMEOUT` | 仓库或工作副本信息检查超时 |
| `CODE_SVN_LIST_TIMEOUT` | 文件清单读取超时，检查所选范围与仓库响应 |
| `CODE_SVN_PROPGET_TIMEOUT` | 外部引用检查超时；仅检查选中的目录及其后代 |
| `CODE_SVN_CHECKOUT_TIMEOUT` | 初始工作副本创建超时 |
| `CODE_SVN_UPDATE_TIMEOUT` | 稀疏检出的文件下载、目录展开或版本更新超时 |
| `CODE_SVN_STATUS_TIMEOUT` | 工作副本状态核验超时，检查挂载磁盘性能 |
| `CODE_SVN_EXECUTABLE_NOT_FOUND` / `CODE_SVN_EXECUTION_DENIED` | 容器缺少 SVN 可执行程序或没有执行权限 |
| `CODE_SVN_START_FAILED` / `CODE_SVN_LOCAL_IO_FAILED` | 容器无法启动进程或执行期间发生本地 I/O 异常 |

普通 SVN 信息与历史查询、按层目录浏览保持单命令 60 秒限制。递归文件清单、外部引用查询和工作副本整体 status/info 检查使用单命令最多 300 秒；工作副本创建与下载命令最多 1800 秒，仍受整个管理操作原有 1800 秒截止及取消检查约束，不能因新命令开始而重置总预算。问答来源操作继续使用其原有截止。所有字节、文件数与磁盘容量限制保持不变；超时后先终止并等待 SVN 进程退出，不自动重试写操作。旧错误码需要结合耗时判断，或更新代码后发起新操作取得具体分类。

此前约一分钟失败与旧批量命令 60 秒时限吻合，但历史错误无法证明具体是哪条命令。修复后的外部引用检查只递归查询选中的目录，所选文件和必要祖先不触发未选子树扫描；检出及后续固定版本更新保持一致。所选范围包含外部引用仍拒绝，所有写命令继续忽略自动外部检出。单个选中目录仍可能超过 300 秒或容量上限，此时需缩小选择范围并按具体错误排查。

`A` 全选与 `B/d`、`B/e` 单独选择可以同时使用，无需选中 `B`；系统会创建必要父目录。2026-11-11 已在隔离合成 SVN 仓库分别验证 d/e 为文件与目录，确认 A 全部存在、B 只包含 d/e，未选择的 f 不检出。这不证明 Windows 现场连接、性能或磁盘状态正常。

若前一节的按层浏览已部署，本次预检范围、预算与错误分类修复只需构建并更新 `knowledge-sync` 与 `admin-web`，无需迁移或 Runtime 发布；等待现有 SVN 写操作结束后更新。现场仍须以新操作结果验证是否恢复，不采集原始标准错误或凭据。本机验证及部署步骤见 [检出预检修复记录](../../openspec/changes/fix-svn-checkout-preflight-timeout/evidence.md)。


已有本地 SVN 升级 CA 信任时，无需重新生成证书或导入仓库：只把 `.local/code-svn/state/client/mes-local/server.crt` 复制到 `.local/code-svn/state/client/trusted-ca/local-svn.crt`，再更新 knowledge-sync 镜像。页面填写 `https://code-svn:8443/repos/mes/trunk` 并选择“无需认证”。地址不会自动替换，证书链、主机名和有效期仍由 SVN 校验。

## 环境隔离升级（迁移 162）

环境标识进入代码分析、共享答案身份和私有问答记录。同库、同来源、同 SVN 版本与同问题在两个环境分别保存，PG 先按环境筛选，全文读取及较高版本线索也必须匹配；向量候选再次通过 PG 核对，不需要每环境创建数据库、集合或代码检出。旧无环境记录保留为空但禁止复用，不能回填默认环境；新记录数据库约束拒绝空环境和改变环境身份。

先执行迁移 162，再协调更新 API、knowledge-mcp、knowledge-sync 和 Runtime。按更新后的 `database_policy.py` 重新授予读取列权限（新增 `knowledge.code_answer.environment_id`），重新发布 Agent/Application 的新工具合同及 `code-business-query` Skill，并发起新 Job。旧快照不兼容新工具，不通过编辑历史 Job 绕过。此次代码变更的本地验证记录见 [环境隔离验证记录](../../openspec/changes/isolate-code-knowledge-by-environment/evidence.md)；不代表目标环境已部署或完成真实模型/SVN 问答验收。
