## ADDED Requirements

### Requirement: 知识模型镜像构建可恢复中断的依赖下载

Embedding 和 reranker 镜像构建 SHALL 对中断的运行时依赖下载进行有界恢复。两个镜像 MUST 使用目标架构对应的运行时锁并校验分发文件的 SHA-256。

#### Scenario: wheel 主机支持续传

- **WHEN** wheel 下载中断且主机支持 Range 请求
- **THEN** 构建在重试预算内从已接收位置继续，校验完整文件后安装

#### Scenario: 构建无法获得有效文件

- **WHEN** 下载重试耗尽或完整文件与锁定哈希不符
- **THEN** 依赖安装失败，构建不会交付镜像
