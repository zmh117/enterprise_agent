## 1. 共享契约与游标

- [x] 1.1 为八个 GraphQL 列表 Tool 增加可选 cursor 输入和统一分页输出字段，更新描述与 schema hash 断言
- [x] 1.2 实现通用 ONES GraphQL 列表游标，覆盖 provider 与 snapshot-offset 两种模式、执行上下文/查询绑定和 500 条累计上限

## 2. Provider Operation 与规范化

- [x] 2.1 将项目、工作项、测试库、测试计划和测试用例 Operation 的 pagination.limit/after 改为服务端变量注入并按累计位置解释 pageInfo
- [x] 2.2 为工作项类型和测试模块直接列表实现有界 offset 切片、完整有序 UUID 集合摘要和漂移检测所需内部元数据
- [x] 2.3 保持固定 GraphQL 文档、各 Tool 单页上限、白名单投影、个人 Principal、401 单次刷新和审计安全边界

## 3. Tool 服务分页编排

- [x] 3.1 实现分页 GraphQL 查询服务基类，统一解码 cursor、限制剩余额度、清除内部 continuation 字段并签发公开 next_cursor
- [x] 3.2 将项目、类型、标准/自定义工作项、测试库、测试模块、测试计划和测试用例服务接入分页基类
- [x] 3.3 对缺失/不前进 Provider cursor、空续页、snapshot 集合漂移、500 条仍有后续等状态失败关闭或返回明确上限

## 4. Mock 与自动化验证

- [x] 4.1 扩展 ONES Mock，精确校验所有 bucket Operation 的 pagination.limit/after 并支持多页响应
- [x] 4.2 覆盖八个 Tool 的首查、续页、终页、非整除 500 上限和单页 100/200 边界
- [x] 4.3 覆盖 cursor 篡改、跨 Tool、跨 Job、跨查询、跨授权、跨身份、跨 Team 与 snapshot 集合漂移，证明应拒绝的场景不访问或不返回 Provider 数据
- [x] 4.4 更新 Manifest/schema drift、固定 GraphQL document、审计和既有 ONES 查询回归

## 5. 验证、部署与真实验收

- [x] 5.1 运行 ONES MCP、Mock、Principal、Runtime、共享 Manifest 定向测试、静态检查、Compose 配置、git diff 检查和严格 OpenSpec 校验
- [x] 5.2 重建并替换本地受影响服务，核对健康状态、容器内关键文件与新 Tool schema
- [ ] 5.3 重新发布 Agent/Application 后，对真实 ONES 的 provider-cursor 与 snapshot-offset 代表 Tool 完成只读首/续/终页验收；无授权或无足量数据时明确保留待验收
