## 1. 共享契约与游标

> 第 1 至 5 节保留第一阶段完成事实；第二阶段以第 6 节及最新 delta 为准，不能沿用第一阶段部署/测试作为本次验收。

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

## 6. 自动翻页、临时结果文件与失败诊断

- [x] 6.1 按官方 bucket 分页修复九个列表并移除模型 cursor，默认/最多 1000，Provider 每批最多 200，覆盖直接列表与稳定性/预算失败
- [x] 6.2 通过受控 Runtime bridge 将列表结果写入 Job 只读沙盒，复用原子预算、派生只读工具、终态与异常恢复清理
- [x] 6.3 Tool Call 时间线显示安全 error/error_code，验证失败审计与对象/JSON 摘要兼容
- [x] 6.4 更新合成 Mock、共享契约、自动翻页/沙盒/权限/错误测试，完成静态检查、前端验证、Compose 和严格 OpenSpec；全 backend mypy 的既有身份模块错误单独记录于 evidence-auto-collection.md
- [x] 6.5 重建受影响本地组件及 ONES Mock，核对部署构建/健康和容器内1000条合成分页、结果文件清理
- [ ] 6.6 对明确选定的 Agent/Application 重新发布，以新 Job 完成真实 ONES 查询、文件读取和失败时间线验收；不能以 Mock 或容器健康替代

## 7. 现场接口兼容与 Mock 下线

- [x] 7.1 对照 ones 目录清点已注册查询/详情/写入 Operation 的请求投影与安全响应结构，区分完整样例和节选
- [x] 7.2 修复迭代进度定点比例、接口明确时间单位和其他已证实的解析差异，统一用例列表页完整性检查
- [x] 7.3 为 GraphQL 顶层错误及字段校验提供安全定位信息，验证 Tool Call 审计与时间线可见且不泄露上游值
- [x] 7.4 按用户最终确认只删除 Mock 服务，保留接口修复、现场文档和原测试基础设施；环境示例、连接配置和 ones-mcp 启动/健康逻辑恢复原样
- [x] 7.5 补齐结构/单位/安全回归，执行相关测试、静态检查、Compose/OpenSpec 校验并部署本地受影响组件（最终范围 327 测试通过，容器原配置与修复均已核对；真实 ONES 仍待验收）

## 8. Runtime 提示词版本回归修复

- [x] 8.1 Worker 默认上下文与 Runtime 观测共用提示词版本定义，保留严格版本/快照/构建身份校验
- [x] 8.2 协议拒绝生成有界中文原因与安全字段差异，经现有失败步骤和执行摘要展示；不保存被拒绝事件或原始载荷
- [x] 8.3 覆盖默认上下文跨组件事件流、版本/快照/身份拒绝、敏感值不外泄、失败持久化及运行记录展示
- [x] 8.4 完成本地测试、静态及构建校验，部署受影响本地组件并验证同版本；不重跑原 Job、不连接真实 ONES、不改环境配置（224 后端、24 前端测试通过，见 evidence-runtime-prompt-version.md）

## 9. 空关联与工具时间线摘要修复

- [x] 9.1 统一可选迭代/人员空关联规范化，覆盖分页第51条与详情/关联工作项，保留必填及半空对象校验
- [x] 9.2 MCP 新写入及管理/Debug 读取使用有界结构化响应摘要，先投影再限长，兼容历史包装且不返回业务正文
- [x] 9.3 文件工具显示安全操作结果与可用大小元数据，区分沙盒写入、输出选择、提交意图与正式提交
- [x] 9.4 完成后端/前端/安全回归、静态/构建/规范校验及本地部署，不连接真实 ONES 或重跑历史 Job（313 后端、34 前端测试通过，见 evidence-empty-relations-summary.md）
