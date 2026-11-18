## Why

SVN 目录浏览调用递归 inventory，一次读取整个分支 XML，真实大工程容易超过 8 MiB 上限；前端仅显示原始错误码。浏览当前层不应依赖整个仓库清单的大小。

## What Changes

- 首次浏览只列当前层文件与目录，展开文件夹后按需加载其直接子项。
- 子层请求继承首次浏览的连接、仓库、配置和数字修订，保留多选、父项包含子项与完整检出行为。
- 保持有界响应和临时结果存储；超限、过期或连接错误提供可操作的中文提示。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`：代码知识库的固定版本、按层目录浏览。

## Impact

影响 API、knowledge-sync 和管理前端。不增加服务、数据库表或凭据，不修改既有工作副本，不改变 Agent 工具合同或模型运行。部署须更新这三个组件；目标 Windows 环境须由部署人员验收。
