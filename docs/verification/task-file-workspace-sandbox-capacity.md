# 任务文件工作区 Sandbox v2 容量基线

## 结论

- Python Runtime每个Job Sandbox：最多64个常规文件、224 MiB共享容量。
- `inputs`：最多40个不同File/Version；重复物化同一版本不重复计数。
- `work/outputs`：合计最多16个文件。
- Runtime内部`tmp`与安全余量：最多8个文件，Agent不可直接写入。
- 每个文本或Markdown文件仍不得超过15 MiB。
- readiness必须同时验证64/224 MiB、40/16/8和15 MiB单文件限制；任一配置漂移均失败关闭。

224 MiB是三个分区共享的真实字节池，不承诺64个文件都可达到15 MiB。任何入口在剩余容量不足时都必须先拒绝，再产生文件或下载字节。

## 建模方法

`one-max-input-output-with-tmp`写入一个15 MiB输入、一个15 MiB输出和1 MiB临时文件，共3个文件、31 MiB。

`sandbox-v2-partition-boundary`写入：

- 40个5 MiB输入，共200 MiB；
- 16个1 MiB工作/输出文件，共16 MiB；
- 8个1 MiB Runtime临时文件，共8 MiB。

合计正好64个文件、224 MiB。该场景只用于验证分区计数和共享容量边界；实际Job仍须按每项真实大小整批预检。

## 可重复验证

执行：

```bash
.venv/bin/python scripts/benchmark_file_workspace_sandbox.py
```

脚本只生成UTF-8合成文本，输出文件数、逻辑大小、实际分配大小和耗时，并在每个场景结束后删除临时内容。自动输入与File MCP物化的首字节前拒绝、失败释放和hash不匹配清理由Runtime聚焦回归验证。
