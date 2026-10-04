# 本地实施与验证记录

核对日期：2026-10-04。范围由用户确认：质量检查与 CI 门禁、已确认文档偏差、管理页面路由拆包。

## 实施结果

- 修复附件 Repository 的既有格式问题，以及 ONES 时间线 `action` / `ext` 的类型收窄；不使用类型忽略，合法业务投影由既有合同回归覆盖。
- `frontend-check` 使用已有 npm 锁文件；运行镜像 job 显式依赖后端静态检查和管理 Web 检查成功，保留 PR 可以跳过完整后端回归的既有规则。
- 19 个页面组件改为延迟导入；受保护页面在 capability 通过后才加载。中文加载状态、个人身份路由和既有加载失败恢复入口均有回归。
- 同步 platform-operations、builtin-tool-resource、governed-api-capability 三个 canonical 领域，修正当前知识能力、ONES 工作项收集上限、构建入口及部署说明。迁移目录核对为 `100..146`，操作手册仍以目标 artifact 的 catalog 为准。
- 保留本轮开始前 README 中用户增加的同步绑定说明与单独启动命令；未更新依赖锁文件，未新增 migration。

## 本地检查

| 检查 | 结果与范围 |
| --- | --- |
| `make lint format-check typecheck` | Ruff 通过；888 个 Python 文件符合格式；mypy 检查 618 个源码文件无错误 |
| 相关后端 pytest | 138 passed，覆盖 ONES 基础查询、自动收集、测试资产收集、保留文件候选和钉钉附件命名 |
| 前端锁文件安装 | `npm ci --no-audit --no-fund` 成功，package-lock.json 无变更 |
| 前端 lint / typecheck / test / build | 最终完整序列通过；17 个测试文件、184 项测试通过；锁定 Vite 8.1.5 构建成功 |
| OpenSpec | `openspec validate --all --strict --no-interactive`：19 项通过，0 项失败 |
| 当前文档本地链接 | 60 份当前说明、canonical 导航/规格及本 change 文档，0 个无效本地目标；不读取 archive 或无关 active change 的内容 |
| CI job 依赖 | YAML 中 9 个 job 的依赖存在且无环；镜像条件要求 backend-static 与 admin-web 成功 |
| Compose 示例配置 | 基础 Compose 和 Knowledge / MCP / sync 扩展均通过 `config --quiet`，显式使用 `.env.example` |
| 差异格式 | `git diff --check` 通过 |

相关后端回归文件：

```text
backend/tests/test_ones_basic_query_interfaces.py
backend/tests/test_ones_auto_collection.py
backend/tests/test_ones_testcase_collection.py
backend/tests/test_retained_file_candidate_repository.py
backend/tests/test_dingtalk_attachment_names.py
```

前端最终检查序列为 `npm run lint`、`npm run typecheck`、`npm test`、`npm run build`，失败即停止。初次检查发现热更新模块导出限制和首页异步断言问题，已分别通过独立组件导出文件、等待页面内容修复；最终结果以上表为准。

## 构建产物比较

基线采用 HEAD 的原路由文件，在临时目录中复用本轮安装的同一份锁定依赖和 Node/Vite 版本构建。当前构建来自本轮工作区；没有改写现场路由或修改锁文件。

初始 JS 统计 HTML 的入口脚本和 modulepreload 脚本之和；gzip 采用相同 Python gzip 参数。它衡量构建输出，不代表生产网络、缓存或页面交互时延。

| 指标 | 原路由 | 本轮路由 | 降幅 |
| --- | ---: | ---: | ---: |
| 入口 JS 字节 | 1,126,027 | 508,644 | 54.83% |
| 入口 gzip 字节 | 324,793 | 156,453 | 51.83% |
| 初始 JS 总字节 | 1,126,027 | 646,923 | 42.55% |
| 初始 JS gzip 总字节 | 324,793 | 204,421 | 37.06% |
| HTML 初始 JS 文件数 | 1 | 6 | — |

页面块包括总览约 3.22 kB、运行记录约 51.30 kB、资源页约 99.34 kB、钉钉候选约 7.33 kB，进入对应页面后按需加载。构建仍有入口块超过 500 kB 的提示，后续优化应按实际加载和性能证据另行定范围；本轮不拆大业务模块。

## 本地真实浏览器验证

使用 Playwright CLI 启动独立临时 Chrome 会话，访问本轮生产构建产物。服务器只监听本机回环地址，认证、capability 与业务应用 API 均返回合成数据，只记录请求路径，不接触真实后端或个人浏览器会话。

- 首页首次加载保留平台壳，出现“正在加载管理页面…”，随后显示总览。
- 点击“打开业务应用”后到达 `/applications`，加载业务应用块并显示合成空列表。
- 请求记录确认首页与业务应用导航未下载资源页、运行记录页模块。
- 直接访问 `/platform/resources` 显示“无权访问此页面”，未下载资源页模块。
- 浏览器控制台 0 errors、0 warnings；验证后关闭本次浏览器并停止合成服务器。

模块导入失败的刷新与返回工作台行为、权限校验期间不加载模块，以及个人身份路由由新增路由回归覆盖。浏览器验证不证明真实认证、Provider 或生产数据合同已验收。

## 已保留的边界

本轮不改变 `max_tool_calls=0` 的现有归一化，不扩大最近七个创建日的同步窗口，不拆分大业务模块，不提交、推送、归档或部署。未执行真实 ONES、模型、生产数据库升级或发布资源验收；其它 active change 的真实环境任务不补勾。

前端测试仍出现既有 AgentProfile 测试中的 Base UI 按钮语义提示；测试通过不等于该提示已修复。文档本次对齐只覆盖已确认的偏差，不声明整个项目所有辅助文档完全匹配。
