# 本机 SVN 与 Docker 工程检出

## 当前可用入口

- 管理页面：`http://localhost:${ADMIN_WEB_PORT:-8080}/platform/resources` → **知识库 → 新建/打开代码知识库 → SVN 工程检出**。
- 可选本机 SVN 服务：由 `scripts/local_svn.py` 与 `docker-compose.code-svn-local.yml` 管理；宿主 HTTPS 端口与仓库路径以 `local_svn.py info` 输出为准。
- 项目 Docker 网络内地址：以部署登记的内部 HTTPS URL 为准（本地示例常见为 `https://code-svn:8443/...`）。
- 容器检出根目录：`/var/lib/code-svn/checkout`；由 Docker 命名卷 `<项目名>_code-svn-checkout` 保存。

## 在管理页面多选检出

1. 使用具有知识管理权限的管理员账号进入上述页面。
2. 在「SVN 仓库地址」填写执行容器可访问的仓库 URL。在「SVN 版本（留空为最新）」填写数字修订，或留空，让系统在浏览时固定最新修订。
3. 在「SVN 认证方式」按仓库要求选择。
   - 允许匿名读取的仓库，选「无需认证」，点「浏览目录」。
   - 需要账号的仓库，选「配置用户名密码」，填写「SVN 用户名」和「SVN 密码」，点「保存连接并浏览」。页面提示「账号凭据已保存」后，再次浏览可留空密码并点「浏览目录」。
4. 等待目录树显示「已固定 SVN r…」，核对修订号。展开文件夹，勾选需要的文件或目录，或勾选「检出整个仓库」。选中父目录会包含其所有子项。
5. 在「目标子目录」输入一个尚不存在的目录名，点「检出所选内容」。
6. 在「SVN 检出任务」中确认状态为「已完成」，核对 SVN 修订和「检出目录」。关闭或刷新页面后，后台任务会继续执行。

页面只接受检出根目录下的新子目录名。浏览后即使 SVN 有新提交，检出仍使用该次浏览固定的版本。任务失败且页面提供「重新校验已有目录」时，可沿用原目录、版本和所选范围进行校验。需要重新下载时使用新的子目录名。

## 在宿主其他目录拉取

在项目根目录运行，宿主机无需安装 SVN；检出由 Docker 执行。目标目录必须不存在，其父目录需允许 Docker Desktop / daemon 访问。必须显式提供 `--destination`：

```bash
python3 scripts/local_svn.py checkout \
  --destination /path/to/new-workdir \
  --revision <数字修订> \
  --select path/to/component-a \
  --select path/to/component-b
```

省略所有 `--select` 表示整个仓库；可重复指定其他文件或子目录。目录结构保持相对主干的位置。省略 `--revision` 时会先固定当前最新版本。

Docker 创建的工作副本记录容器网络地址。需要直接在宿主上运行原生 `svn update` 时，请用下面的原生命令创建工作副本，以记录本机可访问的 localhost 地址。

已安装 SVN 的宿主也可以直接使用原生命令。只信任本机生成的公开证书，不关闭 TLS 验证：

```bash
svn checkout -r <数字修订> \
  --config-option servers:global:ssl-authority-files=<CODE_SVN_LOCAL_STATE_ROOT>/tls/server.crt \
  https://localhost:<本机HTTPS端口>/<仓库路径> \
  /path/to/native-workdir
```

证书路径、端口与仓库路径以 `python3 scripts/local_svn.py info` 与状态目录实际内容为准，不要照抄他人机器上的绝对路径。

## 部署与启停

首次部署到空目录的流程如下。不要把某次本机已初始化状态写成通用前提。

先按 [部署手册](docker-deployment.md) 执行 `docker compose run --build --rm --no-deps code-storage-init`，准备源码卷和配置中的状态根。
本地辅助脚本不再自动创建未经初始化的根目录。使用 `--destination` 指定其他父目录时，也要
先初始化该源码根；脚本的检出进程使用 10003:10010，与页面执行器一致。容器初始化不需要
宿主 sudo；目标宿主的实际只读共享行为仍需验证。

