## Why

现场审计确认日志证据扫描因大小写重复关键词和缺少 `inputs/` 前缀的路径三次失败；运行记录又把具体错误折叠成通用失败，模型和运维人员无法有效纠正。本次修复输入易用性和错误可观测性，不扩大文件访问权限。

## What Changes

- 字面词在既有数量、长度和字节预算内按 `casefold()` 安全去重，保留首次出现的词及顺序；工具 Schema 与实现一致。
- 工具说明及参数说明明确使用已物化的 `inputs/` POSIX 相对 LOG 路径，不自动补前缀、不接受绝对路径、反斜杠或越界路径。
- 文件桥对扫描输入/路径错误返回固定中文纠正提示；Runtime 普通工具事件保留受控错误码、固定提示及正确重试分类，不复制实际路径、关键词或日志正文。
- 补充扫描、文件桥、Runtime 事件和控制面展示链路回归。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`：日志扫描的词项去重、输入边界与纠正提示。
- `execution-delivery`：扫描工具错误的安全传递与重试分类。

## Impact

涉及 Python Runtime 扫描器、File bridge、SDK 事件规范化和工具失败投影及相关测试。派生扫描工具的 Schema hash 随声明变化更新；不修改远端 File MCP 清单、Runtime 协议、数据库、权限或历史 Job，不部署或提交代码，不把本地合成验证描述为 Windows 真实验收。
