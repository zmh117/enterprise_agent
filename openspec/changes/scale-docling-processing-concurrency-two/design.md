## Context

当前默认部署只有一个`file-processing-worker`，其RabbitMQ消费者固定`prefetch=1`且进程拒绝并发值不为`1`；单个`docling-serve`使用local engine、single-use result和一个local execution worker。`docling-layout-ocr-v2`同时把全局Docling并发和单parent图片并发固定为`1`。因此多文件消息可以排队，但Docling处理只能串行执行。

本变更跨越Compose、File Processing Worker、File Service持久化协调、实时就绪聚合和Business Application的不可变Profile发布边界。约束是继续使用RabbitMQ与PostgreSQL，不引入Redis/RQ/Ray；Docling task registry仍是单容器本地临时状态，不能成为平台事实源；Processing Worker不得直接获得数据库凭据；旧Publication和终态处理事实不得被追溯改写。

## Goals / Non-Goals

**Goals:**

- 默认`docker compose build`与`docker compose up -d`固定得到两个Processing Worker、一个Docling容器和两个Docling local execution workers。
- 把文档和图片Docling调用的严格全局上限提升到`2`，并在多Worker、重投递、崩溃和滚动重建下保持上限与幂等。
- Profile hash变化后，管理员仍能进入旧应用、创建新Revision、重新发布并显式激活。
- 用聚合运行证据和十文件业务验收证明能力，不把容器healthy当作完成标准。

**Non-Goals:**

- 不把多个用户文件合并为一个Docling请求，也不改变格式白名单、Docling options或Representation schema。
- 不部署第二个Docling容器，不引入粘性负载均衡、Redis、RQ、Ray或外部调度器。
- 不增加单个Worker进程内线程并发，不把并发数做成普通环境可调参数。
- 不自动迁移、删除或改写旧Publication、旧Job、历史run和Representation，不自动切换活动route。
- 不新增Agent Tool、MCP协议、Agent可见二进制或对象存储访问路径。

## Decisions

### 1. 使用两个单消费者Processing Worker，而不是单进程并发

Compose保留现有`file-processing-worker`服务并增加第二个显式服务实例；两者复用同一镜像、命令、角色bootstrap、Docling凭据、Profile hash和RabbitMQ队列契约，各自保持`FILE_PROCESSING_WORKER_CONCURRENCY=1`与`prefetch=1`。显式第二服务保证普通`up -d`无需`--scale`，并保持现有服务名可供兼容探针使用。公共配置应通过Compose extension/anchor复用，只有实例身份与服务名不同，避免两套配置漂移。

选择该方案是因为当前Handler同步覆盖submit、poll、fetch与持久化，单进程线程池会扩大连接、信号处理和readiness语义。单消费者进程故障域更清楚，RabbitMQ未确认消息也能自然重投递。仅把`prefetch`改为`2`不能产生执行并发；仅运行第二个Worker又不能形成严格全局上限，因此仍需要数据库admission。

### 2. 保持一个Docling容器，并把local execution workers固定为两个

`docling-serve`继续使用local engine、共享模型和single-use results，只把`DOCLING_SERVE_ENG_LOC_NUM_WORKERS`从`1`固定为`2`。两个Processing Worker始终通过同一内部服务身份提交、轮询并获取结果。

不选择横向扩展Docling容器：本模式的task registry和single-use结果位于实例本地，普通Compose DNS负载均衡不能保证submit、poll和fetch命中同一副本。也不引入Redis/RQ/Ray，因为并发`2`不需要新的调度系统，且会扩大Secret、持久化和恢复边界。

### 3. File Service用PostgreSQL维护两个静态Docling槽位

新增由File Service拥有的admission表，预置`slot_no=1,2`两行。每行保存owner kind、owner ID、Worker lease holder、lease到期时间、安全状态和时间戳；owner `(kind, id)`唯一。Processing Worker只能通过现有Principal认证的File Service内部接口执行以下操作，不直接连接PostgreSQL：

1. 在提交Docling前以`parent run`或`picture item`稳定身份申请槽位。
2. File Service在事务中先查找该owner已有槽位，再以行锁取得空槽位；不同owner并发争抢时只能一个成功。
3. Worker周期续租。lease holder只表示当前执行者，owner表示仍占用的Docling工作；lease过期只允许同一owner接管，不允许其它工作窃取。
4. 结果进入受控staging且不再依赖外部task，或task已确定终态/不存在后，Worker在状态提交事务中释放槽位。
5. 外部task是否仍存在无法确定时，槽位进入隔离状态并失败关闭；不得仅因deadline或Worker失联把它分配给第三个工作。

Assembly不调用Docling，因此继续使用现有assembly claim而不申请槽位。RabbitMQ message仍只携带稳定ID与Profile/correlation事实，槽位号、lease token和外部task详情不进入消息、Agent、审计或普通诊断。

选择PostgreSQL静态槽位而不是进程信号量，是因为两个Worker和滚动重建必须共享同一强一致上限；选择File Service内部API而不是Worker直连数据库，是为了保持File Service的数据与权限边界。静态两行比通用分布式信号量简单，且把上限直接编码为可迁移、可校验的事实。

### 4. 原子claim与槽位分别解决幂等和容量

