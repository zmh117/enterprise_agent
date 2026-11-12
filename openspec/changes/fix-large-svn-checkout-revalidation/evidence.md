# 验证记录（2026-11-12，本机 Mac / Docker Linux）

## 已核实

- 后端 SVN/检出/身份/操作/心跳/知识资源相关回归：157 passed，13 个需要独立现场/服务配置的测试 skipped；另补安全诊断投影后，检出专项 57 passed。
- API、检出与流式 XML 组合：82 passed。架构与测试分层治理加检出组合：132 passed（包含重复覆盖，不累加为独立测试总数）。
- 前端检出交互：23 passed；包含按原任务 ID 重新校验、仅提交幂等键、阶段与保留状态显示、旧错误兼容显示。相关 ESLint、前端 TypeScript/Vite build 通过。
- 修改模块 Ruff / 格式 / mypy 通过；Git diff whitespace 通过。
- 新 knowledge-sync 镜像内，隔离真实 file:// SVN 合成仓库 14 项验收通过。无网络、无平台数据库、无真实凭据；仅测试模块只读挂载，执行的是镜像中的应用代码。
- 16000 个合成文件的真实 SVN status/info 输出分别超过旧 8 MiB 上限；旧缓冲调用明确超限，新流式完整核验成功，文件计数 16000。
- 已完成目录在模拟校验超限后保留；重新核验禁止 checkout/update，仍成功。稀疏深度及父目录完整深度下的排除文件均拒绝复用，不冒充 ready。
- 管理流程测试覆盖：失败后保留、原目录重复校验、幂等及重复提交互斥、成功后原连接可绑定、未停止任务/写者/跨资源/连接变化拒绝、持久身份替换和目录缺失拒绝、旧物理身份空值经明确核验后登记。
- OpenSpec change 和 platform-operations / builtin-tool-resource 主规范 strict validate 通过。

## 本机部署

- 更新前两次只读检查 queued/running SVN 操作均为空。
- `docker compose build api-server knowledge-sync admin-web` 成功。
- `docker compose up -d --no-deps api-server knowledge-sync admin-web` 成功。API 与 knowledge-sync healthy，admin-web running，HTTP 8080 已实际返回含重新校验入口的新 JS。
- API 与 knowledge-sync 中六个修改模块 SHA-256 与当前工作区一致；API 新重新校验路由已安装。
- knowledge-sync 仍可写挂载原 `enterprise_agent_code-svn-checkout` 命名卷；Runtime A/B 仍只读挂载同卷。未删除卷、源码目录或历史数据，未启动模型提取或修改 assist03 发布。

## 边界

- 不能访问用户 Windows / 远端任务 `07e6144f-c0e6-53c2-b8ca-6808e022855e` 的工作副本；未直接核实该约 1.7 GiB 目录是否完整。上述结果不等同于该现场任务成功。
- 真实环境拉取本次代码后，等待 SVN 操作停止，更新上述三个服务，保留原 PostgreSQL 与源码卷，在原失败任务点击“重新校验已有目录”。成功后正常选择绑定；若缺文件、修改、元数据损坏或仍超过明确限额，保留目录并报告对应阶段，不自动下载或修复。
- 首次构建遇到前端共享常量导入重复，已修正并重新通过检查/构建；Docker buildx 缓存路径需沙箱提升，已在用户授权的容器更新范围内完成。无代码提交或推送。
