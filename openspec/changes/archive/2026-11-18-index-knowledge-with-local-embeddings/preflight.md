# 首次实现预检与暂停记录（历史快照，2026-09-17）

更新：用户了解 bin/safetensors/ONNX 差异后回复“同意继续”。按最近讨论选择直接使用固定官方 PyTorch 权重、校验摘要、显式 weights_only=True 和离线非特权运行；不增加转换或 ONNX。下文保留此前预检和未采用转换建议的历史，当前决策以更新后的 design 为准。

以下为首次暂停时的预检快照（当时 1/17），不是当前部署状态。用户已确认继续；当前实现、下载、测试和运行状态见同目录 `tasks.md` 与 `evidence.md`。

## 已核实

- 本机 Docker：aarch64、10 CPU、16748032000 bytes 内存；Compose 仅 PostgreSQL 运行且 healthy。
- 实际数据库 head=133；document=5000、chunk_set=5000、chunk=8309。
- 唯一 chunk profile_hash：`edd49b9698781b2e473dfae2fcd3410de631a4ddbcc27468cd55bb35ba55fd35`。
- 全部块 embedding_hash 按 id 排序拼接后 SHA256：`a65ef0bef92d92ca210ce05a5b5a2d045026ed22d6d89f1da56425934682b612`。仅输出聚合计数和摘要，没有读取到会话或打印真实正文。
- 模型官方 revision：`5617a9f61b028005a4858fdac845db406aefb181`。
- 官方 dense 权重文件大小 2271145830 bytes，LFS SHA256：`b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`；来自公开元数据，未下载文件。
- Python `3.12.12-slim-bookworm` 镜像索引 digest：`sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c`。
- Qdrant `v1.17.0` 镜像索引 digest：`sha256:f1c7272cdac52b38c1a0e89313922d940ba50afd90d593a1605dbbc214e66ffb`；包含 linux/arm64 manifest。这里只核验远程 manifest，未拉取/运行新镜像。
- 查询公开 PyPI 元数据确认存在 PyTorch 的 Python 3.12 aarch64 wheel；尚未解析完整依赖锁，也未证明模型镜像可构建。

## 暂停原因

design 第 2 节约定只取 safetensors，但官方固定 revision 文件清单仅提供 `pytorch_model.bin` 形式的 dense 权重，没有 `.safetensors`。不得自行改用第三方转换模型或取消安全加载约束。

[官方固定版本文件清单](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181)

## 建议的待批准调整

保持 BGE-M3 模型及 revision 不变：

1. 下载官方固定版本的 bin，校验来源与文件 SHA256，下载阶段不挂载业务数据/凭据。
2. 新增一次性离线转换步骤：容器无网络、无业务卷/凭据、非特权且限制资源；使用已核实支持 ARM64 的受支持 PyTorch，显式 `weights_only=True` 读取纯 tensor state_dict；不自动 allowlist 任意类、不用不受限 pickle fallback。
3. 转换为 safetensors，校验键、形状、dtype、张量值以及合成输入的向量一致性；生成转换输出的文件清单和摘要。
4. 正式推理仍然只加载校验通过的 safetensors，只读/离线，不把 bin 装入推理文件集合。

`weights_only=True` 只能缩小反序列化攻击面，不保证消除全部风险，仍需来源固定、隔离和资源限制。若转换不能在这些约束下完成，则停止，不自动放宽。参见 [PyTorch 安全限制](https://docs.pytorch.org/docs/2.14/notes/serialization.html#weights-only-security)。

替代方案是另选官方直接提供 safetensors 的模型，但需要重新确认模型、维数和向量配置。本轮尚未批准或执行上述任一调整。

## 未受影响的边界

缺陷文本不外发、Qdrant 本机 Docker、原九表不变、不开 Web/MCP/授权等范围保持不变。待用户确认后再更新 design/spec/tasks 并继续任务 1.2，未将剩余任务标为完成。
