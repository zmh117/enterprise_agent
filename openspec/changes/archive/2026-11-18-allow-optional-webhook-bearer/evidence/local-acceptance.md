# 本地验证记录

日期：2026-11-06。

## 已确认

- 后端相关回归 35 项通过：可选鉴权、Trigger 生命周期、管理/公共 API、报文边界、入口派发和 outbox 恢复。
- 新增合成 API 用例覆盖：空引用保存并规范化、免鉴权发布、无 Header 接收、去重、无活动应用路由拒绝、草稿不影响原 Bearer 发布，以及重新发布 Bearer 后拒绝无 Header 请求。矛盾模式与非空引用组合拒绝保存。
- Bearer 的缺失、弱值和解析失败不会隐式降级。旧强度、唯一性、错误 Header 测试继续通过。
- 前端配置页 7 项测试通过，包括可选凭据保存、curl 当前 public ID、请求头切换、复制及 Grafana 报文。
- Ruff、ESLint、前端 TypeScript/生产构建、git diff --check 和 OpenSpec strict validate 通过。构建保留既有 chunk 大小提示。
- 本地 api-server/admin-web 镜像重建并更新。`/api/ready` 返回 HTTP 200、status ready；管理端返回 HTTP 200。
- 运行中 API 容器的配置模型与鉴权函数接受显式 none；部署的前端资源包含可选凭据、HTTP 示例、复制按钮和后端接收地址。
- 用户解锁后完成 Chrome 实际页面核验：凭据标记可选；留空展示不含 Authorization 的 curl，URL 包含当前 public ID；填入合成凭据引用后自动增加 Bearer 占位符，清空后恢复免鉴权示例；点击复制显示“调用示例已复制”。截图确认代码、说明与按钮排版可读。

## 发布与入口状态后续修复

- 重复发布当前修订曾违反 publication 唯一约束而返回 500；发布流程通过定义行锁串行化，同一当前修订返回已有 Publication，旧修订重复发布返回明确冲突提示。前端已发布修订禁用发布按钮，并显示已发布状态。
- 本地 PostgreSQL 上并发重试当前已发布修订 4 次，均返回相同 Publication，定义 revision 与 publication 数量不变；写入守卫确认未重新创建发布、校验结果或角色授权。
- 渠道运行状态曾无条件检查 Bearer，导致显式免鉴权入口被误标记为配置异常、无法成为应用候选入口。状态检查与请求鉴权现在共用凭据解析规则：显式 none 无需凭据，失效 Bearer 仍拒绝，账号与连接器问题返回各自原因。
- 后续回归：后端 43 项、前端 7 项通过；Ruff、ESLint、TypeScript/生产构建和 git diff --check 通过。
- 再次重建并更新本地 api-server/admin-web。运行中容器的只读检查确认 `test-webhook` 已启用、runtime status 为 READY、无 last_error，且进入应用 Webhook 候选列表；`/api/ready` 返回 HTTP 200、status ready。
- 最后一次浏览器核验在刷新后遇到电脑工具连接超时，未确认最终页面显示；上述 READY 与候选入口结论来自运行中服务的实际查询。没有通过真实 Webhook 触发 Agent 或发送投递。

## 验证边界

- 浏览器检查曾被系统锁屏阻断，用户解锁后已补齐。操作在独立核验标签页进行，用户原页面未保存内容保持原样；合成凭据引用仅用于页面展示测试，已清空且未保存。
- 仅合成测试触发测试容器内事件；没有调用真实 Webhook、Agent 模型、钉钉投递或 HTTP 回调，没有保存/发布用户现有入口配置。
- 本次更新本地服务，不构成远程环境或真实业务链路验收。
