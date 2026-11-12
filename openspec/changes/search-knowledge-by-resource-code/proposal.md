## Why

用户知道知识资源页面上的编码（例如 `mes_story`），却被要求提供内部知识库 UUID。当前检索只接受知识库 ID，且目录返回的 code 来自底层知识库，可能与资源编码不同。

## What Changes

- 知识检索接受资源编码或知识库 ID，二者只能提供一个；编码由服务端精确解析，复用当前授权、发布和来源检查。
- 目录的 code 与资源页面保持一致；Agent 收到明确编码时直接检索，不再索要 UUID。
- 同步工具合同、提示说明和测试；部署相关服务，并为 assist03 发布更新后的工具合同。

## Capabilities

### New Capabilities

无新增领域。

### Modified Capabilities

- `builtin-tool-resource`：知识检索按资源编码定位，并保留所有现有授权和版本约束。

## Impact

影响 knowledge-mcp 检索编排、治理仓储、共享工具合同和 Runtime 工具说明。无需修改数据库结构或重建索引。工具合同变化通过新发布生效，不改写历史发布或 Job。
