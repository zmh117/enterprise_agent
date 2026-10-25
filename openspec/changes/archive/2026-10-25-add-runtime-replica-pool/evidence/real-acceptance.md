# Runtime 池真实 SDK/Provider 与有界容量验收

2026-10-25（Asia/Shanghai），RPOOL-19、RPOOL-20 **PASS**。证据见 [结构化记录](real-provider.json) 和 [环境清理](real-cleanup.json)。本次没有提交或推送代码。

## 环境与调用边界

- 本机 Docker Compose 独立项目 `ea-rpool-a3183f0a`，3 个固定 Runtime、最多 3 个 Worker、独立 PostgreSQL 18（schema 147）和 RabbitMQ 4。Runtime 非 root、每节点一个进程/执行槽、独立 tmpfs。
- ARM64 macOS；Docker 29.4.1 虚拟机可用 10 CPU、约 15.60 GiB 内存。宿主物理内存查询受沙箱限制，没有猜测该值。
- 真实 Claude Agent SDK **0.2.144**，现有受管 `default-deepseek-anthropic` revision 2，模型 **deepseek-v4-flash**，Provider host `api.deepseek.com`。fake Provider 明确 disabled；没有替换 SDK 返回值或伪造模型结果。
- 仅将所选受管模型配置和一条既有加密凭据记录经进程内管道复制到临时数据库；没有导出凭据明文。Runtime 正常解密，原 Master Key 文件只读挂载；原配置 hash、凭据 active version 和加密记录摘要前后相同，未轮换或新增真实凭据。
- 业务输入、Session、Agent/Application Publication、输出与沙盒标记均为隔离环境的合成数据。源数据库仅为只读提取配置而启动，没有对其运行迁移、执行 Job 或改写模型配置。
- 硬上限 **18 Job**、业务自动重试 **0**、最多 **4 轮**。配置超时上限 120 秒，冻结后的当前 Application 策略实际执行上限 **60 秒**。此次总计 18 次 SDK 启动，17 次成功、1 次预期取消；每个 Invocation 只启动一次。

## RPOOL-19：真实并行与隔离

三个不同 Session 分别在 A/B/C 执行，真实 SDK query 区间共同重叠 **6.15 秒**；整个验收每个节点的最大 SDK 并发均为 **1**。各调用有实际模型返回及非零 Provider API duration，未用 healthy、ACK 或线程数推断并行。

冻结上下文只包含各自合成标记；结果包含本 Session 标记、不含其他 Session 标记。实际传给 SDK 的 cwd 等于各自独立 Job Sandbox，透明测试标记文件在调用前后保持正确，最后三个节点均无残留 Job Sandbox。凭据绑定与受管 revision 一致，调用前后进程中的临时凭据环境已恢复。

本机只有 **一组**现有受管凭据，因此本次验证的是该凭据在三个独立进程中的正确绑定、只读使用与环境回收；没有真实测量不同凭据切换或跨账号限流。多凭据/授权对抗仍由已完成的合同测试覆盖，不将本次单凭据测量扩张为多凭据真实验收。

SDK query 区间包括本地 SDK 的开销，属于真实执行重叠证据；Provider 报告的 API duration 用于佐证，不能视为远端服务内部调度的逐请求追踪。

## RPOOL-20：容量测量

相同合成短文本工作负载（20 行虚构检查说明），一 Worker 顺序处理 3 Job，三 Worker 突发提交 6 Job。三节点映射不变，仅调整测试 Worker 数。

| 配置 | 指标（秒） | 样本 | P50 | P95 | P99 | 最大 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Worker / 3 Job | 排队 | 3 | 7.60 | 14.94 | 15.59 | 15.76 |
| 1 Worker / 3 Job | SDK 执行 | 3 | 7.99 | 10.58 | 10.81 | 10.87 |
| 3 Worker / 6 Job | 排队 | 6 | 4.44 | 8.48 | 8.49 | 8.49 |
| 3 Worker / 6 Job | SDK 执行 | 6 | 7.87 | 8.44 | 8.45 | 8.45 |

