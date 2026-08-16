# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:latest
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 frontend/docker-entrypoint.d/10-require-web-admin.sh /docker-entrypoint.d/10-require-web-admin.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
