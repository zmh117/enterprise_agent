## 1. 受管查询条件资源

- [x] 1.1 实现确定性同步脚本，从个人抓取 YAML 提取 Team 元数据、状态与单选/多选自定义字段，并排除人员、项目、迭代和原始接口数据
- [x] 1.2 生成最小运行快照，加入 schema/version/digest，并实现加载时的结构、大小、UUID、唯一性和 Team 校验
- [x] 1.3 增加同步器与资源安全测试，证明相同输入字节稳定且运行代码不读取 `ones_mock/ones/`

## 2. MCP共享契约与条件解析

- [x] 2.1 在共享 ONES Tool 契约和平台 Manifest 中注册 `ones_resolve_query_conditions` 与 `ones_get_users_by_uuids`
- [x] 2.2 新增 `ones_query_work_items_with_custom_options` 的有界输入契约和确定性参数校验，并保持 `ones_query_work_items` schema hash 不变
- [x] 2.3 实现按状态/自定义选项名称匹配的 Team 受限条件解析服务，使用 RESOURCE 审计且不触发 Provider Credential refresh
- [x] 2.4 增加条件解析的精确匹配、包含匹配、同名候选、Team 不匹配、非法类型和有界结果测试

## 3. GraphQL自定义选项筛选

- [x] 3.1 在 Principal 解析后校验自定义字段与选项归属，并把合法输入转换为 `_<field_uuid>_in`
- [x] 3.2 保持工作项 GraphQL 文档集中固定，增加变量构造、未知字段、跨字段选项、重复字段和上限测试
- [x] 3.3 扩展合成 ONES Mock，按自定义选项条件过滤并返回有界工作项结果

## 4. 固定REST用户反查

- [x] 4.1 实现并注册 `ones_get_users_by_uuids`，复用固定 Team users POST operation
- [x] 4.2 只投影用户 UUID/姓名，并覆盖重复、空列表、超限、未知用户、401 refresh、403 与额外个人字段不泄露测试

## 5. Agent查询Skill

- [x] 5.1 新增简短 `ones-query` Skill，定义实时发现、受管条件解析、工具选择、歧义停止和用户统计口径边界
- [x] 5.2 注册 Skill 并验证其可被 Agent Profile 选择、进入运行时镜像且只通过新的 Publication/Job snapshot 生效
- [x] 5.3 验证 Skill 不包含受管字典中的真实 Team、项目、人员、状态、字段或选项 UUID

## 6. 文档与验证

- [x] 6.1 更新 ONES MCP README，明确 GraphQL、REST、本地受管资源三类固定操作及字典更新流程
- [x] 6.2 运行 ONES 契约、Mock、Runtime、架构定向测试以及静态检查、`git diff --check`、Compose 配置和严格 OpenSpec 校验
- [x] 6.3 记录实现验证证据，并区分本地 Confirmed-current 与仍需授权真实 ONES 环境验证的项目
