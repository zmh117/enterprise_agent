# 任务文件工作区沙盒容量基线

## 结论

- 单个 Runtime 容器的 Job Sandbox 默认容量：256 MiB。
- Runtime readiness 的容量下限：64 MiB；低于该值必须拒绝就绪。
- 第一阶段单文件上限：15 MiB。
- 工作区未保留内容配额：100 MiB。
- 最大建模工作集：224 MiB，默认容量保留 32 MiB 安全余量。

这些是每个 Runtime 容器的容量边界，不代表允许单个 Agent 无界使用全部空间。后续实现仍须执行每 Job 文件数、逻辑字节和路径配额。

## 建模方法

`single-legal-file` 同时写入：

- 15 MiB 合法输入；
- 15 MiB 编辑后输出；
- 16 MiB SDK、配置和流式处理临时空间。

合计 46 MiB，因此 32 MiB 不能处理一个合法输入；readiness 下限取整为 64 MiB。

`maximum-workspace-working-set` 同时写入：

- 100 MiB 已物化工作区输入；
- 100 MiB 编辑或生成输出预留；
- 24 MiB 流式传输与 Runtime 临时空间。

合计 224 MiB；默认 256 MiB，剩余 32 MiB，约为建模工作集的 14.3%。

## 可重复验证

执行：

```bash
.venv/bin/python scripts/benchmark_file_workspace_sandbox.py
```

脚本只生成有效 UTF-8 合成文本，输出 JSON 中的逻辑大小、实际分配大小和耗时；临时文件在每个场景完成后立即删除。部署配置后续使用统一的受控容量配置，并由 Python 与 TypeScript Runtime readiness 校验不低于 64 MiB。
