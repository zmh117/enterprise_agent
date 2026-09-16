# Agent、业务应用、平台与辅助文档对账

本次按当前代码调整三个领域并保留仍适用的细粒度规则，移除静态原型、旧阶段与历史拼接注释。原文均保存在本记录original-specs，未改产品代码。

## 主要修正

- Agent管理已支持按资源权限编辑多个Python Agent，默认Agent不再独占编辑；合法旧Python协议/工具策略Publication可历史只读恢复，TypeScript完整详情不能假称兼容。依据agent_config/application/service.py、api/controller.py及前端agent-profiles。
- MCP Envelope允许代码固定且带effect/policy的受治理mutation；应用显式发布激活后才改变后续运行，单独发布Agent不自动更新应用。依据business_application/application/mcp_tool_composition.py与authorization_center/infrastructure/repository.py。
- Workflow规范化node/edge为唯一草稿源，当前仍是配置资产，不宣称已实现图执行引擎。依据workflow/application/graph_facts.py、validation.py与business_application/domain/runtime.py。
- 当前local应用路由支持钉钉私聊、群聊和Webhook；部署environment与Tool调用目标分开。无应用角色不能回退旧项目/Agent允许策略。依据business_application/domain/runtime.py与authorization_center/application/service.py。
- 最大工具调用支持500；当前应用保存0归一化30，冻结有效零值的Runtime语义独立。仅修正文档，未借此改变行为。依据business_application/domain/policies.py和job/domain/execution_policy.py。
- Runtime当前1.5并支持1.4；不把旧119/120迁移、重置和切换阶段要求当成当前常态部署步骤。迁移100..132共33项，fresh与legacy042 adoption边界分开。依据runtime_protocol.py、shared/migrations.py、schema_baseline.py。
- 文件并发与固定跨平台模型摘要、Profile hash变更后的管理可用性、知识离线存储、资源角色随Revision进入hash等已合入。knowledge不等于Agent检索/Embedding/OCR/Qdrant已实现。
- 资源placement为自定义角色，不限cloud/edge；Loki仍禁止非空。依据shared/resource_role.py。
- Stream SDK需要受信AppSecret：API经内部认证与runtime lease向DingTalk Runtime提供，不能写成API和SDK绝不接收；普通管理、Job、模型和日志仍不得获得。依据managed_channel/api/controller.py、application/service.py、dingtalk-runtime/src/sdk-client.ts。
- 外部worker固定分派、启动合同检查、Compose heartbeat文件health、应用组合前置校验和Provider真实权限验证是不同事实；发布不调用worker health验证全部Provider权限。依据services/dingtalk_mcp_server/worker.py、mcp_tool_composition.py和docker-compose.yml。
- API核心ready只计算DB/schema/RabbitMQ/Master Key；Dashboard业务计数、领域探测和真实工具验收分开，不宣称一次ready证明全链。
- Makefile的pnpm与GitHub CI的npm入口并未统一；文档按实际工作目录和锁文件说明，未修改构建或依赖。

上述模块简写相对于backend/app/modules/，shared简写相对于backend/app/shared/。精确证据与合同位于相关主规格。

## 同步的当前辅助文档

更新根README、backend README、docs索引、ONES架构摘要、Schema空库/升级手册及项目上下文；去除旧仅TXT、仅两个ONES只读工具、TypeScript可执行、迁移119和Runtime1.3主链等误导。日期化验证和旧archive不重写。

AGENTS.md、openspec/config.yaml与specs导航共同限定默认按领域读取canonical，不默认读取历史。新change应映射当前领域，不能复制旧碎片路径。

## 验证边界

本次文档Strict OpenSpec、Markdown链接与差异空白检查通过。代码引用候选均存在。独立内存SQLite执行33项迁移并通过head132校验；没有读取现网数据、导入业务文本、外部调用、镜像部署或新Publication/Job验收。
