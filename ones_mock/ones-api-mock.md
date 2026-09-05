# ONES API Mock

独立开发服务，目录自包含于 `ones_mock/`，不连接真实 ONES。
接口配置全部放在 `mock.yaml`。

## 启动

在仓库根目录或本目录执行：

```bash
cd ones_mock
docker compose -f docker-compose.ones-mock.yml up --build -d
docker compose -f docker-compose.ones-mock.yml ps
```

独立启动后，宿主机地址为 `http://127.0.0.1:19121`。主 Compose 不再内置
Mock；其中的 API 和 `ones-mcp` 容器通过
`http://host.docker.internal:19121` 访问该独立服务。

## Mock 用户（见 mock.yaml）

```text
用户1
  email: mock.user@example.test
  password: ones-mock-password-not-a-secret
  uuid: MOCK-ONES-USER-001
  token: MOCK-ONES-TOKEN-NOT-A-SECRET

用户2
  email: mock.owner@example.test
  password: ones-mock-owner-password-not-a-secret
  uuid: MOCK-ONES-USER-002
  token: MOCK-ONES-TOKEN-OWNER-NOT-A-SECRET

team uuid: MOCK-ONES-TEAM-001
project scope uuid: MOCK-ONES-PROJECT-SCOPE-001
invalid response email: invalid.response@example.test
```

仅用于本地 Mock，勿替换成真实密码/Token 后提交。改用户或工作项时编辑
`mock.yaml`，然后 `docker compose -f docker-compose.ones-mock.yml restart`。

## 登录

```bash
curl -sS http://127.0.0.1:19121/project/api/project/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"mock.user@example.test","password":"ones-mock-password-not-a-secret"}'

curl -sS http://127.0.0.1:19121/project/api/project/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"mock.owner@example.test","password":"ones-mock-owner-password-not-a-secret"}'
```

响应中的 `user.uuid`、`user.token`、`teams[0].uuid` 分别用于
`Ones-User-Id`、`Ones-Auth-Token` 和当前默认 Team。示例全部是仓库固定假凭据，
不得替换或提交真实 ONES Secret。

## 主系统身份绑定

```env
ONES_IDENTITY_INSTANCE_CODE=default
ONES_IDENTITY_DISPLAY_NAME=ONES
ONES_IDENTITY_BASE_URL=http://host.docker.internal:19121
ONES_IDENTITY_ALLOWED_HOSTS=host.docker.internal
ONES_IDENTITY_TIMEOUT_SECONDS=5
ONES_IDENTITY_MAX_RESPONSE_BYTES=65536
ONES_IDENTITY_ALLOW_INSECURE_LOCAL=true
```

## 查询需求 / 任务 / 缺陷

`ones-mcp` 使用与真实 ONES 一致的 Team 级固定治理端点：

```text
POST /project/api/project/team/{team_uuid}/items/graphql?t=group-task-data
```

请求体固定为 GraphQL `query` 与 variables；关键词编译为 `filterGroup.name_match`，
稳定类型编译为 `filterGroup.issueType_in`。身份、Team、URL、Header 和 query 均不能由
Tool Input 指定。

以下 keyword 是稳定负向控制：

```text
__401__          每次查询返回 401，用于验证最多刷新一次
__403__          Team 权限拒绝
__429__          限流
__500__          Provider 5xx
__redirect__     重定向（客户端必须拒绝跟随）
__bad_json__     非法 JSON
__oversize__     超大响应
__missing_field__ 缺少必填业务字段
```

`mock.yaml` 中的 `control_passwords.subject_changed` 与 `team_missing` 用于刷新登录时
稳定触发 subject 变化和默认 Team 消失。

详细任务列表与兼容搜索共用同一个 Team 级端点：

```text
POST /project/api/project/team/{team_uuid}/items/graphql?t=group-task-data
```

支持 `issueType_in`、`name_match`、`createTime_range` 和 `pagination.limit`。类型 UUID：

```text
需求: WE3uoYoq
任务: Rbk6XNBr
缺陷: B4TV9bu5
```

```bash
curl -sS 'http://127.0.0.1:19121/project/api/project/team/MOCK-ONES-TEAM-001/items/graphql?t=group-task-data' \
  -H 'Content-Type: application/json' \
  -H 'Ones-User-Id: MOCK-ONES-USER-001' \
  -H 'Ones-Auth-Token: MOCK-ONES-TOKEN-NOT-A-SECRET' \
  -d '{
    "query":"query MockTaskQuery { buckets { tasks { number name } } }",
    "variables":{
      "filterGroup":[{"issueType_in":["B4TV9bu5"],"name_match":"status"}],
      "pagination":{"limit":500,"preciseCount":false}
    }
  }'
```

## 当前边界

Mock 查询、401 刷新和审计通过只证明仓库内契约闭环，不代表真实 ONES GraphQL
兼容性或生产 E2E 已验收。
