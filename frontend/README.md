# Agent 应用平台前端原型

Vite + React + TypeScript + shadcn/ui 的静态控制面原型，用于评审业务应用、Workflow、API Capability 与多外部身份的信息架构。

## 原型边界

- 不实现登录、业务路由或后端 API Client。
- 不读取数据库，不建立 fetch、XHR、WebSocket 或 EventSource 连接。
- 不执行创建、编辑、绑定、测试、保存、发布或回滚命令。
- 不展示真实人员、外部账号、运行记录、连接信息和凭据。
- `src/mocks/dashboard.ts` 中所有 `DEMO` 标识、数量、环境和时间均为虚构 fixture。
- Agent Web 只展示受控业务 Capability，不提供底层数据源、查询语言或任意外部地址入口。

## 本地开发

```bash
cd frontend
npm install
npm run dev
```

默认打开 Vite 开发服务器（通常 `http://127.0.0.1:5173`）。按 `d` 切换深浅色。

## 常用命令

```bash
npm run typecheck
npm run test
npm run build
npm run preview
npx shadcn@latest add button
```

## 目录边界

```text
src/app                  # Shell 与导航装配
src/contexts             # 实际存在的业务展示上下文
src/shared/presentation  # 跨上下文展示组件
src/components/ui        # shadcn CLI 生成组件
src/mocks                # 明确脱敏的本地原型 fixture
```
