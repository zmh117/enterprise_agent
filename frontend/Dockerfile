FROM node:22-alpine AS build
WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/turbo.json frontend/.npmrc ./
COPY frontend/apps/admin-web/package.json ./apps/admin-web/package.json
COPY frontend/packages/api-client/package.json ./packages/api-client/package.json
COPY frontend/packages/config/package.json ./packages/config/package.json
COPY frontend/packages/ui/package.json ./packages/ui/package.json
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm --filter @enterprise-agent/admin-web build

FROM nginx:1.29-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/apps/admin-web/dist /usr/share/nginx/html
EXPOSE 80
