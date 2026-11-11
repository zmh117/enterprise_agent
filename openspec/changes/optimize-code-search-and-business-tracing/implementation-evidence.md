# 本机验证记录（2026-11-11）

## 边界

用户明确原问题来自另一部署环境。当前验证为 Mac Docker / Linux Runtime、本机受管 SVN r2；不表示 test2/r52422 或 Windows 现场已经验收。未提交或推送代码。未发送钉钉、邮件或 Webhook 消息。

## 回归验证

- 搜索、源码 Runtime、Python Runtime、答案展示：200 passed。
- 答案检索、存储、索引：29 passed。
- 轮次预算、Runtime 就绪、协议、Sandbox、SDK 失败元数据：70 passed。
- 共 299 个相关测试通过；Ruff 和 git diff --check 通过。
- OpenSpec strict validation 通过；delta 已同步至 task-file-workspace 与 platform-operations canonical specs。
- 覆盖 >64 文件、>10000 元数据项、UTF-8/GB18030、类型/花括号/数值参数归一化、字段级拒绝、非法正则清理、敏感文件整文件拒绝、版本/身份/内容变化、取消后清理、三类扫描预算、超大依赖跳过，以及合成拆批分支追踪。

## 独立真实源码搜索

在 Runtime B 对本机 r2 的 set_server 执行一个 C++ 类型的错误符号搜索：

- 4355 个文件、137 批，25.68 秒；3 个命中文件，包含实际拆批业务判断。
- 25 个受限/非文本项跳过，因此覆盖不能标为全量完整；没有扫描预算截断。
- 搜索临时文件及配额清理成功。

该测量只说明这次本机源码搜索，不能用作跨版本速度提升百分比，也不代表完整问答只需 26 秒。

## 真实模型验证

Job：`job_de02726b09264ac2bdf71c7ded5b343f`，环境 sanjiu、SVN r2、应用 assist03。使用本次自行编写的拆批类问题，不冒充现场原问题。

- 运行约 300 秒，SUCCEEDED，未自动重试；无外部投递。
- 35 次工具调用：33 成功、2 拒绝。成功包含 13 Grep、4 Glob、10 Read、6 次知识/SVN/保存调用。
- 知识检索后继续核验源码，10 条原文件读取证据覆盖实际后端判断、枚举、上层调用和 EBR 页面。
- 确认本地版本允许集合包含待检、合格、风险放行；“合格近效期小于 7 天”的另一取值不在集合中。静态代码不能证明现场批次当前状态。
- 结果记录为 mixed/supported，成功保存正式答案；增量索引任务 succeeded；只读分析占用已释放。
- 一个根目录 Glob 被正确拒绝，改用明确子目录后成功。
- 首次宽泛 Grep 产生通用拒绝；独立重现宽泛搜索遇到大依赖返回底层 `code_source_file_size_or_type`。随后补修为跳过并标记不完整，直接 Read 仍拒绝；已补回归并更新两 Runtime。历史审计保留原状。完整模型试跑统计来自补修前。补修后使用真实 r2 根目录、不加文件类型的宽泛搜索：20.99 秒扫描 4096 文件/128 批，跳过 42 项，保留 32 个命中文件并以 match_capacity/complete=false 正常返回，未再被大依赖中断；缓存配额清零。
- 原答案对未读到语言包正文、其他拆批入口和页面最终展示形态保留未知；不能将这些项视为已验证。

首次验证 Job `job_d35406af5ae24d60b70c62b51192f92b` 的测试输入写成“环境 sanjiu”，没有满足当前显式环境识别格式“环境：sanjiu”，卡在知识入口。它不计入源码搜索效果。平台尚未兼容该无冒号表达，本变更未放宽环境授权边界。

## 发布与部署

- API、两个 Agent Worker、Job Dispatcher、Channel Dispatcher、Webhook Worker、knowledge-mcp 与两个 Runtime 已更新；Prompt v17。
- 最终两个 Runtime、API 与 knowledge-mcp 的容器健康检查均 healthy。两个 Runtime 安装宿主调用的 ripgrep；Agent 无 Bash，不持有 SVN 凭据，源码卷保持只读。
- default-diagnostic-agent 新发布 r56；assist03 新发布 r72 并激活；冻结 Skill SHA256：`0f1ffa3bb029892d10f5b232535d0abc3db4a3feada7cd2b7ae1b633f0ca4696`。
- 发布前后核对其他应用 Deployment 记录不变。
- 本机新 Docker 源码卷最初为空；将原 .local 中 1.2 GiB 的 mes-business 检出复制到空卷，保留原目录与持久身份，设置既定源码组权限。原只读挂载与 r2 读取核验成功，不改变知识库绑定。
- 另发现既有 knowledge-ops-controller 上报 `knowledge_ops_status_unavailable`（心跳 online）；本次实际检索、SVN、索引与 Runtime 健康验证不依赖它，该独立运维状态问题未纳入本次变更。

## 待现场验收

另一部署环境的 test2/r52422 原拆批问题及真实 Windows 运行效果未验证；任务 2.5 保持未完成。部署时更新同一套调用端/Runtime 镜像，并通过正式 Agent/Application 发布绑定新 Skill，不能仅 restart 或只复制 Skill 文件。
