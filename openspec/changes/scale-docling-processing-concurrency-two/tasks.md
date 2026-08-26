## 1. Profile与持久化协调

- [x] 1.1 新增加法migration，创建恰好两个Docling静态槽位、owner唯一约束、lease/隔离状态和Processing Worker时效心跳存储，并用migration回归证明不会改写旧Profile、Publication、Job、run或Representation。
- [x] 1.2 在File Service repository实现按work identity原子取得、同owner接管、续租、确定释放和隔离槽位，覆盖双事务争抢、lease过期不得跨owner窃取及重复释放测试。
- [x] 1.3 增加受Service Principal保护的File Service内部admission与Worker心跳接口，限制请求/响应为稳定ID和安全状态，并验证Worker无PostgreSQL凭据且诊断不泄露文件、task或Secret信息。
- [x] 1.4 将`docling-layout-ocr-v2`的全局Docling并发和单parent图片并发固定为`2`，更新完整Profile hash，并让Processing Worker从代码Profile派生/校验hash与模型digest而不要求部署者逐环境填写这两个值。

## 2. 双Worker处理与恢复

- [x] 2.1 把parent和picture Docling阶段接入“原子claim、取得/恢复槽位、submit或resume、持久化结果、确定释放、ack”顺序，保持assembly不申请槽位。
- [x] 2.2 实现未取得槽位时不提交Docling、不增加attempt的有界重新等待，并保持每实例单消费者和RabbitMQ `prefetch=1`。
- [x] 2.3 实现Worker lease续租、同work identity接管和外部task状态不明时槽位隔离，增加submit前崩溃、submit后崩溃、single-use fetch后崩溃及重复消息回归测试。
- [x] 2.4 实现每实例不透明ID安全心跳与聚合就绪，覆盖一个实例缺失、第三实例残留、Profile/队列漂移、槽位隔离和完整双实例READY测试。

## 3. 固定Compose拓扑

- [x] 3.1 用共享Compose配置定义保留现有服务名的两个显式Processing Worker实例，确保相同镜像、角色、队列、Profile与资源约束且普通`docker compose up -d`无需`--scale`。
- [x] 3.2 将唯一`docling-serve`固定为local engine、single-use results、共享模型和两个local execution workers，并保持Docling模型digest随代码/镜像版本固化而非环境手工修改。
- [x] 3.3 扩展Compose契约测试，验证恰好两个Processing Worker、单实例并发`1`、单个Docling双执行器、两个槽位期望、无Redis/RQ/Ray、无第二个Docling以及Profile/hash/digest跨代码和Compose一致。
- [x] 3.4 执行`docker compose config --quiet`和镜像构建资源验证；若`4 CPU/8 GiB` Docling固定上限无法稳定承载双执行器，同步上调固定Compose资源和运维前提后重新验证。

## 4. Profile hash切换与应用重发布

- [x] 4.1 调整Business Application控制面读模型，使旧hash Revision/Publication/Deployment继续可列出、查看和编辑，同时仅将文档处理组件标记为`CONFIGURED_UNAVAILABLE`及稳定过期原因。
- [x] 4.2 实现从旧hash应用创建新Revision时按相同Profile code解析当前完整Profile并冻结新hash，保持旧事实不可变，并增加后端与管理端回归测试。
- [x] 4.3 在激活预检中拒绝旧hash Publication但不阻断管理服务；验证管理员可以发布并显式激活当前hash Revision且系统不自动改绑旧route、Job或run。
- [x] 4.4 增加部署只读预检，按状态统计旧hash非终态parent、picture和状态不明外部task；非零时失败关闭，只剩历史终态引用时允许切换。

## 5. 验收与运维交付

- [x] 5.1 增加十个受支持文件并发集成测试，断言每文件独立run/请求、最大两个Docling work在途、其余可恢复等待、最终无重复Representation或消息丢失。
- [x] 5.2 在Compose实际重建后执行十文件全链路验收，并在处理中终止一个Processing Worker验证同owner恢复、并发不超过二且最终结果完整。
- [x] 5.3 更新文档处理运行手册，给出无需改参数的build/up命令、旧hash排空、进入应用重新发布、聚合诊断、槽位隔离处置及非破坏性回滚步骤。
- [x] 5.4 运行受影响单元/集成测试、Ruff、Compose配置校验、严格OpenSpec校验和`git diff --check`，保存代码版本、镜像digest、Profile hash、队列/槽位安全计数及业务E2E结果，且不得仅以容器healthy声明完成。
