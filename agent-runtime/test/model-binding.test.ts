import assert from "node:assert/strict";
import {
  createCipheriv,
  createHash,
  randomBytes
} from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import secretFixture from "../contracts/v1/golden/platform-secret-python.json" with { type: "json" };
import { loadRuntimeConfig } from "../src/config.js";
import type { AgentExecutionRequestV1 } from "../src/generated/contracts.js";
import {
  ModelBindingError,
  ModelBindingResolver,
  type RuntimeSqlClient
} from "../src/model-binding.js";
import {
  PlatformSecretDecryptor,
  PlatformSecretError
} from "../src/platform-secret.js";
import executionRequestFixture from "../contracts/v1/golden/execution-request.json" with { type: "json" };

const MASTER_KEY = secretFixture.master_key;

function runtimeConfig() {
  return loadRuntimeConfig({
    RUNTIME_GRANT_PUBLIC_KEY_FILE: "/run/secrets/runtime-grant-public.pem",
    MODEL_PROBE_AUTH_TOKEN_FILE: "/run/secrets/model-probe-auth-token",
    DATABASE_URL: "postgresql://runtime:secret@database/enterprise_agent",
    APP_CONFIG_MASTER_KEY_FILE: "/run/secrets/app-config-master-key",
    MODEL_PROVIDER_ALLOWED_HOSTS: "api.deepseek.com",
    MCP_SERVER_ALLOWED_HOSTS: "ones-mcp.internal,data-mcp.internal"
  });
}

function request(): AgentExecutionRequestV1 {
  return structuredClone(executionRequestFixture) as AgentExecutionRequestV1;
}

function config(model = "deepseek-chat") {
  return {
    schema_version: 1,
    protocol: "anthropic_compatible",
    base_url: "https://api.deepseek.com/anthropic",
    model,
    default_opus_model: model,
    default_sonnet_model: model,
    default_haiku_model: model,
    subagent_model: model,
    effort_level: "max"
  };
}

function configHash(value: Record<string, unknown>): string {
  const canonical = JSON.stringify(
    Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
  );
  return createHash("sha256").update(canonical).digest("hex");
}

function encryptedSecret(
  plaintext: string,
  secretId: string,
  version: number,
  nonce = randomBytes(12)
) {
  const key = Buffer.from(MASTER_KEY.slice("EA_MASTER_KEY_V1:".length), "base64url");
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  cipher.setAAD(Buffer.from(`platform-secret|v1|${secretId}|${version}`));
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    ciphertext: Buffer.concat([ciphertext, tag]).toString("base64url"),
    nonce: nonce.toString("base64url"),
    key_id: createHash("sha256").update(key).digest("hex").slice(0, 16)
  };
}

function row(
  revisionId: string,
  modelConfig: Record<string, unknown>,
  plaintext = "fixture-api-key-not-secret",
  version = 7
) {
  const secretId = `${revisionId}-secret`;
  const encrypted = encryptedSecret(plaintext, secretId, version, Buffer.alloc(12, version));
  return {
    revision_id: revisionId,
    revision_status: "ready",
    connection_status: "ready",
    connection_protocol: "anthropic_compatible",
    config_json: JSON.stringify(modelConfig),
    config_hash: configHash(modelConfig),
    secret_id: secretId,
    secret_provider: "encrypted_db",
    secret_status: "enabled",
    active_version: version,
    ciphertext: encrypted.ciphertext,
    nonce: encrypted.nonce,
    key_id: encrypted.key_id,
    algorithm: "AES-256-GCM-AAD-V1",
    version_status: "active"
  };
}

class FakeDatabase implements RuntimeSqlClient {
  constructor(readonly rowsByRevision: Record<string, Record<string, unknown>>) {}

  async query<T extends Record<string, unknown>>(
    _sql: string,
    values: readonly unknown[]
  ): Promise<{ rows: T[] }> {
    const value = this.rowsByRevision[String(values[0])];
    return { rows: value ? [value as T] : [] };
  }
}

test("Node decrypts the Python AES-GCM-AAD golden fixture", () => {
  const decryptor = PlatformSecretDecryptor.fromMaterial(secretFixture.master_key);

  assert.equal(
    decryptor.decrypt({
      secretId: secretFixture.secret_id,
      version: secretFixture.version,
      ciphertext: secretFixture.ciphertext,
      nonce: secretFixture.nonce,
      keyId: secretFixture.key_id,
      algorithm: secretFixture.algorithm
    }),
    secretFixture.plaintext
  );
});

test("Platform Secret fails closed for wrong key, tag tampering and algorithms", () => {
  const encrypted = {
    secretId: secretFixture.secret_id,
    version: secretFixture.version,
    ciphertext: secretFixture.ciphertext,
    nonce: secretFixture.nonce,
    keyId: secretFixture.key_id,
    algorithm: secretFixture.algorithm
  };
  const wrongKey = `EA_MASTER_KEY_V1:${Buffer.alloc(32, 9).toString("base64url")}`;
  assert.throws(
    () => PlatformSecretDecryptor.fromMaterial(wrongKey).decrypt(encrypted),
    (error: unknown) =>
      error instanceof PlatformSecretError && error.code === "runtime_secret_key_mismatch"
  );
  assert.throws(
    () =>
      PlatformSecretDecryptor.fromMaterial(MASTER_KEY).decrypt({
        ...encrypted,
        ciphertext: `${encrypted.ciphertext.slice(0, -1)}A`
      }),
    (error: unknown) =>
      error instanceof PlatformSecretError && error.code === "runtime_secret_decrypt_failed"
  );
  assert.throws(
    () =>
      PlatformSecretDecryptor.fromMaterial(MASTER_KEY).decrypt({
        ...encrypted,
        algorithm: "AES-CBC"
      }),
    (error: unknown) =>
      error instanceof PlatformSecretError && error.code === "runtime_secret_algorithm_unsupported"
  );
});

