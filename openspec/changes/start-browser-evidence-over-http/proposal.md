## Why

默认部署只启动平台服务，插件持续采集的证据留在本地待传。现场希望在已有平台部署中直接执行普通 Compose 启动命令，通过容器内网 HTTP 转发和读回证据。

## What Changes

- 将证据桶初始化、Loki、Alloy 纳入主 Compose 默认服务，API 固定使用内部 HTTP 地址。
- 去除容器间客户端证书要求，保留专网、租户及录制归属校验和私有桶隔离。
- 默认部署可自行初始化并复用证据桶专用身份，兼容已经设置专用对象存储身份的部署。

## Capabilities

### Modified Capabilities

- `platform-operations`：调整浏览器证据默认部署以及共享 MinIO 的内部传输方式。

## Impact

影响主 Compose、平台证据传输、证据存储初始化、运维说明和合成验收。
