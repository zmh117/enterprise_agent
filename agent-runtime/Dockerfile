FROM node:22-trixie-slim AS build

WORKDIR /opt/agent-runtime
ENV NODE_ENV=development

COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json tsconfig.build.json ./
COPY contracts ./contracts
COPY src ./src
RUN npm run build \
    && npm prune --omit=dev --no-audit --no-fund \
    && npm cache clean --force

FROM node:22-trixie-slim AS runtime

ENV NODE_ENV=production \
    NODE_OPTIONS=--enable-source-maps \
    TMPDIR=/tmp/agent-runtime
WORKDIR /opt/agent-runtime

RUN mkdir -p /tmp/agent-runtime \
    && chown node:node /tmp/agent-runtime \
    && chmod 0700 /tmp/agent-runtime

COPY --chown=node:node --from=build /opt/agent-runtime/package.json ./package.json
COPY --chown=node:node package-lock.json ./package-lock.json
COPY --chown=node:node scripts/preflight.mjs ./scripts/preflight.mjs
COPY --chown=node:node scripts/entrypoint.sh ./scripts/entrypoint.sh
COPY --chown=node:node --from=build /opt/agent-runtime/node_modules ./node_modules
COPY --chown=node:node --from=build /opt/agent-runtime/dist ./dist
RUN node --input-type=module -e "await import('./dist/src/runtime-contracts.js'); await import('./dist/src/protocol.js')"

USER node
EXPOSE 8090
ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["node", "dist/src/main.js"]
