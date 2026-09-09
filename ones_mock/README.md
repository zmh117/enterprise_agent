# ONES 现场接口参考

`ones/` 保留现场接口文档，仅用于核对字段、响应结构与单位；内容可能含私密材料，不得进入代码、测试、日志或版本控制。

可运行的 ONES Mock 服务及 Docker 部署入口已删除。离线测试替身位于 `backend/tests/support/ones_provider.py`，只通过进程内 TestClient 使用，不作为本地或验收环境的 ONES Provider。

`ones-mcp` 的启动方式和连接配置保持不变。`docker-compose.ones-mock.yml` 仅移除 ONES Mock 服务，原数据库/Redis 测试服务、项目名称、脚本入口和数据卷保持不变。此处不提供 Mock 网络服务，不执行真实 ONES 验收。
