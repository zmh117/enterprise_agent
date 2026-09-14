## Context

当前 ScopeBindingsEditor 的 Environment/Base 回调无条件写入 `workshop_code: ""`。新建和编辑请求直接序列化表单，Loki 后端仅允许 environment_code、base_code、selector_conditions，因而拒绝该空字段。用户已确认修复前端、不放宽后端、不改变 DB/Redis 范围。

## Goals / Non-Goals

目标：Loki 新建和编辑可以保存有效范围；切换环境/基地不制造不支持字段；已有前端状态中的空占位字段不再阻塞保存。

非目标：支持 Loki Workshop、忽略任意未知字段、迁移已有资源、自动发布、修改连接配置、影响其他 Provider。

## Decisions

1. 在两处范围目标回调中，仅为非 Loki 资源生成 Workshop 重置字段，保留原有父子联动行为。
2. 在资源 API 适配器使用共用的保存载荷构造函数，为 Loki scope_bindings 创建副本并移除空串、null 或 undefined 的 Workshop 占位字段；创建和保存 Draft 均调用它。不改变顶层资源身份字段，不原地修改 React 状态。
3. 不通用过滤所有未知字段，也不删除非空 Workshop；这些内容必须继续触发后端严格校验，避免把不支持的车间目标静默扩大为环境/基地目标。
4. 前端测试直接断言完整范围对象与字段不存在，不只用允许额外字段的部分匹配；覆盖两条 HTTP 路径、环境/基地变化、旧空字段、DB/Redis 保持不变。后端补充拒绝非法字段与合法 Loki 范围对照测试。

## Risks / Trade-offs

- 旧浏览器缓存仍发送旧载荷 → 需更新前端部署并刷新页面；后端不为旧前端放宽数据范围契约。
- 过度清理可能掩盖非法范围 → 仅清理已确认无业务含义的空占位值，其他值保留并拒绝。
- Mock 保存不能证明真实资源更新 → 单独标注前端回归与后端契约测试，不自动修改用户资源来验收。

## Migration Plan

无数据库迁移，无后端部署依赖；更新 admin-web 后刷新浏览器，再保存原有 Draft。无需归档重建或重新配置凭据。回滚只需恢复前端版本。
