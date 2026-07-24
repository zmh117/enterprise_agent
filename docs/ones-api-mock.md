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
invalid response email: invalid.response@example.test
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

## 用于系统用户身份绑定

主 Compose 中的 API 可以使用以下本地配置连接该 Mock：

```env
ONES_IDENTITY_INSTANCE_CODE=default
ONES_IDENTITY_DISPLAY_NAME=ONES
ONES_IDENTITY_BASE_URL=http://host.docker.internal:19121
ONES_IDENTITY_ALLOWED_HOSTS=host.docker.internal
ONES_IDENTITY_TIMEOUT_SECONDS=5
ONES_IDENTITY_MAX_RESPONSE_BYTES=65536
ONES_IDENTITY_ALLOW_INSECURE_LOCAL=true
```

管理员在用户详情页输入 Mock 邮箱和一次性密码后，服务端只保存
`user.uuid`、`user.name`、团队 UUID 和验证时间。登录响应中的 Token、邮箱、密码和
原始响应不会进入身份记录、审计或前端缓存。

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

该 Mock 同时保留工作项接口报文，供未来独立变更使用；当前 Agent 平台只调用登录端点
完成用户身份绑定，不调用需求、任务、缺陷接口，也不创建 ONES API Capability。
