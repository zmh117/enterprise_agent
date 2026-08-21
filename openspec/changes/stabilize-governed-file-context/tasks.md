## 1. 机器协议时间

- [x] 1.1 将文件时间 helper 改为 UTC RFC 3339 canonical 序列化，并更新 Manifest、File MCP、Runtime 元数据调用点
- [x] 1.2 更新 Agent 文件约束和 Tool 描述，明确机器值为 UTC、用户展示可按时区转换
- [x] 1.3 增加 UTC instant、naive UTC、Manifest hash 和协议消费者回归测试

## 2. 文件上下文选择

- [x] 2.1 实现日期解析三态和非法日期安全通知，禁止回退为当天
- [x] 2.2 将时间窗口命中统一降为最多 20 个 `METADATA + TIME_WINDOW` 候选，并保持完整文件名直接绑定边界
- [x] 2.3 增加非法日期、逆序区间、唯一/多个/超限时间窗口及部分文件名回归测试

## 3. 历史保留候选

- [x] 3.1 收紧跨会话候选查询，同时校验附件、binding、文件版本和有效保留事实
- [x] 3.2 增加缺失/过期保留事实、Cleanup 延迟、不可用附件和有效候选仓储测试

## 4. Docling Publication 组合约束

- [x] 4.1 新增后端 Docling Profile 组合校验器，并在草稿保存与发布校验复用
- [x] 4.2 更新管理前端 Profile 联动，自动开启工作区、File MCP、附件、连续会话并补选可用读取工具
- [x] 4.3 增加后端字段级错误和前端联动/阻塞提示测试

## 5. 质量验证

- [x] 5.1 修复受影响 Python/TypeScript 文件的静态检查问题并运行聚焦 lint/typecheck
- [x] 5.2 运行聚焦回归、OpenSpec strict、Compose config 和差异完整性检查，记录未执行的外部 E2E 边界