test("resolver reads only the frozen revision and returns an isolated credential", async () => {
  const value = request();
  const modelConfig = config();
  const modelRow = row(value.model_connection.revision_id, modelConfig);
  value.model_connection.config_hash = modelRow.config_hash as string;
  const resolver = new ModelBindingResolver(
    new FakeDatabase({ [value.model_connection.revision_id]: modelRow }),
    PlatformSecretDecryptor.fromMaterial(MASTER_KEY),
    runtimeConfig(),
    async () => ["203.0.113.10"]
  );

  const binding = await resolver.resolve(value);

  assert.equal(binding.connectionRevisionId, value.model_connection.revision_id);
  assert.equal(binding.model, "deepseek-chat");
  assert.equal(binding.apiKey, "fixture-api-key-not-secret");
  assert.equal(Object.hasOwn(binding, "secret_ref"), false);
});

test("resolver rejects disabled credentials, config drift and private DNS", async () => {
  const value = request();
  const modelRow = row(value.model_connection.revision_id, config());
  value.model_connection.config_hash = modelRow.config_hash as string;
  const decryptor = PlatformSecretDecryptor.fromMaterial(MASTER_KEY);

  await assert.rejects(
    new ModelBindingResolver(
      new FakeDatabase({
        [value.model_connection.revision_id]: { ...modelRow, secret_status: "disabled" }
      }),
      decryptor,
      runtimeConfig(),
      async () => ["203.0.113.10"]
    ).resolve(value),
    (error: unknown) =>
      error instanceof ModelBindingError && error.code === "runtime_model_binding_disabled"
  );

  const drifted = { ...modelRow, config_json: JSON.stringify({ ...config(), model: "changed" }) };
  await assert.rejects(
    new ModelBindingResolver(
      new FakeDatabase({ [value.model_connection.revision_id]: drifted }),
      decryptor,
      runtimeConfig(),
      async () => ["203.0.113.10"]
    ).resolve(value),
    (error: unknown) =>
      error instanceof ModelBindingError &&
      error.code === "runtime_model_config_integrity_failed"
  );

  await assert.rejects(
    new ModelBindingResolver(
      new FakeDatabase({ [value.model_connection.revision_id]: modelRow }),
      decryptor,
      runtimeConfig(),
      async () => ["127.0.0.1"]
    ).resolve(value),
    (error: unknown) =>
      error instanceof ModelBindingError && error.code === "runtime_model_dns_rejected"
  );
});

test("active rotation and concurrent revisions never share credential state", async () => {
  const first = request();
  const second = request();
  second.invocation_id = "invocation-2";
  second.model_connection.revision_id = "model-connection-revision-2";
  const firstRow = row(first.model_connection.revision_id, config("model-a"), "key-a", 8);
  const secondRow = row(second.model_connection.revision_id, config("model-b"), "key-b", 9);
  first.model_connection.config_hash = firstRow.config_hash as string;
  second.model_connection.config_hash = secondRow.config_hash as string;
  const resolver = new ModelBindingResolver(
    new FakeDatabase({
      [first.model_connection.revision_id]: firstRow,
      [second.model_connection.revision_id]: secondRow
    }),
    PlatformSecretDecryptor.fromMaterial(MASTER_KEY),
    runtimeConfig(),
    async () => ["203.0.113.10"]
  );

  const [firstBinding, secondBinding] = await Promise.all([
    resolver.resolve(first),
    resolver.resolve(second)
  ]);

  assert.deepEqual(
    [firstBinding.model, firstBinding.apiKey, secondBinding.model, secondBinding.apiKey],
    ["model-a", "key-a", "model-b", "key-b"]
  );
});

test("PostgreSQL role grants keep platform reads column-bounded and ledger writes isolated", async () => {
  const sql = await readFile(
    new URL("../../../backend/maintenance/agent_runtime_grants.sql", import.meta.url),
    "utf8"
  );

  assert.match(sql, /REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public/);
  assert.match(
    sql,
    /GRANT SELECT \(id, protocol, status\)\s+ON model_connection/
  );
  assert.match(
    sql,
    /GRANT SELECT, INSERT, DELETE ON agent_runtime_terminal_ledger/
  );
  assert.doesNotMatch(
    sql,
    /GRANT (?:INSERT|UPDATE|DELETE|ALL)[^;]*ON (?:model_connection|model_connection_revision|platform_secret)/
  );
  assert.doesNotMatch(sql, /GRANT UPDATE|GRANT ALL/);
  assert.doesNotMatch(sql, /masked_summary|metadata_json|created_by/);
});
