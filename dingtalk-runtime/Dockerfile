FROM node:22-alpine AS build
WORKDIR /app
COPY dingtalk-runtime/package.json dingtalk-runtime/package-lock.json ./
RUN npm ci
COPY dingtalk-runtime/tsconfig.json dingtalk-runtime/eslint.config.js ./
COPY dingtalk-runtime/src ./src
COPY dingtalk-runtime/test ./test
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY dingtalk-runtime/package.json dingtalk-runtime/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
USER node
EXPOSE 8081
CMD ["node", "dist/src/main.js"]
