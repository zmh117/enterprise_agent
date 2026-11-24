# 真实环境验收欠账

代码和自动化测试已覆盖以下能力，但仍缺目标环境、真实 Provider 或新 Publication/Job 的验收证据。不得用本地测试、Mock、合成数据、容器健康或配置存在代替；取得真实证据前保持未验收。

原始任务文本可在提交 `f89eea8e` 的 `openspec/changes/archive/` 中追溯。已被当前设计取代的旧项未列入，包括整版代码预提取、Runtime 协议 1.3 切换、可部署 ONES Mock 全链和每小时知识调度。

## 身份、渠道与外部操作

- 钉钉联系人搜索：用新 Job 验证真实命中、分页、同名人员人工消歧，以及单人和多人发送的同意、取消、重复点击。
- 钉钉 MCP mutation：待办、日历、AI 表格记录、机器人消息和工作通知各自完成同意链与拒绝链；拒绝时 Provider 写入次数为零，被排除的删除、撤回、DING 类工具不可见。
- ONES 缺陷创建与任务更新：在真实 ONES 及钉钉私聊、群聊中完成确认、拒绝、过期、冲突、Provider 失败和成功回读。证据须串起 Job、Tool Call、Action Intent、卡片点击、Provider attempt 和结果卡片，且不含 Secret。
- Webhook：真实 Grafana 或公网 HTTPS 入口、真实钉钉多接收人投递（含部分失败与限流）、免鉴权入口的公网暴露评估、生产迁移验收。

## 执行与工具

- 执行审计：用新 Job 验证 `agent_run_audit` 持久化，以及调优摘要和折叠正文的展示。
- 文件链路：在当前协议下，新鲜部署的 Compose 中完成无附件 Job、File MCP 读取、`select_sandbox_output → file_create_commit_intent → file_deliver_version`、缺失提交工具时失败关闭，以及断线恢复。
- ONES 查询分页：在重新发布的 Agent 和应用上，用超过一页的真实数据验证 provider-cursor 与 snapshot-offset 的首页、续页和终页。
- Schema 分页游标：在 Windows 部署完成迁移后，用新 Job 连续读取至少四页并核对完整性。
- 压缩字段解码：用合成记录在真实 MySQL MEDIUMBLOB、SQL Server VARCHAR(MAX)、Oracle 11.2.0.4 + Instant Client 19c Thick 上验证解码、容量与文件链路。
- Oracle 资源：在部署环境通过 Web 完成真实 Oracle 11.2.0.4 技术测试和发布资格核对。

## 知识检索

- 主 Compose 下检索成功：此前真实调用因 ONES 目标不可达，并在当时约 60 秒客户端截止下超时未通过；现行检索预算上限为 360 秒（与 Job 剩余时间取较小值），仍须重新取得目标环境证据。
- 新 Job 链路：用本地或内网 Embedding 加 Agent 既有聊天模型完成真实知识问答。
- 双权限：两位 ONES 可读范围不同的真实用户，分别验证知识库权限、ONES 本人可读性、引用回源、工作项撤权、知识库撤权和服务重启。
- 时间线核验：真实完成知识命中 → ONES 详情 → 评论文件读取。
- 检索质量：由有权人员准备经脱敏的冻结评测集（建议至少 50 条独立问法），输出 Recall、MRR、无答案误报和 p50/p95；在真实模型上对比重排前后的效果，并测单请求与四并发的时延、内存和拒绝情况。
- 同步：在目标 ONES 环境完成首次正式导入、文档级增量、日期补采同规模耗时对比；启用四小时调度后至少观察一个实际周期及恢复行为。

## 代码知识与 SVN

- 三平台挂载：在 Windows（WSL2）、macOS、Linux 分别验证 CLI、中文和空格路径、两个 Runtime 只读挂载、同版本并发读、修改互斥和异常恢复，并注明 amd64 或 arm64。
- Windows 长检出：用真实仓库完成命名卷长检出和问答读取。
- 内网 SVN：核验地址、同仓库同分支组件路径、认证引用和 external 映射。
- 答案保存与复用：真实 PG 保存、Qdrant 就绪、同版本复用不占用源码目录、更高版本线索须先核验请求版本；从页面新建空代码知识库后完成一次入库到索引就绪。
- 新 Job 重跑：保存收尾、UI 操作举证（配置操作、旧知识缺口补查、前端不可读三种情形），以及另一部署环境的拆批复测。
- 代码答案与 ONES 同时使用共享重排时的检索质量、排队和截止行为。

## 平台与构建

- Windows 10/11 WSL2 实机仍待整套验收。按[部署检查表](operations/docker-deployment.md#实际验收)验证首次启动、管理网页构建与启停、完整 Job 和文件处理，记录目标主机版本和每项结果。
- 真实 x86-64 Linux VM 仍待整套部署与负载验收。完成[部署检查表](operations/docker-deployment.md#实际验收)，记录实际资源配置、同步与检索长时间并发时的吞吐、时延和失败情况。现有 ARM 主机模拟 amd64 的结果见[本地兼容验证记录](operations/docker-compatibility-validation.md#未验证)。
- MCP Inspector：取得 Linux CI 实际运行结果，并证明 Inspector 失败时镜像门禁不会放行。
- Docling 模型：在 AMD64 与 ARM64 镜像环境核对固定 index 对应的模型目录 digest。
