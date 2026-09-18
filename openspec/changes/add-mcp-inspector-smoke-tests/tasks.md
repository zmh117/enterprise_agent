## 1. 开发依赖与兼容性确认

- [x] 1.1 在 `tools/mcp-inspector/` 固定官方 Inspector `2.7.0` 并生成 npm 锁文件；本地接受正式版 Node >=22.19.0，CI 固定 22.19.0；验证本地 CLI 的 JSON 输出、Header、参数和退出码，记录实际版本，不能把提案中的候选版本当作已验收。
- [x] 1.2 将安装与测试运行分离，实现预装依赖及版本检查；确认开发依赖被 Git/镜像构建正确忽略，运行阶段不联网安装、不读取用户 MCP/OAuth 配置、不进入生产镜像。

## 2. 测试夹具与真实 HTTP 生命周期

- [x] 2.1 记录现有 `test_tool_mcp.py` 的收集数与基线结果，将新旧测试确实需要共用的应用、Job claim、资源发布和 Header 准备抽到 `backend/tests/support/tool_mcp.py`，保留旧测试原有行为和断言。
- [x] 2.2 为 Inspector 显式创建 `allow_direct_jobs=False` 的严格授权夹具，使用隔离数据库、Published Resource、冻结工具快照及带调用计数的合成 Schema 替身；不得跳过真实授权与审计。
- [x] 2.3 使用原 `create_app` 和 uvicorn 在预绑定回环随机端口启动真实服务，显式配置测试 allowed_hosts，验证 lifespan、就绪、数据库跨线程访问和用例间隔离。
- [x] 2.4 实现 `backend/tests/support/mcp_inspector.py` 的轻量 CLI 调用辅助函数：参数数组、完整 JSON 参数、独立状态目录、分离 stdout/stderr、连接/总超时、结果分类以及失败或取消后的进程和资源清理。

## 3. Inspector 代表性用例

- [x] 3.1 新建 `backend/tests/test_mcp_inspector_smoke.py` 并唯一登记到 `integration`，验证连接以及工具名称集合、inputSchema hash 与本 Job 快照和 Manifest 的精确一致性。
- [x] 3.2 验证 `get_schema_directory` 的已知合成表列结果、资源实际调用和两个 `_meta` 关联标识，核对 Tool Call 与 MCP 审计；覆盖连续同名调用不串联。
- [x] 3.3 覆盖非法参数和快照外工具调用，核对预期拒绝类别、可取得的项目错误码及资源零调用，明确区分客户端提前拒绝与服务端拒绝。
- [x] 3.4 覆盖缺少调用执行 Header 的服务端 `tool_mcp_context_missing`，以及固定假 Authorization 的拒绝；不得将不可达、超时或未知 CLI 错误当作拒绝通过。

## 4. 本地入口、CI 与使用说明

- [x] 4.1 增加 `make test-mcp-inspector` 和显式启用开关；普通套件未启用时显示清楚的跳过原因，专用入口对缺依赖、零用例、全部跳过、必需场景遗漏及失败返回非零。
- [x] 4.2 在现有 CI 中新增固定 Node/Python/npm 依赖的 Inspector job，在工作流已覆盖的 PR/push 执行；纳入 `runtime-images` 的依赖和成功条件，保留旧门禁，不设置 continue-on-error。
- [x] 4.3 编写 `docs/development/mcp-inspector.md`，说明安装和运行命令、排障、添加工具用例的方法、客户端/服务端拒绝区别及与旧测试的职责；不要求每个工具实现适配器。

## 5. 本地验证与收益记录

- [x] 5.1 完成本地完整 Inspector 套件实际运行，记录版本、场景清单、通过数、跳过数、耗时和真实 HTTP 路径证据；确认未访问真实资源或业务服务。
- [x] 5.2 在隔离测试中证明缺依赖、版本不符、连接失败、错误预期及超时会令专用入口失败，验证取消/失败后无遗留进程、端口、临时状态或数据库；不能只测试成功路径。
- [x] 5.3 运行夹具调整影响到的旧 HTTP/业务测试、测试分层治理检查及现有 SDK/MCP 合同测试，比较原用例与断言覆盖，解释收集数变化，不删除旧覆盖。已运行 55 项：54 通过、1 处已有 Compose tmpfs 断言失败；详见 evidence，不能视为旧门禁全绿。
- [x] 5.4 对修改文件执行适用的静态与格式检查，执行本 change 的 strict OpenSpec 校验、文档链接检查和 `git diff --check`，验证改动局限在开发测试范围。
- [x] 5.5 在本 change 的 `evidence.md` 记录新旧测试覆盖对照与测得耗时，明确独立客户端新增证据和剩余缺口；不宣称未经测量的准确率提升。

## 6. CI 验收与真实环境边界

- [ ] 6.1 取得 Linux CI 上 Inspector job 及受影响原门禁的真实运行结果，核对失败时镜像门禁不会放行；没有实际 CI 运行证据时保持本项未完成，不能用工作流文件存在或本地通过代替。
- [x] 6.2 在验收说明中逐项标注本期未覆盖的发布镜像、生产网络、真实数据库、ONES/钉钉/File MCP 和完整 Agent 链路；说明远端 required-check 设置是否核验。本项完成只表示边界已记录，不表示外部验收通过。

后续扩展到其他 MCP、真实环境或迁移删除旧用例，不属于本次任务。归档时任何未完成验证必须保留原状态。
