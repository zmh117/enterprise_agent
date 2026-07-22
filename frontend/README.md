# Frontend (shadcn dashboard-01)

Vite + React + TypeScript + shadcn/ui（`nova` preset，`dashboard-01` 模板）。

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
npm run build
npm run preview
npx shadcn@latest add button
```

## Docker

仓库根目录：

```bash
docker compose up -d --build admin-web
```

映射端口默认 `8080`，`/api/` 代理到 `api-server:8000`。
