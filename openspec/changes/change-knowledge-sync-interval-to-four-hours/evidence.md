# 四小时自动同步验证

验证日期：2026-11-05。全部使用本地测试及合成数据，未操作真实环境或已有业务数据库。

- 知识运维、受管同步、候选、补采及 Compose 合同测试：105 passed，5 skipped。覆盖四小时到期、首次立即执行、活动任务互斥及完成后重新计时。
- 在独立 PostgreSQL 18 测试容器中运行迁移回归：SQLite 与 PostgreSQL 共 2 passed。由 152 升级至 153，核对间隔、原下次时间顺延三小时、首次立即到期、停用与暂停状态、配置字段、活动 run/operation、重复迁移及外键完整性。
- schema migration runtime 测试：51 passed，包含迁移清单、schema head 和注释检查。
- 知识库运维页面组件测试：12 passed；覆盖运行中显示“本轮完成后 4 小时”及暂停状态。前端生产构建通过，保留现有大 chunk 提示。
- 修改文件 Ruff lint/format、三个生产 Python 文件 mypy、前端 ESLint/Prettier、变更及 platform-operations 主规格严格校验通过。

已同步主规范与运维说明。未连接真实 ONES，未执行真实环境迁移、部署或等待实际四小时调度；目标环境需运行主 Migrator 至 153 并部署匹配版本服务镜像后验收。本次未修改检索超时链路。
