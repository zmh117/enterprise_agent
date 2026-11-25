# Proposal

## Why

用户在 MES 复现问题后，可以在本地查看请求、回放或导出 ZIP。把同一段操作交给 Enterprise Agent 连续排查时，需要能在插件里用自己的平台身份分享一次录制，并在回答生成过程中追问、断线后继续读。

## What Changes

- 在扩展控制台连接用户选择的内网 HTTP 平台，使用系统现有账号登录后，选择本人获准使用且启用了插件入口的活动应用。发行包固定插件身份，平台地址由用户首次输入。活动期间自动续期，平台登录失效时提示用户重新登录。
- 用户可直接提问，也可选择一段已结束且保存完整的录制。预览请求、响应和操作中的业务字段与采集缺口，经确认才分片上传。同一授权范围的同一录制版本只发布一次，恢复时只补缺片。
- 追问使用服务端会话，允许绑定、切换或解除录制。Agent 在服务端按需查请求或操作，每轮只发问题和必要引用。
- 以 SSE 接收主对话助手正文，包括工具前的说明和工具后的结论。在同一条回复中按 Markdown 逐步展示，断线按游标续读，重开时从持久消息恢复全文。

## Capabilities

### New Capabilities

- `enterprise-agent-conversation` — 控制台以平台用户身份共享诊断录制、发起多轮问答并恢复回答。

### Modified Capabilities

无。

## Impact

插件改动集中在 `extension/ui/control.*`、`extension/manifest.json` 和 `extension/storage/database.ts`。本地保存、离线导出和回放仍可独立使用。远程共享自动覆盖新业务字段，另行剔除凭据和原始业务消息，原始问题包保留在本机。

对应平台提案为 Enterprise Agent 的 `add-browser-extension-agent-channel`，具体消息、分片和事件定义以[平台版本化契约](../../../../contracts/browser-extension/v1/README.md)为准。平台负责授权、建索引、Job 执行及回答留存。插件开发规格第 11.3 节将上传定义为可选能力，现有验收记录中生产 MES 和可选上传仍待接入。本提案将客户端实现、合成联调与目标部署验收分别列为待办。[插件开发规格](../../../MES_Browser_Evidence_Collector_Development_Spec.md) · [现有验收记录](../../../docs/acceptance.md)
