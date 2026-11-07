## Why

当前 MES 工程仅存在于本机目录，缺少可由其他工作目录和 Docker 容器访问的 SVN 仓库。需要建立本地仓库并提供容器内检出到指定目录的入口，便于后续验证源码版本和知识更新。

## What Changes

- 提供独立的本地 SVN 服务部署入口及持久化仓库目录。
- 从 `/Users/mhz/Develop/enterprise_agent/ones知识库/项目代码` 导入首个版本，初始选择 `set_server`、`set_web/EBR`、`set_web/JTH`。选中工程完整导入，不套用知识提取的文件过滤规则。
- 管理页面允许输入已登记 SVN 仓库地址、浏览并多选其文件和子目录，随后由 Docker 后台检出完整文件。
- 提供 Docker 内固定 SVN 版本的检出入口，通过显式绑定挂载落到操作者指定的宿主机目录；检出不覆盖来源目录或已有人工修改。
- 明确 SVN 仓库、普通工作副本、知识库不可变源码快照三个目录的职责；复用现有 SVN 采集器与来源登记，不将可变工作副本直接交给提取 Runtime。
- 记录首次导入和真实网络检出的版本、文件范围与摘要验证。保持模型提取关闭，不自动发布知识快照。

## Capabilities

### New Capabilities

无独立新领域。

### Modified Capabilities

- `platform-operations`：本地 SVN 服务、工程导入、容器检出目录及版本核验的部署合同。

## Impact

- 预计涉及独立 Compose 配置、SVN 服务镜像、部署脚本、针对性测试和操作说明。
- 当前代码事实：`CodeSourceRegistry` 仅允许部署者登记目标；`SvnCodeSource` 的实际网络连接仅接受 HTTPS，并核验仓库 UUID、分支和 revision；`SvnSourceAdmission` 已实现固定版本准入和不可变快照发布。现有链路尚未证明本次本地 SVN 的真实网络接入。
- 不修改现有 ONES 内容和索引，不修改 MES 原始源码，不向提取 Agent 开放 SVN 写权限或数据库写权限。

## 已确认的部署参数

- 服务只对这台 Mac 与本项目 Docker 容器开放，不绑定局域网地址。
- 默认检出目录为容器 `/var/lib/code-svn/checkout` 对应项目 `.local/code-svn/checkout`，支持部署者显式指定其他目录。
- SVN 是完整工程的版本存储，导入和普通检出不自动过滤配置、依赖、二进制或生成物；不打印文件正文。知识提取准入另行执行，不将完整工程直接扩大为模型可读范围。
- 普通工作副本不得覆盖原工程或不可变知识源码快照；模型提取保持关闭。

用户已明确目录多选用于从 SVN 拉取，不需要本地工程上传的网页文件选择器。
