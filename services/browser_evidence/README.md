# 浏览器证据试用栈

这个 Compose 项目使用独立的 Alloy、Loki 和 MinIO。运行它的主机需要 Docker Compose。为这套试用栈单独提供 `BROWSER_EVIDENCE_S3_ACCESS_ID` 和 `BROWSER_EVIDENCE_S3_ACCESS_SECRET`，通过部署环境的 Secret 注入。MinIO 专供这套本地试用栈，Loki 的 TSDB 索引和压缩块写入 `browser-evidence` 桶。试用配置的保留期为 7 天。

为试用栈签发专用 CA 和用途受限的服务器、客户端证书。Loki 与 Alloy 的服务器证书分别包含服务 DNS 名称。只有平台 API 和 Alloy 获发客户端证书。配置以下三个只读目录，分别挂载到相应服务，以运行身份授予私钥读取权限。

| 配置 | 目录中的文件 |
|---|---|
| `BROWSER_EVIDENCE_LOKI_TLS_DIR` | `ca.crt`、`server.crt`、`server.key` |
| `BROWSER_EVIDENCE_ALLOY_TLS_DIR` | `ca.crt`、`server.crt`、`server.key`、`client.crt`、`client.key` |
| `BROWSER_EVIDENCE_API_TLS_DIR` | `ca.crt`、`client.crt`、`client.key`，路径从 API 容器内部解析 |

在仓库根目录启动试用栈。

```sh
docker compose -p mes-browser-evidence -f services/browser_evidence/compose.yaml up -d
```

把平台 API 容器加入 `mes-browser-evidence_ingress` 内部网络，并为该服务配置下列地址。普通日志工具、Grafana 和业务服务使用各自的网络。对象存储位于另一张内部网络，Compose 默认不发布任何宿主机端口。

| 平台 API 配置 | 栈内地址 |
|---|---|
| `BROWSER_EVIDENCE_WRITE_URL` | `https://evidence-alloy:3500` |
| `BROWSER_EVIDENCE_READ_URL` | `https://evidence-loki:3100` |

插件只访问已连接的 Enterprise Agent。API 从登录来源派生 Loki 租户，核对所有者、应用、标签实例、顶层文档和绑定版本。Alloy 把内部路由标签转为 Loki 的租户身份。录制 ID、用户和车间保存在记录内容中。收到转发回执后，还需从 Loki 读回对应切片并核对摘要才能确认可见。

停用试用时，从平台 API 配置移除写入地址并按现有部署方式重启该服务。保留读取地址供已接收材料核对。停止收集后，可用下列命令停止试用栈并保留卷。

```sh
docker compose -p mes-browser-evidence -f services/browser_evidence/compose.yaml stop
```

Alloy 的接收接口兼容 Loki Push API，TSDB 和对象存储的配置见官方文档。[Alloy 接收接口](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/) · [Loki 存储](https://grafana.com/docs/loki/latest/configure/storage/)

本地合成联调需要本机已有 Compose 镜像、插件依赖、平台测试虚拟环境和支持扩展的 Chromium。可用 `MES_TEST_CHROME` 指定浏览器可执行文件。先在 `browser-extension/` 运行 `npm run build`，再于仓库根目录运行 `.venv/bin/python services/browser_evidence/test_roundtrip.py`。脚本创建临时 CA、独立测试项目及数据卷，在录制中的合成 MES 页面验证发布工具回读，最后清理该项目。插件回退演练另用 `EA_TEST_FLOAT=1 EA_TEST_PREVIOUS_DIST=/path/to/previous/dist npm run test:agent`，在停用持续写入的测试环境执行。
