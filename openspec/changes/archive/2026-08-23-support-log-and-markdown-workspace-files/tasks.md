## 1. 格式策略与持久化契约

- [x] 1.1 在文件领域新增代码注册的`text-v1/text-v2`格式策略，固定TXT全能力、LOG只读、Markdown全能力及扩展名、MIME、UTF-8、BOM、NUL和15 MiB规则
- [x] 1.2 用统一格式策略替换File Service、Manifest、附件分类和公共错误目录中的TXT专用常量，保留旧TXT helper的有界兼容读取并禁止新调用方自行判断后缀
- [x] 1.3 为Business Application Revision/Publication snapshot增加`file_format_policy_version`规范化、hash、审计和`text-v1`历史默认；按当前持久化模型补充必要migration与repository投影
- [x] 1.4 升级Job File Manifest schema，冻结策略版本、format code、精确版本和允许操作，并为旧schema提供TXT-only兼容读取及hash完整性测试
- [x] 1.5 增加格式策略、Publication兼容、Manifest篡改、未知format/版本和操作扩大失败关闭的领域与repository测试

## 2. 发布组合与Job创建

- [x] 2.1 扩展业务应用草稿/API/前端类型与发布校验，使`text-v2`只可与兼容Agent Runtime protocol和精确File MCP schema hash组合
- [x] 2.2 更新Agent/Application发布预览、详情与运行时就绪摘要，展示非敏感文件策略版本和兼容状态，不提供任意格式配置入口
- [x] 2.3 更新Job创建与Tool Execution Snapshot，使新Job冻结Publication的文件策略版本且历史Publication保持`text-v1`
- [x] 2.4 将显式文件输出识别收敛为格式+动作矩阵：保留TXT规则，增加明确Markdown/`.md`创建、编辑、保存、导出触发，并为概念讨论、聊天Markdown排版和普通日志分析补负向测试
- [x] 2.5 更新Job等待附件、未消费附件认领与Manifest最终化逻辑，按受支持文本格式而非TXT专用查询释放同一个Job

## 3. Channel与File Worker导入

- [x] 3.1 扩展Channel附件白名单和真实内容校验：`.txt=text/plain`、`.log=text/plain`或严格文本验证后的`application/octet-stream`、`.md=text/markdown|text/plain`，继续拒绝`.markdown`进入任务工作区
- [x] 3.2 更新钉钉Stream附件归一化和纯附件暂存，使`text-v2`的TXT/LOG/Markdown进入同一Session未消费集合，`text-v1`不被追溯扩大
- [x] 3.3 将File Worker TXT validator重构为流式文本validator，覆盖UTF-8 BOM、无BOM输出、NUL、分块多字节边界、15 MiB和扩展名/MIME/内容冲突
- [x] 3.4 更新附件导入、幂等重试、终态凭证清除和WAITING_INPUT释放，持久化规范化format及只读LOG操作集合
- [x] 3.5 增加TXT/LOG/Markdown混合纯附件、通用LOG MIME、非法编码、二进制伪装、重复消息和旧Publication负向契约测试

## 4. File Service与File MCP

- [x] 4.1 扩展File MCP物化与提交封闭schema，使物化允许TXT/LOG/Markdown，输出选择和Commit只允许TXT/Markdown，并更新Tool schema hash与安全描述
- [x] 4.2 更新File Service流式导入、物化路径生成、元数据和对象Content-Type，使format与扩展名保持精确且不在模型/API中暴露对象位置
- [x] 4.3 在Commit Intent创建、上传接收和事务终结三处复核策略、handle、format、逻辑扩展名、基础版本、编码、大小和配额，并在正文接收前拒绝LOG提交
- [x] 4.4 保持TXT/Markdown严格幂等提交、同名竞态、版本冲突与Conflict Candidate语义，禁止跨format新版本和Markdown自动合并/渲染
- [x] 4.5 更新File MCP统一operation audit与安全错误码，记录策略版本和format摘要但排除正文、JWT、对象键和凭据
- [x] 4.6 增加File Service/MCP测试，覆盖LOG改名绕过、handle复用、旧schema漂移、Markdown提交恢复、MIME冲突和无部分对象可见性

## 5. Runtime协议与Python Runtime

