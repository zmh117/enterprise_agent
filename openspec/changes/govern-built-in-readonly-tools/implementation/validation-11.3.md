# 11.3 车间数据库与 Redis 真实格式样例验收证据

执行日期：2026-08-06（Asia/Shanghai）

## 验收边界

- 本项使用用户提供的 GL001、CZ002 完整 Redis key 和数据库/Redis 的实际命名格式执行可复现的策略边界验收。
- GL002 Redis 样例按同一部署契约推导为完整 namespace `cr999.crmes.CRMES_TEST_GL#GL002@$`；未把推导值描述为用户提供的线上 key。
- 验收调用生产 SQL analyzer、Redis namespace enforcement 和 Redis Partition Policy verifier，但使用有界测试客户端，不连接或读取客户生产数据库、Redis 实例。

## 数据库表前缀

对 `GL001_`、`GL002_`、`CZ002_` 分别验证：

- 同车间 `*_EBR_ORDER` 表允许进入既有只读 SQL 边界；
- 其余两个车间的表均在连接数据库前以 `PolicyViolation` 拒绝；
- 三种策略执行全组合越界验证，不依赖字符串包含放行。

## Redis namespace

GL001 验证以下用户提供的完整 key：

- `cr999.crmes.CRMES_TEST_GL#GL001@$EBRDataText.809901890274822.Sheet4.rows`
- `cr999.crmes.CRMES_TEST_GL#GL001@$[WEIGH]:wo.20250627MAOYAN10-yapi5:weigh_id.list`
- `cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:674351510281286:exec_param`
- `cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:675454427238982:states`

CZ002 验证用户提供的完整 key：

- `cr999.crmes.CRMES_TEST_CZ#CZ002@$[WEIGH]:wo.20260410-11:weigh_id.list`

GL002 使用同一命名契约构造完整 key。三个车间均验证同 namespace 允许，其余两个 namespace 在访问 Redis 前拒绝。

## zero-match

- verifier 对三个完整 namespace 分别且仅执行一次系统生成的 `prefix*` 有界 SCAN；
- 全部返回零条时，验证状态仍为 `PASSED` 并设置 `zero_match_warning=true`；
- 原精确前缀没有缩短、扩大或自动切换；
- 持久化摘要不含完整 namespace 或业务 key。

## 执行命令与结果

```text
.venv/bin/pytest -q backend/tests/test_real_workshop_partition_examples.py backend/tests/test_internal_api_platform_domain.py backend/tests/test_workshop_partition_policy_service.py
```

结果：`45 passed, 12 subtests passed`；另有一个来自测试依赖的既有 Starlette deprecation warning。

新增回归入口：`backend/tests/test_real_workshop_partition_examples.py`。
