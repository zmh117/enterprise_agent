import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

test("production image is multi-stage, non-root and never installs at startup", async () => {
  const dockerfile = await readFile(new URL("../../Dockerfile", import.meta.url), "utf8");

  assert.match(dockerfile, /^FROM node:22-trixie-slim AS build/m);
  assert.match(dockerfile, /^FROM node:22-trixie-slim AS runtime/m);
  assert.match(dockerfile, /^USER node$/m);
  assert.match(dockerfile, /^CMD \["node", "dist\/src\/main\.js"\]$/m);
  assert.doesNotMatch(dockerfile, /CMD .*npm (?:install|ci)/);
  assert.doesNotMatch(dockerfile, /claude-agent-sdk==|pip install|python -m pip/i);
});

test("deployment preflight checks exact runtime versions, grants and secret permissions", async () => {
  const dockerfile = await readFile(new URL("../../Dockerfile", import.meta.url), "utf8");
  const preflight = await readFile(
    new URL("../../scripts/preflight.mjs", import.meta.url),
    "utf8"
  );
  assert.match(dockerfile, /COPY --chown=node:node package-lock\.json \.\/package-lock\.json/);
  assert.match(
    dockerfile,
    /COPY --chown=node:node contracts\/v1\/protocol\.schema\.json \.\/contracts\/v1\/protocol\.schema\.json/
  );
  assert.match(
    dockerfile,
    /COPY --chown=node:node scripts\/preflight\.mjs \.\/scripts\/preflight\.mjs/
  );
  assert.match(preflight, /package-lock\.json/);
  assert.match(preflight, /--version/);
  assert.match(preflight, /AGENT_RUNTIME_CLI_VERSION/);
  assert.match(preflight, /has_column_privilege/);
  assert.match(preflight, /has_table_privilege/);
  assert.match(preflight, /APP_CONFIG_MASTER_KEY_FILE/);
  assert.match(preflight, /MODEL_PROBE_AUTH_TOKEN_FILE/);
  assert.match(preflight, /RUNTIME_GRANT_PUBLIC_KEY_FILE/);
  assert.match(preflight, /mode: staticOnly \? "static" : "deployment"/);
});
