## 1. 代码事实对账

- [x] 1.1 核对 Agent、Business Application、Channel、ONES、Identity、MCP、Runtime 与 Compose 的当前代码、schema、migration 和直接测试
- [x] 1.2 记录 Confirmed-current 与未验证真实外部 E2E 的证据边界

## 2. Delta Specs

- [x] 2.1 为八个受影响 canonical 领域编写完整 MODIFIED、REMOVED、ADDED 或 RENAMED delta
- [x] 2.2 严格校验 `reconcile-canonical-specs-to-current-code` change

## 3. Canonical 同步

- [x] 3.1 将八个 delta 精确合并到对应 canonical spec
- [x] 3.2 确认 `document-file-processing` 与 `task-file-workspace` 未发生无依据修改

## 4. 验证与收尾

- [x] 4.1 运行 canonical strict validation、相关现有测试、Compose config 和 `git diff --check`
- [x] 4.2 复核没有代码、migration、Compose、前端或测试文件被本 change 修改
- [x] 4.3 归档 change 并确认 active change 为空
