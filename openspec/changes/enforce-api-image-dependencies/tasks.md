## 1. 实现

- [x] 1.1 声明直接依赖，保证后端镜像安装附加依赖时使用平台兼容范围，增加 API 镜像离线工厂验收。
- [x] 1.2 修正镜像 CI 服务名，增加覆盖依赖版本、草稿列表约束及 Compose 构建入口的回归检查。

## 2. 验证

- [x] 2.1 验证不兼容依赖被拒绝，实构 API 镜像，核对 Compose 构建目标并运行相关测试与 OpenSpec 严格校验。
- [x] 2.2 按 Dockerfile 继承关系验证 Runtime 与 Worker 的应用文件白名单。两者均须能导入入口，Runtime 须维持业务模块隔离和只读工作副本访问边界。

## 验证记录

- 在本机以 Linux AMD64 为目标实构 API、文件服务和 Python Runtime 依赖阶段。API 离线生成含草稿路由的 OpenAPI，API 和文件服务的 `pip check` 通过。
- 实际 pip 解析根依赖且附加 `pydantic<2` 约束时报告 `ResolutionImpossible`。草稿模型接受 20 个触发器，拒绝 21 个。已解析 CI 对应的 Compose 构建目标。
- Runtime 与 Worker 的白名单测试沿构建阶段继承应用文件，按 Dockerfile 的文件目标路径复制浏览器协议。Runtime 的知识基础设施导入仅允许只读检出的 `code_source` 和 `code_checkout_identity`。
- 十个相关测试文件共 182 项通过。Linux AMD64 的 `python-agent-runtime` 与 `agent-worker` 两个最终镜像目标均已实构通过。
