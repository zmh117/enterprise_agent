# File MCP与Sandbox v2负向证据

日期：2026-08-21。证据级别：仓库内合成回归；不包含真实业务文件、Secret、目标tenant配置变更或真实Runtime到Delivery全链声明。

## 工作集与Publication门禁

执行：

```bash
.venv/bin/python -m pytest -q backend/tests/test_file_commit_streaming.py -k 'concurrent_catalog_selection or rejects_41st or requires_compatible or rechecks_current or catalog_document_selection'
```

结果：`5 passed, 14 deselected in 2.94s`。

覆盖事实：

- 16个并发重复选择只产生一个精确working-set事实和一个transfer；
- 第41个不同File/Version在working-set事实和transfer创建前返回`job_file_working_set_limit_exceeded`；
- 旧Job缺少目录搜索Tool时在晋升前失败关闭；
- 当前授权撤销后不能复用已存在transfer；
- 文档选择冻结精确Markdown Representation，替换表示不会静默改绑。

## 首字节前容量拒绝与失败释放

执行：

```bash
.venv/bin/python -m pytest -q backend/tests/test_python_file_transfer.py -k 'capacity_before_download or integrity_failure or releases_reservation'
```

结果：`4 passed, 9 deselected in 0.14s`。

覆盖事实：

- 使用默认224 MiB预算预留到边界后，下一次File MCP物化返回`sandbox_capacity_exceeded`，download调用次数为0且目标文件不存在；
- 下载异常、字节数不匹配和相同长度SHA-256不匹配均删除部分文件并释放精确输入预留；
- 相同File/Version在失败后可由正确内容重新物化，证明预留没有泄漏。

这些负向证据只证明边界实现，不替代任务8.4要求的真实Runtime→目录搜索→Docling Markdown→Agent回复或Delivery全链E2E。
