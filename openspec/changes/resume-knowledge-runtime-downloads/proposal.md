## Why

现场 AMD64 构建在读取官方 PyTorch CPU wheel 时发生 ReadTimeoutError，随后整个 Compose 构建中止。Embedding 与 reranker 使用同一套架构锁，也都使用基础镜像里的 pip 25.0.1。

## What Changes

- 两个镜像共用相同的依赖安装步骤，允许短时读取停顿，并对中断下载进行有限次数的续传或重试。
- 保留各架构的运行时锁、SHA-256 校验和 CPU Torch 导入检查。

## Capabilities

### Modified Capabilities

- `platform-operations`：增强知识模型镜像在不稳定网络中的构建行为。

## Impact

涉及 Embedding、reranker 及复用这两个镜像的模型准备服务。变更仅在镜像构建时生效。
