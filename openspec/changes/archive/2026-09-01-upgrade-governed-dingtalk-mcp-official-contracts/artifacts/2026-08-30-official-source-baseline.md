# 钉钉 MCP / OpenAPI 官方来源基线（2026-08-30）

## 来源优先级

1. Tool 功能名称、调用时机、目标类型和参数语义：官方 `open-dingtalk/dingtalk-mcp` 的 npm `latest` 包。
2. Provider method、path、请求和响应：审计时最新的阿里云官方钉钉 Go SDK；SDK 未覆盖时回查官方 MCP 包中仍公开的接口。
3. 平台治理：本项目代码 Manifest 与 canonical OpenSpec；治理限制必须与官方功能语义分开描述。

## 固定版本

| 来源 | 固定版本 | 完整性证据 |
|---|---|---|
| `dingtalk-mcp` npm | `1.1.21`（2026-08-30 的 `latest`） | dist shasum `57fbd6062e82ec4905044f5553b8b0ac6f559eff` |
| 官方 MCP 源码 | `https://github.com/open-dingtalk/dingtalk-mcp` | 与 npm 包内七个启用 profile YAML 交叉核对 |
| 官方 Go SDK | commit `6f1bd553359d8060ff7c6a38bcd4a93da4d13109`，提交时间 2026-08-19 | `https://github.com/alibabacloud-go/dingtalk` |

2026-08-31 复核：npm registry 的 `latest` 仍为 `1.1.21` 且 dist shasum 未变，官方 Go SDK 的远端 `HEAD` 仍为上述 commit。重新下载该 npm tarball 后，逐个读取七个启用 profile 的 YAML，并与本项目分类表机械比对：官方条目总数 52，七个 profile 均为 `missing=[]`、`extra=[]`。

基线不包含 Client ID、Client Secret、access token、Cookie、业务消息或真实用户资料。用户在会话中暴露过的 Secret 已视为失效材料，本 change 不使用也不保存该值。

## 关键差异结论

- 官方 MCP `1.1.21` 仍包含 v1 和 `oapi.dingtalk.com`；所以“npm latest”只能作为功能语义基线，不能证明每个端点都是最新版本。
- 官方 Go SDK 同时提供 `notable_1.0` 与 `notable_2.0`；官方 MCP `1.1.21` 对数据表、字段和记录固定使用 `notable_1.0 + operatorId`。路径版本号更高不证明操作者身份和资源可见范围语义等价。
- 2026-08-31 真实对照中，官方 MCP 可对 `新浪热搜` 完成列数据表、列字段、插入记录和回读；本系统使用 storage v2 搜索得到同一 `baseId` 后，notable v2 无 operator 的列数据表请求被钉钉拒绝。该结果推翻原“v1 可直接迁移 v2”结论，目标契约恢复为官方 MCP/SDK 共同支持的 v1 + operator；证据不包含记录正文或凭据。
- 官方机器人 profile 明确区分 `sendMessageToGroupByRobot` 与 `batchSendMessageToUsersByRobot`。群聊与个人批量单聊不能由含混的同名 Tool 描述替代。
- 机器人群发/个人批量发送成功响应中的 `processQueryKey` 表示发送请求已被钉钉受理，不等于最终送达；个人批量接口还会返回过滤、流控和无效收件人名单。工作通知的 `task_id` 同样只表示异步任务已提交，必须用发送进度/结果接口或钉钉事实判断最终结果。
- 官方 MCP `1.1.21` 的通讯录用户详情仍调用 legacy topapi，但最新 SDK 另有 `BatchGetUser`：`GET /v1.0/contact/users/batch/get` 可按 `userIdList` 查询 `userList/unauthorizedUserIdList`。本项目已用其执行单 userId 查询，并只投影 userId、unionId、姓名、工号等安全基础详情；不再把仅按 unionId 的 `GET /v1.0/contact/users/{unionId}` 当作候选替代。部门详情/成员和工作通知仍没有被证实存在等价新接口。
- 对 SDK 全库再次按 `Pathname`、department、work notification、corp conversation 和 send result 等关键词扫描：通用通讯录只有 `/v1.0/contact/departments/search`；其余新式 department 路径属于 `village`、`industry` 等专用业务域，不能替代企业通用通讯录。SDK 也未提供与 `asyncsend_v2/getsendprogress/getsendresult` 等价的通用工作通知新接口。
