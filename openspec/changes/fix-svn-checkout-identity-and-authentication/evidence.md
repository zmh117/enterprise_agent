# 本机验证记录 · 2026-11-10

## 实现与自动检查

- 后端定向运行 316 项通过，覆盖检出、持久身份、凭据引用、资源发布、原生源码权限、SVN 控制桥、工具摘要、知识目录及 Schema 事实目录。
- 最终接口调整后的相关回归 258 项通过；维护恢复专项 9 项通过；包含加密凭据读取与 HTTP 入口的 SVN 连接专项 12 项通过。这些运行存在重叠，不相加作为唯一用例总数。
- 前端配置与运行时间线 41 项通过，生产构建通过。
- 所有修改的 Python 文件通过 Ruff；32 个修改的应用源文件通过 mypy。
- OpenSpec strict 校验通过，git diff --check 通过。
- 扩展运行 `test_mcp_tool_runtime.py` 时出现两类未修改的旧夹具问题：断言所有 knowledge-mcp 工具只读（已有 `knowledge_svn_update` 为写操作）；`_SkillLoader` 缺少 `load_publication`。该扩展运行未全绿，不算作通过的验证。

## 真实协议与迁移

- 独立 Linux 容器运行 Apache HTTPS + SVN 1.14，只有合成账号、合成 C++ 文件、r1/r2，不挂载用户仓库或真实凭据。
- 5 项真实 SVN 集成检查通过：用户名密码认证、错误密码、证书拒绝、目录/文件检出、固定修订、log、diff、update 与只读元数据核验；原有完整/稀疏检出与原子发布检查也通过。
- `--no-auth-cache` 下 SVN 会创建空认证目录，但没有写入认证文件；测试检查的是文件不存在，不误把空目录作为凭据泄漏。
- 在独立 PostgreSQL 测试库完整迁移到 161 并通过 SchemaHeadValidator；测试库和 SVN 夹具容器已删除。

## 本机部署

- 排空检查：没有 RUNNING Job、未释放分析读占用或未静默 SVN 操作，停止应用执行服务后升级。
- 本机 PostgreSQL 从 160 升至 161；已有知识 MCP 角色仅增加环境关联所需列的读取权限，连接表 `secret_ref` 的读取仍被拒绝。
- 更新相关后端服务、两个 Runtime 和前端镜像；Runtime 构建白名单包含新的身份模块，并在构建时执行源码挂载模块导入检查。
- `mes-business` 和 `mesx` 完整核验后升级为持久身份协议，generation 从 1 到 2，均保持 SVN r2。未修改源码文件，未清空答案。
- `mes-business` 实际检查：7,541 个文件，mixed=false、modified=false、switched=false。
- Runtime A、B 实际读取 `set_server/pubclass/Control/EquipUnit.cpp` 并核验 revision=2；仅记录成功元数据，没有输出源码正文。两者持久身份摘要相同，源码挂载均为只读；knowledge-sync 对同一个宿主检出根目录有写权限。
- 单独重建 Runtime A 后，再次只读核验成功、持久身份未变化。两个 Runtime 均为 `agent-system-prompt-v14`。
- API、两个 Runtime、knowledge-sync、knowledge-mcp 以及其余已更新服务的健康检查通过。
- 现有 `mes-code-answers` 发布配置重新解析成功；现有 4 条代码答案保留。没有擅自替该库选择环境，管理员可在配置页多选并验证发布。

## 验证范围

没有启动模型提取、没有重放原业务 Job。以上证明源码访问与配置链路，不能替代模型回答质量验收。尚未提供企业 SVN 连接，因此企业网络/账号及其 CA 需在现场验证。Windows/Linux 宿主未实测；本机为 macOS + Linux 容器。浏览器连接不可用，页面交互验证采用组件测试和生产构建，未声称完成登录页面人工验收。