现有parent run、picture item和assembly的条件更新claim继续作为状态所有权；新槽位只控制是否允许存在一个Docling在途工作，不能替代claim。为了确保等待容量不会增加attempt，parent和picture处理顺序为“以消息固定work identity取得/恢复槽位 → 原子claim work → submit或resume task → stage result/commit state → release slot → ack message”；File Service在准入时先校验该work identity确实绑定当前Profile。未取得槽位不claim、不创建新attempt、不提交Docling，消息按固定短退避重新可用。Assembly不申请槽位，继续直接使用既有原子claim。

Worker在submit后崩溃时，外部task ID和slot owner都已持久化；重投递只能以相同owner接管并继续poll/fetch。若Worker在submit前崩溃，相同owner接管后继续当前attempt。数据库唯一约束、Representation唯一约束和Outbox幂等键仍阻止重复发布。

### 5. Profile并发值固定为二并产生新hash

`docling-layout-ocr-v2`完整payload把`max_global_docling_concurrency`和`max_parent_picture_concurrency`都改为`2`，代码、Worker启动校验、Compose期望值和数据库槽位数必须一致；普通环境变量不能覆盖。该payload变化必然产生新Profile hash，镜像构建与Compose使用代码计算/校验的同一值，部署者不再手工改参数。

旧hash仍是不可变历史事实，但不再是当前可激活Profile。管理读模型必须把“管理服务可用”和“该Publication文档处理组件当前不可运行”分开：旧应用列表、详情和编辑入口继续返回，组件显示`CONFIGURED_UNAVAILABLE`及稳定过期原因。基于旧应用创建的新Revision重新解析同code的当前完整Profile并冻结新hash；发布、激活仍由管理员显式执行。

### 6. 聚合就绪由File Service的安全心跳和槽位状态产生

每个Processing Worker启动时生成不透明运行实例ID，并通过认证内部接口周期上报build/Profile、队列契约、Docling探针结论和过期时间，不上传主机名、文件信息、task ID或Secret。File Service聚合期望实例数`2`、有效且配置一致的实例数、Docling单实例/双执行器期望、队列依赖和两个槽位状态。

只有恰好两个合规实例且全部安全闸门可验证时才报告`READY`。一个实例丢失、出现第三实例、Profile漂移或槽位隔离时报告`CONFIGURED_UNAVAILABLE`与安全计数；数据库槽位仍保证即使拓扑漂移也不会超过二。该组件状态不得让Business Application管理API整体失败，旧应用仍可重发布。

### 7. 保留当前资源上限，使用验收决定是否在实现内上调固定值

初始实现保留Docling现有`4 CPU/8 GiB`和每个Processing Worker`1 CPU/2 GiB`的固定上限，利用`SHARE_MODELS=true`避免为两个local workers复制模型。完成前必须在目标CPU部署运行十文件验收并观察OOM、超时、队列等待和处理时长；若固定上限不足，实现任务必须同步调整Compose固定资源与运维前提后重新验收，不能通过降低安全限制、恢复并发`1`或暴露环境可调并发来绕过。

## Risks / Trade-offs

- [两个Docling执行器竞争CPU或内存，吞吐未达到两倍甚至OOM] → 保留共享模型，执行十文件资源验收；不足时在同一实现中上调并固定Compose资源前提。
- [Worker在外部task状态不明时退出导致槽位长期隔离] → 同owner可接管；只有确认task终态/不存在才释放，无法确认时显式不可用并由受控Docling恢复流程处理。
- [双Worker增加重复投递窗口] → 继续使用run/item/assembly原子claim、slot owner唯一约束、Representation唯一约束和Outbox幂等键。
- [Profile hash切换暂时使旧应用文档组件不可用] → 切换前排空旧hash工作，保留管理入口并提供创建新Revision、发布、显式激活的确定路径。
- [滚动部署短时出现一个或三个Worker心跳] → readiness失败关闭，槽位上限保持二；心跳按固定TTL淘汰，不自动扩大容量。
- [单Docling容器仍是可用性单点] → 这是local task状态一致性的有意取舍；依靠持久task ID、同run重试和确定失败恢复，不在本变更引入分布式Docling后端。

## Migration Plan

1. 在旧拓扑运行时执行只读预检，按旧Profile hash统计非终态parent run、picture item和状态不明的外部task；任一计数非零则停止切换并继续排空。
2. 备份PostgreSQL并构建全部受影响镜像。应用可回滚的加法migration，创建两个静态槽位和Worker心跳存储；migration不得改写旧Profile、Publication、Job、run或Representation。
3. 同一版本发布Profile payload、新hash、File Service admission API、双Worker Compose和Docling双local-worker配置，执行`docker compose up -d`。启动校验必须拒绝Profile、槽位数、Worker期望数或Docling执行器数不一致。
4. 等待聚合状态确认恰好两个Worker、一个Docling、两个执行器和两个可用槽位。此时旧hash应用仍可管理，但旧Publication不得重新激活。
5. 管理员从旧应用创建使用当前Profile的新Revision，完成发布与显式激活；逐个确认活动route只在激活后切换。
6. 使用十个受支持文件执行全链路验收，验证最大在途Docling工作为二、每文件独立run、无重复Representation、无消息丢失，并覆盖一个Worker崩溃与恢复。

回滚时先停止新文档工作准入并排空新hash非终态任务，再恢复旧代码、单Worker和Docling单执行器。新hash Publication在旧代码下保持只读且不可激活；操作者可显式重新激活仍受旧代码支持的旧hash Publication。加法表保留但旧代码不使用，不执行破坏性schema回退。

## Open Questions

无。资源固定值是否需要上调由实现阶段的目标环境十文件验收决定，但并发上限、拓扑和安全边界不因此变化。
