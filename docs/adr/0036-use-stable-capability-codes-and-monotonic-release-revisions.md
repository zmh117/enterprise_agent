# 使用稳定 Capability Code 和递增 Release Revision

Capability Code 按 ADR-0044 同时作为业务标识和模型 Tool 名，例如 `cap__ones__work_item__search`，不包含 `v1` 或 `v2` 后缀，也不得复用于不同业务含义。每次 Publish 为该 Code 创建单调递增的 Release Revision。只修改外部路径、固定 Query 或字段映射时，复用原 Capability Revision，创建新 Handler Revision 和 Capability Release；修改公开 Input 或 Output Schema 时，在同一 Code 下创建新 Capability Revision 和 Release，既有 Application Publication 继续冻结旧 Revision；业务含义变化时必须创建新的 Capability Code。新 Release 可以按 ADR-0035 软废弃旧 Release 并指向替代版本。
