# 验证记录（2026-11-05）

## 当前事实与边界

用户确认 v8 / v10 错误来自生产，并表示没有可提供的生产 SSH 连接信息。本次未访问生产
Job、请求正文或凭据，也未重建/重启任何服务。

本机只读 `docker exec` 查询共享模板常量：`enterprise_agent-agent-worker-1`、
`enterprise_agent-agent-worker-2`、`enterprise_agent-runtime-a`、`enterprise_agent-runtime-b`
当时均为 v10；checkout 当时为 v11。因此不能把本机版本当作该生产错误的根因证据。

代码确认：原被动健康探针核对协议、构建身份和依赖，不核对 Prompt；Runtime 新准入也无
版本前置检查，而 Worker 在 `tool_contract_observed` 事件才拒绝。冻结请求可独立于当前镜像
版本保留，因此生产仍需区分旧 Worker 与旧请求；本次没有作出二者之一已确认的结论。

## 本地回归

```bash
.venv/bin/pytest -q \
  backend/tests/test_runtime_http_client.py \
  backend/tests/test_python_agent_runtime.py \
  backend/tests/test_runtime_replica_pool.py \
  backend/tests/test_runtime_readiness.py \
  backend/tests/test_agent_runtime_protocol_contract.py -x
```

结果：220 passed in 36.35s。前一次相关子集 189 passed，最终结果已包含该子集，不叠加计数。

- 版本相同、缺失、非法、接口声明不一致及冻结版本覆盖；健康探针不调用模型/MCP。
- 新执行按冻结版本跳过不匹配节点；RUNNING/TERMINAL 使用原恢复路径，请求不被改写。
- protocol 1.4/1.5 的不匹配新请求在 Registry 占槽和 admit 前返回固定 409 错误；模型未启动，
  请求保持 PREPARED 且 digest 不变。
- 模拟 Runtime 模板更新后，已有运行实例仍复用同一执行对象，持久终态按原事件恢复，
  replacement executor 没有收到新调用。
- 传输层仅显示固定部署提示，不回显远端消息正文；原有严格工具契约拒绝测试保持通过。

3 个生产文件 mypy 通过，生产/测试修改 Ruff lint 和格式检查通过；OpenSpec strict、
Markdown 链接与 diff 空白检查通过。

## 未验收项

未部署到本机或生产，未调用真实模型或发送钉钉消息；未完成生产所有副本版本核对及目标
Job 冻结版本核对。本次交付代码防线和运维步骤，不代表生产故障已恢复。未改 Prompt 常量，
未提交代码、同步主规格或归档 change。
