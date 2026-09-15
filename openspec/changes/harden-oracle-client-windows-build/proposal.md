## Why

Windows checkout 可能把 Oracle Python 检测脚本转换为 CRLF，Linux shebang 执行失败后又被归类为未找到客户端，导致镜像构建成功但没有 Instant Client。需要修复构建链路的跨平台行尾兼容与错误判定。

## What Changes

- 为 Docker 构建用 Python 脚本固定 LF，并在 Oracle 镜像构建阶段归一化复制进来的安装和检测脚本行尾。
- 统一显式使用 Python 解释器调用检测脚本，不依赖 shebang 或执行位。
- 区分合法 ZIP 无 19c 成员与检测器执行失败、损坏 ZIP；后两者必须终止构建并给出明确错误。
- 保留未提供合规客户端时 Oracle 不可用、其他 Provider 可用的行为，以及 19c/64-bit/架构限制。
- 添加 CRLF、含空格路径、检测异常与安装验收回归，补齐 Windows 和目标主机更新说明。
- 经用户确认补齐 libaio1t64 的 64 位兼容链接，并在实际提供客户端时执行构建期 Thick 初始化检查；依赖缺失或初始化失败必须终止构建。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`：明确 Oracle 镜像构建兼容 Windows CRLF，且检测故障不得被伪装为正常缺少客户端。

## Impact

仅修改 Git 行尾规则、Oracle 构建脚本、Dockerfile、测试及部署说明。无数据库迁移、Runtime 协议修改或自动发布；不部署到用户远端机器，不下载或提交 Oracle 客户端二进制。
