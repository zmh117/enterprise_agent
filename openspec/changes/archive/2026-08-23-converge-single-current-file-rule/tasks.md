## 1. 单一规则领域模型

- [x] 1.1 将直接文本规则收敛为固定`text-v2`并删除`text-v1`枚举、兼容别名和默认分支
- [x] 1.2 将文档Profile注册表收敛为`NONE`与独立完整定义的`docling-layout-ocr-v2`
- [x] 1.3 删除后端管理API、Publication快照和Job请求中的可切换文本策略字段
- [x] 1.4 删除旧文档Profile的API枚举、运行分支、hash派生和测试夹具

## 2. Manifest v5与Working Set

- [x] 2.1 将Job创建、持久化与hash固定为Manifest schema v5并删除v1-v4生成/读取代码
- [x] 2.2 修复Catalog Revision与Job Tool Snapshot授权判定，使分页目录和空Manifest行为一致
- [x] 2.3 删除Agent Worker的v5到v4投影并把v5文件上下文原样传给Runtime
- [x] 2.4 删除File MCP、Runtime和测试中的旧Manifest parser、兼容字段及fixture

## 3. Runtime protocol 1.3

- [x] 3.1 将protocol 1.3合同升级为只接受Manifest v5并覆盖无附件空文件上下文
- [x] 3.2 删除protocol 1.0、1.1、1.2合同目录、生成代码、版本协商和恢复分支
- [x] 3.3 将Worker、Runtime健康声明、执行摘要约束与合同测试固定为`python-v1` protocol 1.3

## 4. 统一附件处理链

- [x] 4.1 删除进程内DOCX/XLSX/PPTX/Markdown附件提取与模型上下文注入
- [x] 4.2 删除`attachment_content`模型、repository、service调用和API投影
- [x] 4.3 删除`message_attachment`重复文件身份影子字段并统一使用canonical binding表
- [x] 4.4 将Office生成库从生产依赖移出，仅在合成测试fixture确有需要时保留开发依赖

## 5. 管理端单一配置

- [x] 5.1 删除应用组成配置中的文件格式策略选择并展示固定`text-v2`只读说明
- [x] 5.2 文档处理选择只展示`NONE`和`docling-layout-ocr-v2`并删除旧Profile文案、Mock和类型
- [x] 5.3 更新应用API客户端、表单校验、快照展示和前端回归测试

## 6. 数据库与开放测试重置

- [x] 6.1 实现有精确确认、非终态/队列门禁和脱敏预检的开放测试文件域重置命令
- [x] 6.2 通过File Service对象存储适配器删除受管对象并按外键拓扑清理文件域和强关联终态测试事实
- [x] 6.3 新增前向migration删除旧表/列并收缩Profile、Manifest和Runtime协议约束
- [x] 6.4 更新schema contract、migration ledger、数据库注释和SQLite/PostgreSQL迁移测试

## 7. 验证与交付

- [x] 7.1 增加无附件文字Job、直接文本、文档Profile、Manifest v5、Working Set和Runtime 1.3聚焦回归
- [x] 7.2 增加旧策略/Profile/Manifest/协议稳定拒绝及发布产物无旧实现门禁
- [x] 7.3 运行后端、前端、合同、migration、Compose配置、OpenSpec strict与diff检查
- [ ] 7.4 在重建受影响服务后完成新鲜Runtime到Delivery全链E2E并记录未验证项
