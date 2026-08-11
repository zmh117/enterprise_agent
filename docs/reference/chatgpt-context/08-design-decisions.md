# 08 当前设计决策

1. MCP 替换工具协议和旧平台抽象，不删除身份、RBAC、范围、Secret、审计和发布治理。
2. 工具目录由代码 Manifest 提供，管理端只读展示；不做动态 Handler/Release。
3. Resource 在平台发布，Application 不做 Resource Mapping。
4. 用户输入会变化，因此 Job 不冻结推断目标；Agent 在实际 Tool Call 中选择，服务端实时复核。
5. Worker 连接两个独立 Runtime；不把两套 SDK 强塞进一个 Runtime 进程。
6. ONES 身份证明与业务工具调用凭据分离；当前不保存 ONES 长期调用 Token。
7. MCP 不新增专用治理层或密钥；既有业务治理继续生效。
