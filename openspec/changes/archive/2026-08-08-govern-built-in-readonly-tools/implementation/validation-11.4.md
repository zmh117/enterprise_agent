# 11.4 Loki global/environment 配置验收

执行日期：2026-08-06（Asia/Shanghai）

## 验收端点与边界

用户确认当前 Loki 由本机容器提供，入口为 `http://localhost:3100`，tenant 为
`tenant1`。Docker 只读检查确认 `evaluate-loki--gateway-1` 健康并发布宿主机
`3100` 端口。

本次验收把同一真实端点分别声明为 global Resource 和一个精确 Environment
Resource，并在两个不同的测试 Environment 上验证两种配置语义。它证明平台能够
管理和执行 global/environment 配置，但不宣称已经验证两套物理隔离的 Loki 部署。

全程只访问 buildinfo、labels、label-values 和 series 元数据，不读取、不输出、
不持久化日志正文或 Secret。

## 现场发现结果

- `/loki/api/v1/status/buildinfo` 成功，Loki 版本为 `3.7.3`；
- 当前标签目录包含 `cluster`、`container`、`region`、`service_name`；
- `cluster` 的真实值包含 `mes-cluster`；
- 在精确条件 `cluster=mes-cluster` 下级联发现 `region`，真实值包含
  `datacenter-01`；
- 精确 AND selector `cluster=mes-cluster AND region=datacenter-01` 命中流元数据。

本机实例的标签模型与较早快照中的 `customer/workshop` 不同。本次验收以在线返回的
`cluster/region` 为准；平台策略并不硬编码具体业务标签名。

## 可复现现场验收

新增 `backend/tests/test_live_loki_acceptance.py`。该测试默认跳过，只有显式提供
`LOKI_LIVE_ACCEPTANCE_URL` 才访问外部 Loki。它通过生产实现验证：

1. global 和 environment Resource Draft 都通过真实 buildinfo、标签目录和级联值发现；
2. 两类 Resource 都通过真实技术探针并发布不可变 Resource Revision；
3. global Resource 的环境策略使用强制 `cluster=mes-cluster` 并命中；
4. environment Resource 的基地策略使用强制
   `cluster=mes-cluster AND region=datacenter-01` 并命中；
5. 不存在的 region 返回零结果，验证仍为 PASSED、发布健康状态为 EMPTY，且没有移除
   或放宽任何强制条件；
6. environment Resource 被另一个 Environment 引用时以
   `loki_scope_policy_resource_invalid` 失败关闭；
7. 调用方尝试覆盖强制 `region` 时在访问 Loki 前以 PolicyViolation 拒绝。

执行命令：

```text
env LOKI_LIVE_ACCEPTANCE_URL=http://localhost:3100 \
    LOKI_LIVE_ACCEPTANCE_TENANT=tenant1 \
    LOKI_LIVE_ACCEPTANCE_CLUSTER=mes-cluster \
    LOKI_LIVE_ACCEPTANCE_REGION=datacenter-01 \
    .venv/bin/pytest -q backend/tests/test_live_loki_acceptance.py
```

结果：`1 passed`；另有一个来自测试依赖的既有 Starlette deprecation warning。

## 结论

当前 global Loki 与至少一个 environment-scoped 配置均已通过在线验收；级联发现、
环境与可选基地强制 selector、空结果和越界拒绝全部有真实端点或生产策略代码证据。