- [x] 5.1 新增Runtime protocol v1.3语言无关schema，投影文件策略版本、Manifest format与允许操作，并生成Python/TypeScript类型及请求digest测试
- [x] 5.2 更新Worker Runtime选择和协议兼容检查，使`text-v2`只进入v1.3兼容Runtime，未知或旧Runtime在模型调用前失败关闭且不跨Runtime fallback
- [x] 5.3 重构Python Job Sandbox权限：Read/Glob/Grep允许TXT/LOG/Markdown，Write/Edit只允许TXT/Markdown，并在副作用前拒绝LOG、未知格式、路径逃逸、符号链接和非常规文件
- [x] 5.4 更新Python File MCP bridge、流式传输、输出选择器和Agent上下文，使自动物化保留format/操作、Markdown可选提交、LOG只读且完整字节不进入MCP JSON
- [x] 5.5 增加Python真实Claude SDK权限回调和文件桥回归，覆盖绝对路径归一化、Markdown Write/Edit、LOG写拒绝、BOM/NUL/大小与finally清理

## 6. TypeScript Runtime与跨实现一致性

- [x] 6.1 让TypeScript Runtime消费生成的v1.3契约并严格校验策略版本、format和操作集合，保留v1.0-v1.2的TXT-only兼容行为
- [x] 6.2 重构TypeScript Job Sandbox与File bridge，使Read/Glob/Grep和Write/Edit/输出选择权限与Python完全一致，并在副作用前拒绝LOG写入
- [x] 6.3 更新TypeScript流式物化、Markdown提交、隐藏传输控制拦截、Tool事件安全摘要和所有终态Sandbox清理
- [x] 6.4 建立语言无关格式策略夹具并由两个Runtime运行，逐项比较扩展名、MIME、BOM、NUL、大小、路径、符号链接、操作和稳定错误结果
- [x] 6.5 运行两个Runtime的lint、typecheck、单元、协议生成漂移和真实权限回调测试，确认没有开放Bash、Web或任意文件工具

## 7. 精确版本交付与产品说明

- [x] 7.1 扩展文件交付元数据与钉钉发送器，支持新提交TXT/Markdown及Manifest既有TXT/LOG/Markdown精确版本，同时保持reply route、Connector和哈希不变
- [x] 7.2 保证LOG原样交付不创建Commit Intent或新版本，Markdown默认交付/WORKSPACE_ONLY、响应丢失重试和终态失败通知继续幂等且不重跑Agent
- [x] 7.3 更新管理端文件能力、Job详情和运行时就绪文案，展示TXT/LOG/Markdown能力矩阵与冻结策略来源，不渲染Markdown正文或暴露文件内容
- [x] 7.4 更新`CONTEXT.md`、ADR、架构说明、切换运行手册和用户说明，明确LOG只读、Markdown不渲染、`.markdown`不进入工作区及回滚保留规则

## 8. 切换、验收与质量门禁

- [x] 8.1 实现切换预检，枚举引用旧File MCP schema hash的非终态、待重试和可恢复文件Job；未排空或隔离时禁止启用`text-v2`
- [ ] 8.2 使用合成数据完成私聊与群聊TXT/LOG/Markdown全链路验收：Channel、File Worker、File Service、PostgreSQL、MinIO、RabbitMQ、两个Runtime、File MCP、Commit和Delivery
  - 当前仓库内合成验收使用内存对象存储和模拟Delivery；真实PostgreSQL、MinIO、RabbitMQ、双Runtime容器与目标渠道证据仍按切换运行手册部署后验收。
- [x] 8.3 完成负向验收：旧Publication、LOG写入/改名、Markdown主动内容、非法MIME/编码、15 MiB、路径逃逸、schema漂移、权限撤销、重试与Secret/正文不泄漏
- [x] 8.4 验证回滚到`text-v1` Publication不会删除已创建Markdown版本、不会让旧Runtime处理`text-v2` Job，并保持历史版本只读交付和审计可追溯
- [x] 8.5 运行受影响后端、前端、两个Runtime、MCP、Worker、Delivery、migration与Compose测试，并执行`openspec validate support-log-and-markdown-workspace-files --strict`、全量严格校验、任务核对和`git diff --check`
