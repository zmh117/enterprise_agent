# Task File Workspace 合成验收证据

日期：2026-08-17。证据级别：仓库内 synthetic acceptance；不包含真实业务文件、真实 Secret、真实钉钉调用或目标环境部署声明。

## 新鲜链路

`backend/tests/test_task_file_workspace_synthetic_acceptance.py` 使用合成 UTF-8 TXT/LOG/Markdown、内存对象存储和假钉钉 Delivery，贯通：

```text
DingTalk sanitized Channel event
 -> Job + Workspace + attachment queue task
 -> AttachmentProcessingService（file-worker handler）
 -> in-process File Service streaming boundary
 -> Managed File / immutable Version / lineage / Manifest
 -> Python Runtime Job Sandbox
 -> exact materialization -> restricted Edit
 -> Commit Intent -> streamed upload -> current Version advance
 -> Delivery Outbox -> simulated response loss -> same-version retry
 -> Retained File + file_commit_results + final reply
```

测试同时证明 Job 沙盒在终态路径清理、输入/输出正文不进入 MCP 控制结果，以及默认文件交付使用冻结的当前 reply route。RabbitMQ durable queue/retry/dead 声明、单消费者消息 schema 和 ack 边界由 `backend/tests/test_attachment_worker_contract.py` 独立验证；Compose 单消费者和凭据隔离由 `backend/tests/test_task_file_workspace_compose.py` 验证。

混合格式用例证明 `text-v2` Job 固定选择 Runtime protocol v1.3，Manifest schema v3 同时冻结 TXT、只读 LOG 和可编辑 Markdown 的精确版本与操作集合。`agent-runtime/contracts/text-format-policy-v2.fixture.json` 由 Python 与 TypeScript Runtime共同执行，比较扩展名、MIME、BOM、NUL、大小、路径、符号链接、操作和稳定错误码；Markdown 正文不会进入管理端或被渲染。

## 群与并发

`backend/tests/test_task_file_workspace_group_acceptance.py` 使用同群两个内部用户和两个冻结 Job：两人均可基于同一群工作区版本创建提交；第一个提交推进唯一 current version，第二个成为 Conflict Candidate；提交与实际 Job sender 可追溯；会话切换到另一群后授权失败关闭。

## 负向覆盖

| 范围 | 证据 |
|---|---|
| Principal/JWKS/Job/Publication/scope/schema 漂移 | `test_file_service_security.py`, `test_principal_jwt.py` |
| 私聊、群聊、跨会话、跨租户、撤权、内容删除 | `test_file_authorization.py`, `test_job_file_manifest.py` |
| TXT/LOG/Markdown扩展名、MIME、UTF-8、BOM、NUL、15 MiB | `test_text_format_policy.py`, TypeScript shared fixture, `test_file_commit_streaming.py` |
| LOG 写入、改名、Commit与旧Publication/schema漂移 | File Service、Manifest、Python/TypeScript Runtime contract tests |
| 路径逃逸、符号链接、特殊设备、容量、残留清理 | Python/TypeScript Job Sandbox tests |
| Commit 幂等、响应丢失、对象/DB 失败、部分冲突 | `test_file_commit_streaming.py` |
| staging/工作区/附件/保留/孤儿清理 | `test_file_lifecycle_service.py` |
| Delivery 超时、响应丢失、重复、跨会话、最终失败 | `test_file_version_delivery.py` |
| Secret、正文、对象键和 URL 不泄漏 | File Service、MCP contract、Runtime transfer tests |

## Deployment-gated

真实 PostgreSQL、MinIO、RabbitMQ、平台 Secret provider、短时服务 Principal 轮换、容器网络以及真实钉钉上传/发送仍须按 `docs/operations/task-file-workspace-cutover.md` 在目标环境单独验收。容器 health 不得替代上述业务链证据。
