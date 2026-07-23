## 1. 配置模型与安全规则

- [x] 1.1 盘点 `backend/app/shared/config.py`、`runtime_config_loader.py`、Bootstrap 和各 Worker 对所有 `FEATURE_*` 的直接读取，形成旧键到新分类/领域策略的代码映射
- [x] 1.2 在共享配置领域中实现不可变的有效功能配置模型，包含最终值、来源、分类、弃用输入、是否需重启和诊断信息
- [x] 1.3 实现统一解析器及四个顶层开关的安全默认值，保证管理面总开关不会开启三个数据面安全闸门
- [x] 1.4 实现生产环境 test-only 校验，使测试身份请求头被启用时启动失败
- [x] 1.5 实现数据库策略不得越过部署安全闸门、数据库不可用时不扩大权限或外部调用的安全回退
- [x] 1.6 增加配置解析单元测试，覆盖四开关组合、来源优先级、数据库不可用、生产 test-only 和 API/Worker 一致性

## 2. 管理面原子启停与访问控制

- [x] 2.1 将管理 Web、管理 API、统一身份、Web Session、RBAC 和业务应用控制面统一派生自 `FEATURE_WEB_ADMIN`
- [x] 2.2 删除业务代码对 `FEATURE_UNIFIED_IDENTITY` 和 `FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE` 的独立判断，所有装配读取统一有效配置
- [x] 2.3 保证 `FEATURE_WEB_ADMIN=false` 时不注册管理入口，但不影响 Channel ingress 和已发布 Agent Runtime
- [x] 2.4 增加管理面集成测试，覆盖开启后的认证/RBAC保护、关闭后的路由不可用以及无认证降级不可达

## 3. 数据面闸门与领域策略

- [x] 3.1 将 `FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE` 和 `FEATURE_REAL_INTERNAL_TOOLS` 接入统一解析器，并保持 Worker/客户端注入的独立控制
- [x] 3.2 根据现有业务应用与 Agent Profile 模型选定连续会话和附件策略的唯一发布事实源，补充有版本、审计和回滚能力的字段或配置定义
- [x] 3.3 将连续会话和附件运行路径改为读取已发布策略，草稿修改不得改变当前运行
- [x] 3.4 将权限 shadow mode 迁移到受审计的 runtime policy 或专用迁移策略，并提供安全默认值和回滚 revision
- [x] 3.5 将 Webhook ingress 判断改为校验 Connector 状态、方向、已发布 Trigger Binding 和已发布业务应用版本
- [x] 3.6 增加领域策略与数据面集成测试，覆盖 deployment gate 阻断、草稿不生效、发布后生效、未发布 Webhook 不创建 job

## 4. 兼容迁移与诊断 API

- [x] 4.1 实现旧开关兼容适配器，识别七个旧键并输出去敏、包含迁移目标和移除版本的弃用告警
- [x] 4.2 实现新旧配置冲突检查：同义配置允许启动并告警，矛盾配置拒绝启动或发布
- [x] 4.3 实现只读迁移检查命令，列出旧键、目标分类、目标领域策略、冲突和待确认事项，不写数据库或发布资源
- [x] 4.4 实现从旧 Webhook/会话/附件/权限开关生成领域策略草稿的迁移服务，确保不会自动发布、改变路由或开启外部调用
- [x] 4.5 扩展受 RBAC 保护的平台配置 API，提供有效功能配置、来源、revision、弃用项、阻断原因和冲突的去敏快照
- [x] 4.6 扩展环境迁移指导 API，拒绝把 bootstrap-only、deployment safety gate 或生产 test-only 配置作为普通数据库运行配置越权编辑
- [x] 4.7 增加兼容与 API 测试，覆盖仅旧配置、新旧同义、新旧冲突、未授权诊断、Secret 去敏和迁移草稿不发布

## 5. 部署面与文档收敛

- [x] 5.1 更新 `docker-compose.yml` 的公共环境锚点和各服务环境面，只保留四个顶层功能开关并保留必要 bootstrap/network 配置
- [x] 5.2 更新 `.env.example` 和环境模板，为四个顶层开关给出安全默认值、职责说明和彼此独立关系
- [x] 5.3 更新 README、管理后台、业务应用、Webhook、连续会话和运行配置文档，删除要求部署人员组合旧开关的步骤
- [x] 5.4 在运维文档中写明兼容期截止版本、静态检查命令、冲突修复方式、迁移发布步骤和回滚路径
- [x] 5.5 更新现有 smoke 脚本和 Compose profile，禁止依赖已废弃开关直接启用细粒度能力

## 6. 端到端验证

- [x] 6.1 运行后端完整测试与 OpenSpec 严格校验，修复因配置边界调整产生的回归
- [x] 6.2 使用默认安全配置启动 Compose，验证管理面、已发布 Runtime、真实模型和真实工具均符合默认值且 readiness 正确
- [x] 6.3 开启 `FEATURE_WEB_ADMIN`，验证统一身份、Session、RBAC 和业务应用控制面同时可用，三个数据面闸门未被联动开启
- [x] 6.4 分别验证已发布 Runtime、真实模型和真实内部工具闸门可独立开启/关闭，数据库配置不能越过关闭闸门
- [x] 6.5 使用已发布 Connector/Trigger 和业务策略验证钉钉/Webhook、连续会话及附件行为，并确认未发布草稿不生效
- [x] 6.6 使用冲突旧配置和生产 test-only 配置执行启动失败 smoke，确认错误可定位且日志不泄露 Secret
- [x] 6.7 执行迁移与回滚演练，确认迁移只生成草稿、不改变现有路由，回滚后原 Agent/Channel 链路仍可运行
