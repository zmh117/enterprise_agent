## Why

后端已经具备本地登录、服务端 Session、CSRF、统一内部用户、RBAC 和通用外部身份表，但当前管理 Web 仍是无登录、无真实数据的静态原型，用户与钉钉/ONES账号的关联也没有可操作的管理界面和可信验证流程。现在需要把管理端真正接入认证与外部身份治理，使同一内部人员能够安全关联多个外部系统主体，并为后续 Business Application 和 API Capability 提供可信 actor。

## What Changes

- 将管理 Web 接入现有 `/api/auth/login`、`/me`、`/logout`、修改密码和Session管理接口，增加登录页、认证路由、Session恢复、权限导航和安全退出。
- 建立统一前端 API Client、CSRF 和错误边界；浏览器只使用 HttpOnly Session Cookie，不在Local Storage或前端状态中保存长期Token。
- 将“用户与外部身份”从静态原型升级为真实用户列表、用户详情和身份管理工作区。
- 在现有通用 `user_external_identity` 基础上增加可信外部身份连接、Provider能力、验证状态、验证方法、团队/租户上下文和冲突治理模型。
- 第一版支持钉钉和ONES两种Provider，并保证一个内部用户可以关联多个不同Provider、租户或系统实例的外部身份。
- 复用现有钉钉Connector完成管理员审核绑定；继续使用`provider + tenant/connection + external_subject_id`唯一约束，不按姓名、昵称、邮箱或手机号自动关联。
- 增加ONES一次性身份验证：后端通过受信ONES连接调用登录接口，从响应提取用户UUID、展示信息和团队UUID；密码和返回Token只用于当前验证请求，MUST NOT写入身份表、日志、审计或浏览器持久化存储。
- 支持管理员手工创建pending关联、自助或代操作验证、启用、停用、解绑和冲突处理；未经验证或发生冲突的身份不能作为可信业务主体。
- 明确“身份关联不等于授权”：内部RBAC、业务应用授权、API Capability授权、API平台数据权限及ONES原生权限仍分别生效。
- 保持现有钉钉入口fail-closed语义；ONES身份本变更只用于身份映射和管理，不接入需求、任务、缺陷查询，也不保存可供业务接口调用的ONES Token。
- 不在本变更中实现企业SSO、钉钉扫码登录、目录全量同步、按邮箱自动匹配、API Capability调用、长期外部凭据Vault或Business Application运行时路由。

## Capabilities

### New Capabilities

- `admin-web-session-integration`: 定义管理Web登录、Session恢复、认证路由、CSRF、权限导航、修改密码、Session撤销和安全退出。
- `multi-provider-external-identity-management`: 定义可信外部身份连接、钉钉/ONES及未来Provider的通用绑定、状态、唯一性、冲突治理和真实管理工作区。
- `ones-identity-verification`: 定义通过受信ONES登录接口进行一次性身份验证、响应字段提取、团队上下文保存和密码/Token非持久化边界。

### Modified Capabilities

无。现有统一身份、Web Session、RBAC和钉钉入口行为继续有效；本变更连接真实管理Web并增加多Provider治理与ONES验证能力，不改变现有Agent数据面规格。

## Impact

- 数据库：新增外部身份连接和验证记录，并扩展外部身份的connection、verification status/method、团队上下文和冲突治理字段；保留现有唯一约束和历史绑定。
- 后端：扩展Identity领域、Repository、服务和管理API，增加Provider Adapter端口与ONES验证适配器；复用现有AuthService、AuthorizationEvaluator、AuditService和ConnectorRegistry。
- 前端：新增Router、TanStack Query、统一API Client、登录/会话页面、真实用户与外部身份工作区；替换对应静态fixture但保留其余控制面原型。
- ONES Mock：开发和测试使用独立`docker-compose.ones-mock.yml`中的登录接口；生产只允许配置的受信HTTPS连接，不接受请求级任意URL。
- 安全：外部密码、登录Token、Session Cookie、CSRF值和真实Secret不得进入数据库身份记录、前端持久化、日志或审计；所有状态变更执行RBAC、CSRF、乐观并发和安全审计。
- 后续变更：建议先实施本变更，再实施真实Business Application工作区，使其复用已经建立的前端认证、路由和API基础。
