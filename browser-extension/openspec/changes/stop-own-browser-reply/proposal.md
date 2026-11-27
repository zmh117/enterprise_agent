# Proposal

## Why

阅读浮窗和插件控制台共用消息输入区。用户在问题已经发送后，需要在原位置停止当前回答，同时能保留正在编写的下一条消息。

## What Changes

- 提交问题后，同一个发送按钮切换为「停止回答」。即使回执尚未到达，也接收本次停止操作。
- 按本轮回执中的任务标识向平台请求取消。运行中的任务等待平台确认，任务结束后恢复发送。
- 在输入框中按 Enter 不会触发停止。停止操作保留追问草稿。

## Capabilities

### New Capabilities

### Modified Capabilities

- `floating-assistant` 记录阅读浮窗和插件控制台共用的停止交互与验收场景。

## Impact

涉及共享输入区、控制台与浮窗的回答渲染，以及两个入口的浏览器回归。权限与终态定义见[平台侧同名变更](../../../../openspec/changes/stop-own-browser-reply/proposal.md)。
