# 本机 SVN 与 Docker 工程检出

## 当前可用入口

- 管理页面：`http://localhost:8080/platform/resources` → **知识库 → 新建代码知识库（或打开已有代码知识库）→ SVN 工程检出**。
- Mac 访问地址：`https://localhost:18443/repos/mes/trunk`。
- 项目 Docker 网络内地址：`https://code-svn:8443/repos/mes/trunk`。
- 本次完整工程版本：**r2**，包含 `set_server`、`set_web/EBR`、`set_web/JTH`。r1 只有空主干。
- 容器检出根目录：`/var/lib/code-svn/checkout`；由 Docker 命名卷 `<项目名>_code-svn-checkout` 保存，不再对应 Windows D 盘或 Mac 项目目录。

2026-11-07 的旧宿主目录曾保留两份验证用工作副本（切换后不自动迁移）：`mes-r2` 包含三个工程，`ui-selected-r2` 只包含 EBR、JTH。完整导入和检出没有按扩展名或知识准入规则过滤文件。

## 在管理页面多选检出

1. 使用具有知识管理权限的管理员账号进入上述页面。
2. 输入已由部署人员登记的仓库地址；版本留空表示浏览时固定最新版本，也可以填写 `2`。
3. 点击“浏览目录”，等待目录树加载，检查显示的固定 SVN 版本。
4. 展开目录，查看子文件夹与文件名（包括隐藏文件），多选需要的文件或子目录；也可选择“检出整个仓库”。文件支持单独勾选，也可与文件夹混合选择；选择父目录即包含其所有内容并移除重复子项。更新前已生成的浏览结果需要重新点击“浏览目录”获取文件清单。
5. 输入一个尚不存在的目标子目录名，例如 `mes-r2-copy`，点击“检出所选内容”。
6. 等待任务显示“已完成”和实际容器目录。关闭或刷新页面不会取消后台任务。

页面只接受检出根目录下的子目录名，不允许任意宿主路径，也不会覆盖已有目录。浏览后即使 SVN 有新提交，检出仍使用该次浏览固定的版本。后台重启后，无法确认完成的任务标记为中断；再次检出使用新的目录名。

## 在 Mac 的其他目录拉取

在项目根目录运行，宿主机无需安装 SVN；检出由 Docker 执行。目标目录必须不存在，其父目录需允许 Docker Desktop 访问。

```bash
python3 scripts/local_svn.py checkout \
  --destination /Users/mhz/Develop/mes-checkout-r2 \
  --revision 2 \
  --select set_server \
  --select set_web/EBR \
  --select set_web/JTH
```

省略所有 `--select` 表示整个仓库；可重复指定其他文件或子目录。目录结构保持相对主干的位置。省略 `--revision` 时会先固定当前最新版本。

Docker 创建的工作副本记录容器网络地址。需要直接在 Mac 上运行原生 `svn update` 时，请用下面的原生命令创建工作副本，以记录 Mac 可访问的 localhost 地址。

已安装 SVN 的 Mac 也可以直接使用下面的命令。只信任本机生成的公开证书，不关闭 TLS 验证；浏览器无需打开该 HTTPS 地址。

```bash
svn checkout -r 2 \
  --config-option servers:global:ssl-authority-files=/Users/mhz/Develop/enterprise_agent/.local/code-svn/state/tls/server.crt \
  https://localhost:18443/repos/mes/trunk \
  /Users/mhz/Develop/mes-native-r2
```

## 部署与启停

当前 Mac 已初始化、导入并启动，**无需重新初始化或导入**。首次部署到空目录的流程如下：

先按 [部署手册](docker-deployment.md) 执行 `docker compose run --build --rm --no-deps code-storage-init`，准备源码卷和配置中的状态根。
本地辅助脚本不再自动创建未经初始化的根目录。使用 `--destination` 指定其他父目录时，也要
先初始化该源码根；脚本的检出进程使用 10003:10010，与页面执行器一致。容器初始化不需要
宿主 sudo；目标宿主的实际只读共享行为仍需验证。

```bash
python3 scripts/local_svn.py init
python3 scripts/local_svn.py import --source-root /绝对路径/项目代码
python3 scripts/local_svn.py start
python3 scripts/local_svn.py info
```

首次导入固定为此前确认的三个工程，不包含其他 EBR 副本。导入命令拒绝重复导入；不执行同步、覆盖或删除。初始化会生成本机证书、连接登记和客户端配置；不要把它当成日常配置更新命令。

完整工程检出功能由 `.env` 中 `CODE_CHECKOUT_ENABLED=true` 启用。首次启用时需要通过既有迁移流程升级数据库，并构建、更新 API、knowledge-sync、前端及要求当前 schema head 的服务。主 `docker-compose.yml` 保留 API/worker 接线，可选 `docker-compose.code-svn-local.yml` 负责本地 SVN 服务。检出不会启动模型。问答按需访问代码的部署步骤见 [按需代码知识库](code-knowledge-on-demand.md)。

日常启停本地 SVN：

```bash
python3 scripts/local_svn.py stop
python3 scripts/local_svn.py start
```

仓库数据、TLS 材料和任务结果都持久保存；停止不会清空目录。若停用检出功能，将其开关设为 false 后更新 API 和 knowledge-sync。不要在检出执行中手动移动或修改输出目录。

部署变量：`CODE_SVN_LOCAL_STATE_ROOT` 指定 SVN 状态目录，`CODE_SVN_CHECKOUT_VOLUME` 指定实际源码卷名；旧 `CODE_SVN_CHECKOUT_HOST_ROOT` 不再生效。主 Compose 默认基于 `KNOWLEDGE_DEPLOY_ROOT`，本机未设置时使用项目目录；运维控制器继续使用它已有的宿主路径解析。`scripts/local_svn.py` 的 checkout/browse 必须显式提供 `--destination`，仅用于独立宿主维护目录；系统内检出使用页面，不能借此修改受管源码卷。该脚本使用当前项目默认状态目录、默认网络；自定义部署路径应通过 Compose 管理并同步登记配置。

## 访问与按需分析边界

- 服务仅发布 `127.0.0.1:18443`，供本机和已接入项目网络的容器读取；没有对局域网开放。
- 网络 SVN 为只读。本次不提供从工作副本 `svn commit` 的写入账号；初始化与首次导入使用离线部署容器。
- 新 SVN 地址先在部署端登记 `checkout.json`，填写公开地址、内部 HTTPS 地址、仓库 UUID、分支及认证配置引用；页面不能临时输入密码或绕过登记访问任意地址。
- 第一版发现分支存在 `svn:externals` 时明确拒绝检出，不会静默跳过后声称完整。
- 工程内容、私钥、密码不会通过 API 或日志返回；仓库和工作副本目录均不进入 Git 或构建上下文。
- 新流程把同一检出根只读挂给两个 Runtime，可写挂给 knowledge-sync。分析使用原问答 Job；update/log/diff/blame 经现有 Knowledge MCP 由 knowledge-sync 执行。同版本可并发读，更新必须等所有读者实际停止。
- 旧版本的 `sources.json` 不再是运行依赖。已有目录通过 `app.cli.register_code_checkout` 只读核实后登记，再在代码知识库配置中绑定；不会复制源码，也不会把未知本地版本当成 SVN r2。
- 下述 r2 和目录记录是 2026-11-07 的历史验收，按需问答改造的部署与真实模型验收状态以当前变更证据为准。

本次验收记录见 [OpenSpec evidence](../../openspec/changes/add-local-svn-source-checkout/evidence/local-svn-20261107.md)。