- 单 Worker 阶段 **26.77 秒**排空，观测吞吐 **0.112 Job/s**；三 Worker 阶段 **17.29 秒**排空，观测吞吐 **0.347 Job/s**。这些是本次小样本观测值，不是模型配额或生产容量保证。
- 最大 PENDING/RETRY_WAIT 数分别为 3 和 6，包含刚提交但尚未领取的任务；两阶段最终积压均为 0。容量等待不增加 retry_count；没有意外 Job 失败或向调用者暴露的模型限流错误。
- 分位数采用线性插值，样本仅 3/6 条；没有据此建立 P99 SLO、长期稳态吞吐或不同模型的容量承诺。SDK 内部隐藏 HTTP 重试和 Provider 配额没有直接观测。
- 共 **144 次**资源采样，约 2 秒间隔。单 Runtime 容器最高观测内存 **535.3 MiB**；逐容器 CPU、内存和进程数峰值保存在 JSON。采样峰值不等于完整连续时间峰值，也不与各容器非同时峰值相加宣称总峰值。

## 真实取消与接管

- 在真实 SDK 执行中只保存取消意图，不发送即时取消通知：Runtime 轮询后本地停止耗时 **8.31 秒**，Job 终结耗时 **8.60 秒**；结果为 FAILED + runtime_cancelled，停止证据存在。上游已接收请求后的计算和计费无法由本地停止证明撤销。
- 在真实 SDK 执行中 SIGKILL 测试 Worker，随后重新启动：接管并提交原结果耗时 **34.07 秒**，领取版本提高；Invocation、digest、Runtime owner 和原 deadline 保持不变，SDK 启动数仍为 1。这一耗时包含等待旧控制租约到期和结果提交，不是纯模型延迟。

## 处理过的验收脚本问题

初次启动的 fake-provider 参数从空值修正为显式 disabled，发生在任何真实模型调用前。预热 Job 已成功，但收集器误从领域对象读取 created_at；修复为读取持久化字段后只补取原结果，没有重跑模型。

第一批三路模型调用成功，但测试 Agent 未授权文件工具，回显标记不能证明文件隔离。该批保留为失败的隔离用例，没有被计作通过。随后三路重跑改为核对真实 SDK cwd、独立透明标记和清理结果，保持既有工具权限；不声称已验证原生文件工具或 File MCP 的端到端业务链路。

## 运行建议与未测范围

维持默认 **2 个固定 Runtime / 2 个 Worker** 作为起点。本次证明本机和该受管模型支持受测 3 槽并行；需要提升时可按运维流程显式扩至 3 个固定节点，同时确认 Provider 配额并持续观察排队、错误率和内存。不能直接按本次吞吐外推更大副本数。

保留当前 5 秒续租、30 秒租约和 10 秒停止宽限。实测接管约 34 秒包含租约等待，没有证据支持缩短租约；当前合成短文本在 60 秒执行预算内完成，长文本、多轮工具、多个凭据、跨主机和长期压测需要单独测量。此处不给生产默认预算做自动修改。

此次没有验证 Oracle、生产 HTTPS/HMAC、Grafana 告警到钉钉的完整业务闭环、外部消息投递或生产发布。这些边界不因 Runtime 池通过而改变。

复现入口：[真实验收脚本](../../../../../backend/tests/support/runtime_pool/real.py)、[透明观测模块](../../../../../backend/tests/support/runtime_pool/real_node.py)、[收集器](../../../../../backend/tests/support/runtime_pool/collect_real.py)。需要明确授权真实模型调用；普通确定性验收不会自动启用本入口。

收尾补充了可复用的有界资源采样入口，并使历史失败用例对后续干净运行可选；没有修改产品执行代码或本次测量结果。JSON 同时保留实测时源码摘要与交付时测试脚本摘要。
