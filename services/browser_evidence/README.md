# 浏览器证据的部署与回退

仓库根目录的 `docker-compose.yml` 通过 `browser-evidence` profile 启动 Alloy、Loki 和一次性证据桶初始化。Loki 使用本机 `grafana/loki:latest`，Compose 禁止自动拉取。文件服务和 Loki 共用 `minio:9000`，默认分别使用 `agent-files` 和 `browser-evidence` 两个私有桶。Loki 将压缩块和 TSDB 索引写入证据桶，本地工作目录单独使用 `evidence-index` 卷。证据保留 7 天，证据桶容量由 `BROWSER_EVIDENCE_QUOTA` 配置，默认 20 GiB。按磁盘可用容量调整配额并为附件留出空间。

## 准备身份与证书

1. 按系统部署手册运行既有的密钥初始化脚本。它在 `PLATFORM_SECRETS_DIR` 中生成文件桶专用的 `file-storage-access-id` 与 `file-storage-secret-key`，重复运行保留原值。主 Compose 的 `minio-init` 创建文件桶受限身份。生产环境按既有平台 Secret 流程配置文件服务引用，本地首次安装可使用 Migrator 的显式 bootstrap。
2. **存量升级**应先保留现有桶、卷和正在运行的管理入口。在维护窗口准备文件密钥，运行 `docker compose run --rm minio-init`，通过平台凭据管理的轮换操作将文件服务引用的两份 Secret 调整为新文件中的值，再更新文件服务和 Migrator。已有受治理值和本地 bootstrap 不同会阻断启动。文件服务访问系统 MinIO 时核对已配置身份的摘要，旧 root 身份会导致就绪失败。原先使用手工创建的 MinIO 用户时，也应切到本部署新建的受限身份。先确认文件服务就绪，并通过其正常入口读回已有附件、写入一个测试文件，再启用证据采集。共享部署要求文件服务使用系统地址 `http://minio:9000`。
3. 在仓库外的受保护目录准备一个权限为 `0400` 的环境文件，内含 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY`。在项目 `.env` 用 `BROWSER_EVIDENCE_STORAGE_ENV_FILE` 指向它，仅证据桶初始化和 Loki 加载该文件。已有部署也可沿用 `BROWSER_EVIDENCE_S3_ACCESS_ID` 和 `BROWSER_EVIDENCE_S3_ACCESS_SECRET`。使用专用随机 ID（3–20 个 ASCII 字符）与随机密钥（建议 40 个十六进制字符）。证据初始化创建受限身份、私有桶和配额，重复初始化核验既有密钥。
4. 使用证据专用 CA 签发证书，服务器证书的 SAN 分别包含 `evidence-loki`、`evidence-alloy`。只给平台 API 和 Alloy 签发客户端证书。以下均为宿主机只读挂载目录，密钥须可由对应容器 UID 读取。

| 宿主配置 | 所需文件 |
|---|---|
| `BROWSER_EVIDENCE_LOKI_TLS_DIR` | `ca.crt`、`server.crt`、`server.key` |
| `BROWSER_EVIDENCE_ALLOY_TLS_DIR` | `ca.crt`、`server.crt`、`server.key`、`client.crt`、`client.key` |
| `BROWSER_EVIDENCE_API_TLS_DIR` | `ca.crt`、`client.crt`、`client.key` |

## 启用与停用

在部署配置中设置 `BROWSER_EVIDENCE_WRITE_URL=https://evidence-alloy:3500` 和 `BROWSER_EVIDENCE_READ_URL=https://evidence-loki:3100`。在系统项目原目录运行以下命令。可将 `browser-evidence` 加入 `COMPOSE_PROFILES` 以沿用日常启动命令。启用前记录本机镜像 ID，确认以后复现测试时使用同一构建。

```sh
docker image inspect grafana/loki:latest --format '{{.Id}}'
docker compose --profile browser-evidence config --quiet
docker compose --profile browser-evidence up -d --build file-service api-server evidence-alloy
```

插件沿用 Enterprise Agent 地址。API 负责验证录制归属、派生租户，写入 Alloy 并从 Loki 查询；两端均校验客户端证书。普通日志服务没有证据证书，Alloy、Loki 不发布宿主端口。上传 ACK 后，回读切片并核对摘要才算可见。

暂停写入时将 `BROWSER_EVIDENCE_WRITE_URL` 留空，保留读取地址，执行 `docker compose up -d --no-deps api-server` 使配置生效。等待在途写入可读后可停止 Alloy。需要完全停用时再清空读取地址、更新 API，执行 `docker compose --profile browser-evidence stop evidence-alloy evidence-loki`。保留共享 MinIO 及所有卷。旧独立试用栈的数据仍在原项目卷中；需要继续查询旧证据时，先保留原栈入口并单独安排数据迁移。

## 本地验证

在 `browser-extension/` 构建插件后，于仓库根目录运行 `.venv/bin/python services/browser_evidence/test_roundtrip.py`。需要本机已有镜像、插件依赖、平台虚拟环境及支持扩展的 Chromium（可设置 `MES_TEST_CHROME`）。脚本从主 Compose 选择存储与采集服务，使用临时 CA、合成身份、随机端口和独立测试卷。它验证重复初始化、跨桶拒绝、录制期间回读与证据块落盘，最后只清理本次测试项目。
