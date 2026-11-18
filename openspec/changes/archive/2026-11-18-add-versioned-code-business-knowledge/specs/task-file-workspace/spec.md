## ADDED Requirements

### Requirement: 受管代码提取来源和候选属于 Runtime 内部构建产物
受管代码提取 SHALL 使用部署登记的来源卷和独立产物卷，不经过 File Service，不产生 File ID 或伪造聊天附件。来源卷 MUST 只读挂载给 Runtime，且每个 Job 的 SDK 文件权限必须限定到服务端绑定的不可变源码快照与允许范围；普通 Job 不获得该目录访问权限。Runtime SHALL 在沙盒清理前按固定 Job/Invocation 身份回收候选与报告，使用有界文件、摘要和原子提交清单；Worker SHALL 只读回收目录并验证归属及来源配置。现有聊天文件、用户工作区、文件 Principal、配额及 File Service 权威不因此放宽。

#### Scenario: 来源目录包含多个快照
- **WHEN** Runtime 挂载卷中保留多个源码版本
- **THEN** 当前提取 Job 只能读取服务器固定的一个快照，拒绝其他版本、绝对路径及符号链接逃逸

#### Scenario: 普通问答知道源码路径
- **WHEN** 普通 Job 尝试调用 SDK Read 访问源码卷
- **THEN** 因缺少受管提取绑定拒绝访问，不能只靠容器已经挂载目录取得权限

#### Scenario: Runtime 回收产物失败
- **WHEN** 模型结束但候选未完成原子提交或摘要不一致
- **THEN** Worker 不推进候选校验和知识激活，恢复按原 Invocation 核实，不把最终回答文字作为产物

#### Scenario: 来源或产物已按策略清理
- **WHEN** 已导入知识所引用的原始字节不再保留
- **THEN** 保留知识修订和证据定位，明确原件不可复验；重新提取必须创建并核验新的来源导入
