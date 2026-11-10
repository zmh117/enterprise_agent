# 按需代码知识库运维

实现变更：`replace-code-preextraction-with-on-demand-knowledge`。2026-11-09 已在本机 Mac 完成旧候选退役、数据库迁移 160、容器切换、真实 SVN 检出和代码索引发布。assist03 已启用新工具，业务 E2E 的 4 名成员已获授权，原 ONES 权限保留。已验证两个 Runtime 同目录 r2 并发读取、真实业务答案入 PG/Embedding/Qdrant，以及同版本命中只新增问答记录、不读源码或重复编码。Windows/Linux 宿主、真实 MES 跨版本变化与 ONES 并发重排负载仍待验收；详见变更的 implementation-evidence.md。

## 使用流程

在“工具资源 → 知识库”新建**代码知识库**，输入已由部署端登记的 SVN 地址，浏览并选择文件/文件夹检出，或者选择已登记的完整工作副本。保存源码配置后，显式初始化、验证并发布代码答案索引。PostgreSQL 使用平台内容库，Qdrant 使用当前受管服务中的独立代码集合；不接受 ONES 外部只读连接作为自动写入目标。Embedding 和重排复用现有服务，状态显示在同页“知识库服务”。

代码问题必须明确包含 SVN 数字版本，例如“SVN r100，工单发布提示数据异常，为什么”。知识搜索先查 r100；最近且有权限的更高版本仅作线索，必须检查 r100 源码才能形成 r100 答案。没有版本时澄清，不从 HEAD、当前目录或历史回答猜测。纯 ONES 问题不要求提供 SVN 版本；同一 Job 的附件读写继续使用原文件沙箱权限。

完整答案注明适用条件和版本。每次有效问答由结果收尾写入私有 `code_qa_record`；仅完整核验的知识结论进入共享文档和增量索引，命中缓存不会重复分块或 Embedding。当前 Job 读取源码后可保存受支持答案，原 Job 负责回答，不再运行预提取 Agent。

同版本纠错先读取完整原答案，再用它的 `question_text` 重新 exact 检索，并以这次检索申请源码授权。保存时沿用原问题和身份条件，带实际读取的 `expected_current_revision_id`；新的用户纠错说明不能直接替代原问题身份。已准入的分析不能中途换题，冲突时不要移除 CAS 字段后另建文档冒充纠错。真正不同的业务条件应作为独立问题记录，并明确原答案是否仍适用。

## 容器与目录

- `code-svn` 是可选的本机 SVN 服务，真实部署也可以连接现有 SVN。
- `knowledge-sync` 含 SVN CLI，负责浏览、检出、update/log/diff/blame 和代码答案增量索引；新增结果端点仅容器内网络的 8096 端口，不发布宿主端口。
- 两个 Runtime 都只读挂载 `/var/lib/code-svn/checkout`，没有 SVN 凭据和源码写权限；源码只允许经过路径守卫的 Read/Glob/Grep，SVN 操作通过已有 MCP。混合文件任务的 Write/Edit 只能作用于原文件沙箱授权区域，不能写源码。
- `CODE_SVN_CHECKOUT_HOST_ROOT` 为 Docker daemon 实际看到的目录；`CODE_SVN_LOCAL_STATE_ROOT` 提供受管登记和 SVN 客户端认证配置。运维控制器通过实际挂载解析 Windows/WSL2 路径，不能把 PowerShell 的 `C:\...` 拼进 Linux 容器命令。
- 部署前创建这两个根目录；Compose 的 `create_host_path: false` 拒绝拼错路径后自动创建空目录。保留各自现有凭据文件，只传文件引用，不输出内容。

三个宿主系统均运行 Linux 容器和同一套 SVN CLI；无需把 TortoiseSVN 安装到 Runtime。当前真实 CLI 验证是在 Mac Docker 的 Linux 容器中完成，不代表另外两种宿主已经通过。

代码问答已纳入唯一主入口 `docker-compose.yml`，不再使用额外的代码知识库 overlay。主文件同时给 API 和两个 Runtime 挂载专用凭据与固定环境配置。`CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE` 可指定已有专用凭据文件；留空使用 `${HOME}/.config/enterprise-agent/code-runtime-bootstrap-token`。新环境使用 `scripts/bootstrap_agent_runtime_secrets.sh` 幂等生成此文件，已有环境继续使用原文件，不轮换或复用 ONES 凭据。后续构建、更新只使用主文件：

```sh
docker compose -f docker-compose.yml up -d --build --no-deps api-server python-agent-runtime-a python-agent-runtime-b
```

Windows PowerShell 同样使用上述 `-f` 参数；凭据宿主路径根据该机器配置。不要把凭据值放进命令或日志，也不要复用 ONES 的凭据。

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

同一目录同版本可多个读者并行；修改独占，更新后原子转为当前 Job 的读占用。读者到期、Job 结束或网络失联不代表读取停止。只有 Runtime 实际停止工具/SDK，并记下对应 invocation 的停止证明后才释放。取消一个 Job 不释放其他 Job 的占用。

SVN 子进程继承 `.executor-locks` 中对应操作的 OS 文件锁。Worker 重启仅在锁已释放且 owner/claim 与数据库一致时确认旧执行结束；update 不自动重放。未知或损坏的停止证明需要维护核查，不能删除锁文件强行放行。该机制面向同一 Docker daemon 上的共享文件系统，不支持未经验证的多宿主网络盘。

索引任务在 PG 中与答案同事务提交，失败有界重试，达到上限后在代码 KB 内重试。暂停只暂停派生工作，不阻止问答记录。向量点包含任务代次，召回先限定当前 PG ready 代次；迟到请求不会覆盖新代次。移除只删除捕获上限及以下代次，不影响之后重新收录的点。响应丢失时检查前 8 个代次的不可变向量并复用，不重新运行问答模型。失效旧点即使尚待物理清理，也不能作为有效答案。

SVN diff/提交说明只在有界内存保留，单响应不超过 512 KiB，总缓冲 8 MiB，最长 60 秒且不超过任务截止。只读结果丢失可以在原授权/版本下重新取得并比较摘要；摘要变化则拒绝。不要把日志、原文或凭据写入排障报告。

代码分析会话设置 `--no-session-persistence` 和 `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`，防止 SDK 将源码读取及 SVN 原文另存为会话转录。审计只保留工具、版本、授权范围等安全元数据。不要为排障打开包含完整请求/响应的 SDK debug 日志。

管理页面的目录预览不含源码或提交正文，允许最多 2 MiB 的固定字段路径清单，仍受总内存 8 MiB、60 秒过期和管理员权限约束。只有管理 browse 分支启用该限额；问答 SVN 原文维持单响应 512 KiB。两端校验目录预览结构，不能以该标记传递 diff 或任意正文。
