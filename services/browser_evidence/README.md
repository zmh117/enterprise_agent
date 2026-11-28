# 浏览器证据部署

完成平台基础配置后，在项目根目录执行 `docker compose up -d`。主 Compose 会启动一次性的 `evidence-bucket-init`，随后启动 `evidence-loki` 和 `evidence-alloy`。API 通过内部 HTTP 将证据写入 `evidence-alloy:3500`，从 `evidence-loki:3100` 读回。插件继续使用原有平台地址。证据入口所在的 Docker 网络为内部网络，两个端口均不映射到宿主机。

## 存储与升级

文件服务和 Loki 共用 `minio:9000`，分别使用受限身份访问私有文件桶和 `browser-evidence` 桶。沿用平台密钥初始化脚本准备文件服务凭据。证据桶身份首次部署时自动生成，保存在 `evidence-storage-identity` 卷，由 Loki 只读挂载。请随 MinIO 数据一起备份和恢复该卷。证据保留 7 天，证据桶配额由 `BROWSER_EVIDENCE_QUOTA` 配置，默认 20 GiB。

已配置 `BROWSER_EVIDENCE_STORAGE_ENV_FILE` 或 `BROWSER_EVIDENCE_S3_ACCESS_ID` 和 `BROWSER_EVIDENCE_S3_ACCESS_SECRET` 的部署应继续使用原凭据。外部环境文件应限制权限为 `0400`，包含 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY`。两个字段均须填写。初始化会核对既有身份，保留原有证据桶、块、索引及配额设置。

升级到本版本时执行 `docker compose up -d --build`，让 API 加载 HTTP 客户端实现。原有证书目录和证据读写 URL 配置可以移除。首次部署或升级时需要可用的固定摘要 Loki、Alloy 镜像。

**旧版文件服务升级**应先保留现有桶、卷和正在运行的管理入口。在维护窗口准备文件密钥，运行 `docker compose run --rm minio-init`，通过平台凭据管理的轮换操作将文件服务引用的两份 Secret 调整为新文件中的值，再更新文件服务和 Migrator。已有受治理值和本地 bootstrap 不同会阻断启动。文件服务访问系统 MinIO 时核对已配置身份的摘要，旧 root 身份会导致就绪失败。原先使用手工创建的 MinIO 用户时，也应切到本部署新建的受限身份。先确认文件服务就绪，并通过其正常入口读回已有附件、写入一个测试文件。共享部署要求文件服务使用系统地址 `http://minio:9000`。

## 核对采集

```sh
docker compose ps -a evidence-bucket-init evidence-loki evidence-alloy
```

证据桶初始化预期以 0 退出，Loki 和 Alloy 应保持运行。插件收到平台转发回执后才记为已转发，成功读回并核对分片摘要后才记为已核对。

本地可在构建 `browser-extension/` 后执行 `.venv/bin/python services/browser_evidence/test_roundtrip.py`。脚本使用隔离的 Compose 项目、临时卷、合成身份及回环端口，覆盖重复初始化、跨桶拒绝、API 写入及读回、MinIO 落盘和插件用例。
