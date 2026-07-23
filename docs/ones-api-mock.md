# ONES API Mock

这是供身份映射和后续 API Capability 联调使用的独立开发服务，不连接真实 ONES，
也不包含真实账号、Token、团队、项目或工作项数据。

## 启动

```bash
docker compose -f docker-compose.ones-mock.yml up --build -d
docker compose -f docker-compose.ones-mock.yml ps
```

默认地址为 `http://127.0.0.1:19121`。主机端口可通过 `ONES_MOCK_PORT` 修改。
另一个 Docker 容器需要访问时，可在 Docker Desktop 环境使用
`http://host.docker.internal:19121`。

默认 Mock 身份：

```text
email: mock.user@example.test
password: ones-mock-password-not-a-secret
user uuid: MOCK-ONES-USER-001
token: MOCK-ONES-TOKEN-NOT-A-SECRET
team uuid: MOCK-ONES-TEAM-001
project scope uuid: MOCK-ONES-PROJECT-SCOPE-001
```

这些值仅用于本地 Mock，不得替换成真实密码或 Token 后提交。需要覆盖时，在本地 Shell
或未提交的环境文件中设置 `ONES_MOCK_*` 环境变量。

## 登录

```bash
curl -sS http://127.0.0.1:19121/project/api/project/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"mock.user@example.test","password":"ones-mock-password-not-a-secret"}'
```

响应中的 `user.uuid`、`user.token` 和 `teams[0].uuid` 分别用于业务请求头
`Ones-User-Id`、`Ones-Auth-Token` 和业务 URL 的 `{team_uuid}`。

## 查询需求、任务和缺陷

接口路径和 ONES 保持一致：

```text
POST /project/api/project/team/{team_uuid}/items/graphql?t=group-task-data
```

Mock 支持：

- `variables.filterGroup[].issueType_in`：按需求、任务或缺陷类型 UUID 过滤；
- `variables.search.keyword`：按 `#number`、number 或名称过滤；
- `variables.pagination.limit`：限制返回条数，最大 1000。

固定工作项类型：

```text
需求: MOCK-ISSUE-TYPE-DEMAND
任务: MOCK-ISSUE-TYPE-TASK
缺陷: MOCK-ISSUE-TYPE-DEFECT
```

缺陷编号查询示例：

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

## 查询项目工作项类型

```text
POST /project/api/project/team/{team_uuid}/items/graphql?t=issueTypeScopes
```

`scope_equal` 使用 `MOCK-ONES-PROJECT-SCOPE-001`，`scopeType_equal` 使用 `1`。
返回需求、任务和缺陷三个项目级类型及各自的 `issueTypeScope.uuid`。

## 当前边界

当前只提供 ONES 外部接口 Mock。系统用户与 ONES 用户的身份绑定、凭据安全存储以及
需求/任务/缺陷的 API Capability 适配不在该 Mock 内实现，后续应分别接入身份域和
Capability Gateway，避免 Agent 直接持有 ONES 密码或自由构造底层请求。
