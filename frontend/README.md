# Agent 应用平台管理前端

Vite + React + TypeScript + shadcn/ui 管理控制面，通过同源 `/api` 连接后端，使用受保护会话、CSRF 和服务端权限校验。当前已提供应用、Agent、人员与授权、外部身份、运行记录、工具资源、凭据及运行配置管理。

## 知识库管理

入口为“工具资源 → 知识库”（`/platform/resources`）。资源列表维护知识库、内容连接、索引、验证与发布；运维面板提供构建、启动、停止、服务状态、采集计划、立即同步、日期补采、重试和安全事件。页面轮询持久任务，刷新页面不停止后台工作；长任务不在浏览器或 API 请求线程里执行。

“检索向量模型”对应 `knowledge-embedding-online`，负责查询向量化；“后台模型”负责文档入库向量化；“重排模型”负责候选文档排序。字段解释、首次安装与运行边界见[知识库运维手册](../knowledge/OPERATIONS.md)。

## 本地开发

容器构建使用 Node.js 22 和 npm：

```sh
cd frontend
npm ci
npm run dev
```

Vite 默认通过 `/api` 代理到 `http://127.0.0.1:8000`，可用 `VITE_DEV_API_TARGET` 指向已准备的后端。需要后端开启 `FEATURE_WEB_ADMIN` 并具备有效登录账号；本地页面不是免认证的演示入口。

```sh
npm run lint
npm run typecheck
npm run test
npm run build
```

`npm run preview` 仅用于检查构建产物，正式部署使用 `frontend/Dockerfile` 和 Nginx。已安装知识运维的环境，重建/更新 `admin-web` 应沿用原项目名、安装时的 Compose 扩展和环境文件；前端改动不需要重建知识向量索引。

## 目录边界

```text
src/app                  # 路由、Providers、认证门禁与平台 Shell
src/contexts             # 应用、Agent、身份、授权、运行、平台治理等领域
src/shared/api           # HTTP Client、CSRF、错误与请求关联
src/shared/presentation  # 跨领域展示组件
src/components/ui        # shadcn/ui 基础组件
```

目录及权限边界详见[Admin Web 当前实现](../docs/architecture/admin-web-mvp.md)。`src/mocks/dashboard.ts` 仍保留导航定义和旧预览夹具；其中演示数字不是运行数据，不能用于验收当前服务。按钮可见性不替代后端授权，前端不持有 Docker socket、数据库连接或采集凭据明文。