```bash
python3 scripts/local_svn.py init
python3 scripts/local_svn.py import --source-root /绝对路径/待导入工程根
python3 scripts/local_svn.py start
python3 scripts/local_svn.py info
```

`--source-root` 填三个工程的共同根目录。首次导入固定读取该根目录下的 `set_server/`、`set_web/EBR/`、`set_web/JTH/`。三个路径都必须是实际目录，缺少任一项或以符号链接代替都会返回 `svn_source_component_invalid`。根目录下的其他工程不在导入范围内。成功导入后，再次执行会被拒绝。初始化生成的本机证书、连接登记和客户端配置可在以后启动时复用。

完整工程检出功能由 `.env` 中 `CODE_CHECKOUT_ENABLED=true` 启用。首次启用时需要通过既有迁移流程升级数据库到当前 head，并构建、更新 API、knowledge-sync、前端及要求当前 schema head 的服务。主 `docker-compose.yml` 保留 API/worker 接线，可选 `docker-compose.code-svn-local.yml` 负责本地 SVN 服务。检出不会启动模型。问答按需访问代码的部署步骤见 [按需代码知识库](code-knowledge-on-demand.md)。

日常启停本地 SVN：

```bash
python3 scripts/local_svn.py stop
python3 scripts/local_svn.py start
```

仓库数据、TLS 材料和任务结果都持久保存；停止不会清空目录。若停用检出功能，将其开关设为 false 后更新 API 和 knowledge-sync。不要在检出执行中手动移动或修改输出目录。

部署变量：`CODE_SVN_LOCAL_STATE_ROOT` 指定 SVN 状态目录，`CODE_SVN_CHECKOUT_VOLUME` 指定实际源码卷名；旧 `CODE_SVN_CHECKOUT_HOST_ROOT` 不再生效。主 Compose 默认基于 `KNOWLEDGE_DEPLOY_ROOT`，本机未设置时使用项目目录；运维控制器继续使用它已有的宿主路径解析。`scripts/local_svn.py` 的 checkout/browse 必须显式提供 `--destination`，仅用于独立宿主维护目录；系统内检出使用页面，不能借此修改受管源码卷。该脚本使用当前项目默认状态目录、默认网络；自定义部署路径应通过 Compose 管理并同步登记配置。

## 访问与按需分析边界

- 服务仅发布本机回环地址上的 HTTPS 端口，供本机和已接入项目网络的容器读取；没有对局域网开放。
- 网络 SVN 为只读。本次不提供从工作副本 `svn commit` 的写入账号；初始化与首次导入使用离线部署容器。
- 页面按填写的 URL 直接连接，支持 `http://`、`https://` 和 `svn://`。容器内的 `localhost` 指向执行容器自身。使用企业自签证书时，由部署人员配置受信任的 CA。账号凭据由凭据中心加密保存。
- 第一版发现分支存在 `svn:externals` 时明确拒绝检出，不会静默跳过后声称完整。
- 工程内容、私钥、密码不会通过 API 或日志返回；仓库和工作副本目录均不进入 Git 或构建上下文。
- 新流程把同一检出根只读挂给两个 Runtime，可写挂给 knowledge-sync。分析使用原问答 Job；update/log/diff/blame 经现有 Knowledge MCP 由 knowledge-sync 执行。同版本可并发读，更新必须等所有读者实际停止。
- 旧版本的 `sources.json` 不再是运行依赖。已有目录通过 `app.cli.register_code_checkout` 只读核实后登记，再在代码知识库配置中绑定；不会复制源码，也不会把未知本地版本当成任意 SVN 修订。

未完成的真实验收见 [验收欠账](../acceptance-backlog.md)。
