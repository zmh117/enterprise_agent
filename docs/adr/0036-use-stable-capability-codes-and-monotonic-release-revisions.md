# 使用稳定 Capability Code 和递增 Release Revision

Capability Code 是长期稳定的业务标识，例如 `ones.work_item.search`，不包含 `v1` 或 `v2` 后缀，也不得复用于不同业务含义。每次 Publish 为该 Code 创建单调递增的 Release Revision。只修改外部路径、固定 Query 或字段映射时，复用原 Capability Revision，创建新 Handler Revision 和 Capability Release；修改公开 Input 或 Output Schema 时，在同一 Code 下创建新 Capability Revision 和 Release，既有 Application Publication 继续冻结旧 Revision；业务含义变化时必须创建新的 Capability Code。新 Release 可以按 ADR-0035 软废弃旧 Release并指向替代版本。
