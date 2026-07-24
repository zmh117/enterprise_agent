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

默认地址：`http://127.0.0.1:19121`。主机端口可用 `ONES_MOCK_PORT` 覆盖。
其他容器访问（Docker Desktop）可用 `http://host.docker.internal:19121`。

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
`Ones-User-Id`、`Ones-Auth-Token` 和 URL 中的 `{team_uuid}`。

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

```text
POST /project/api/project/team/{team_uuid}/items/graphql?t=group-task-data
```

支持 `issueType_in`、`search.keyword`、`pagination.limit`。类型 UUID：

```text
需求: MOCK-ISSUE-TYPE-DEMAND
任务: MOCK-ISSUE-TYPE-TASK
缺陷: MOCK-ISSUE-TYPE-DEFECT
```

```bash
curl -sS 'http://127.0.0.1:19121/project/api/project/team/MOCK-ONES-TEAM-001/items/graphql?t=group-task-data' \
  -H 'Content-Type: application/json' \
  -H 'Ones-User-Id: MOCK-ONES-USER-001' \
  -H 'Ones-Auth-Token: MOCK-ONES-TOKEN-NOT-A-SECRET' \
  -d '{
    "query":"query MockTaskQuery { buckets { tasks { number name } } }",
    "variables":{
      "filterGroup":[{"issueType_in":["MOCK-ISSUE-TYPE-DEFECT"]}],
      "search":{"keyword":"#900103","aliases":[]},
      "pagination":{"limit":500,"preciseCount":false}
    }
  }'
```

## 当前边界

当前 Agent 平台主要调用登录端点做用户身份绑定；工作项接口供后续 Capability 联调。
