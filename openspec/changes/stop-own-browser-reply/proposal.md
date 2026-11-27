# Proposal

## Why

插件用户发出问题后，有时需要立即纠正问题或停止耗时的分析。现有管理端取消接口要求 `jobs.manage`，而普通用户只需要控制自己从插件发起的一轮任务。

## What Changes

- 增加插件本人专用的 Job 取消接口，同时核验平台来源、消息回执、会话、发起人和当前应用授权。
- 复用任务的持久化取消流程。已准入时返回取消已请求，任务的流或快照提供最终结果。

## Capabilities

### New Capabilities

### Modified Capabilities

- `execution-delivery` 规定插件本人取消的权限边界及终态语义。

## Impact

涉及浏览器渠道 API、回答状态投影与浏览器扩展协议 v1。配套交互见[插件侧同名变更](../../../browser-extension/openspec/changes/stop-own-browser-reply/proposal.md)。
