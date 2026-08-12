import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { EventEmitter, once } from "node:events";
import type { IncomingMessage, ServerResponse } from "node:http";
import { Readable } from "node:stream";
import { test } from "node:test";

import { SignJWT } from "jose";

import executionRequestFixture from "../contracts/v1/golden/execution-request.json" with { type: "json" };
import {
  assertSafeRemoteUrl,
  loadRuntimeConfig,
  RuntimeConfigError
} from "../src/config.js";
import { DeterministicFakeProviderRuntimeExecutor } from "../src/fake-provider.js";
import type {
  AgentExecutionRequestV1,
  RuntimeEvent,
  RuntimeProvenance
} from "../src/generated/contracts.js";
import { RuntimeGrantError, RuntimeGrantVerifier } from "../src/grant.js";
import {
  InvocationConflictError,
  InvocationRegistry,
  type RuntimeExecutor
} from "../src/invocation-registry.js";
import { sanitizeLogValue, StructuredLogger } from "../src/logger.js";
import type { ReadinessProbe } from "../src/readiness.js";
import { createRuntimeRequestHandler } from "../src/server.js";
import type {
  PersistedTerminal,
  TerminalLedger
} from "../src/terminal-ledger.js";

const NOW_SECONDS = 1_800_000_000;

function runtimeEnv(): NodeJS.ProcessEnv {
  return {
    AGENT_RUNTIME_HOST: "127.0.0.1",
    AGENT_RUNTIME_PORT: "8090",
    AGENT_RUNTIME_LOG_LEVEL: "info",
    AGENT_RUNTIME_LEDGER_TTL_SECONDS: "3600",
    AGENT_RUNTIME_CLI_VERSION: "2.1.226",
    RUNTIME_GRANT_PUBLIC_KEY_FILE: "/run/secrets/runtime-grant-public.pem",
    MODEL_PROBE_AUTH_TOKEN_FILE: "/run/secrets/model-probe-auth-token",
    DATABASE_URL: "postgresql://runtime:secret@database/enterprise_agent",
    APP_CONFIG_MASTER_KEY_FILE: "/run/secrets/app-config-master-key",
    MODEL_PROVIDER_ALLOWED_HOSTS: "api.anthropic.com,provider.internal",
    MCP_SERVER_ALLOWED_HOSTS: "tool-mcp,ones-mcp",
    MCP_TOOL_SERVER_URL: "http://tool-mcp:9103/mcp",
    ONES_MCP_SERVER_URL: "http://ones-mcp:9104/mcp"
  };
}

function request(): AgentExecutionRequestV1 {
  return structuredClone(executionRequestFixture) as AgentExecutionRequestV1;
}

function provenance(value = request()): RuntimeProvenance {
  return {
    runtime_kind: "typescript-v1",
    runtime_version: "0.1.0",
    protocol_version: "1.0",
    sdk_version: "0.3.226",
    cli_version: "2.1.226",
    model_connection_revision_id: value.model_connection.revision_id,
    model_connection_config_hash: value.model_connection.config_hash
  };
}

function keyPair(): ReturnType<typeof generateKeyPairSync> {
  return generateKeyPairSync("ed25519");
}

async function grant(
  privateKey: ReturnType<typeof keyPair>["privateKey"],
  value = request(),
  overrides: Record<string, unknown> = {},
  expiresAt = NOW_SECONDS + value.limits.timeout_seconds
): Promise<string> {
  return new SignJWT({
    azp: "agent-worker",
    runtime_kind: value.runtime_kind,
    sub: value.app_user_id,
    job_id: value.job_id,
    invocation_id: value.invocation_id,
    agent_publication_id: value.agent_publication_id,
    application_publication_id: value.application_publication_id,
    request_digest: value.request_digest,
    jti: "grant-jti-1",
    ...overrides
  })
    .setProtectedHeader({ alg: "EdDSA", typ: "JWT" })
    .setIssuer("enterprise-agent-worker")
    .setAudience("agent-runtime")
    .setIssuedAt(NOW_SECONDS)
    .setNotBefore(NOW_SECONDS - 1)
    .setExpirationTime(expiresAt)
    .sign(privateKey);
}

test("runtime config rejects unknown settings, floating CLI and unsafe remote URLs", () => {
  const config = loadRuntimeConfig(runtimeEnv());
  assert.equal(config.port, 8090);
  assert.throws(
    () => loadRuntimeConfig({ ...runtimeEnv(), AGENT_RUNTIME_UNSAFE_FALLBACK: "1" }),
    (error: unknown) =>
      error instanceof RuntimeConfigError && error.code === "runtime_config_unknown"
  );
  assert.throws(
    () => loadRuntimeConfig({ ...runtimeEnv(), AGENT_RUNTIME_CLI_VERSION: "latest" }),
    (error: unknown) =>
      error instanceof RuntimeConfigError && error.code === "runtime_cli_version_mismatch"
  );
  assert.equal(
    assertSafeRemoteUrl(
      "http://tool-mcp:9103/mcp",
      config.mcpAllowedHosts,
      "mcp"
    ).hostname,
    "tool-mcp"
  );
  assert.throws(
    () => assertSafeRemoteUrl("http://api.anthropic.com/v1", config.providerAllowedHosts, "model"),
    (error: unknown) =>
      error instanceof RuntimeConfigError && error.code === "runtime_remote_url_insecure"
  );
  assert.throws(
    () => assertSafeRemoteUrl("https://attacker.example/mcp", config.mcpAllowedHosts, "mcp"),
    (error: unknown) =>
      error instanceof RuntimeConfigError && error.code === "runtime_remote_host_not_allowed"
  );
  assert.throws(
    () =>
      loadRuntimeConfig({
        ...runtimeEnv(),
        AGENT_RUNTIME_TEST_PROVIDER_MODE: "deterministic"
      }),
    (error: unknown) =>
      error instanceof RuntimeConfigError && error.code === "runtime_fake_provider_forbidden"
  );
  assert.equal(
    loadRuntimeConfig({
      ...runtimeEnv(),
      APP_ENV: "testing",
      AGENT_RUNTIME_TEST_PROVIDER_MODE: "deterministic"
    }).fakeProviderMode,
    true
  );
});

test("test-only fake provider validates binding and has deterministic retry semantics", async () => {
  let resolutions = 0;
  const executor = new DeterministicFakeProviderRuntimeExecutor({
    resolve: async (value) => {
      resolutions += 1;
      return {
        protocol: "anthropic_compatible",
        baseUrl: "https://api.deepseek.com/anthropic",
        model: "deepseek-chat",
        defaultOpusModel: "deepseek-chat",
        defaultSonnetModel: "deepseek-chat",
        defaultHaikuModel: "deepseek-chat",
        subagentModel: "deepseek-chat",
        effortLevel: "max",
        connectionRevisionId: value.model_connection.revision_id,
        configHash: value.model_connection.config_hash,
        apiKey: "fake-provider-binding-secret"
      };
    }
  });
  const first = request();
  first.invocation_id = `${first.job_id}.attempt-0`;
  first.prompt.user_question = "[smoke:retry-once] verify retry";
  const emitted: string[] = [];
  const retry = await executor.execute(first, {
    signal: new AbortController().signal,
    emit: (eventType) => emitted.push(eventType)
  });
  const second = structuredClone(first);
  second.invocation_id = `${second.job_id}.attempt-1`;
  const succeeded = await executor.execute(second, {
    signal: new AbortController().signal,
    emit: () => undefined
  });

  assert.equal(retry.status, "FAILED");
  assert.equal(retry.failure?.retry_class, "TRANSIENT");
  assert.equal(succeeded.status, "SUCCEEDED");
  assert.equal(succeeded.final_answer, "TypeScript Runtime fake-provider smoke completed.");
  assert.deepEqual(emitted, ["execution_started"]);
  assert.equal(resolutions, 2);
  assert.equal(JSON.stringify([retry, succeeded]).includes("binding-secret"), false);
});

test("structured logger redacts credentials recursively and truncates values", () => {
  const sanitized = sanitizeLogValue({
    authorization: "Bearer header-secret",
    nested: { api_key: "sk-very-secret-value", note: "x".repeat(3000) },
    database: "postgresql://runtime:password@database/agent"
  }) as Record<string, any>;

  assert.equal(sanitized.authorization, "[REDACTED]");
  assert.equal(sanitized.nested.api_key, "[REDACTED]");
  assert.match(sanitized.nested.note, /\[TRUNCATED\]$/);
  assert.equal(String(sanitized.database).includes("password"), false);

  const lines: string[] = [];
  new StructuredLogger("info", (line) => lines.push(line)).log("info", "safe_event", {
    access_token: "must-not-log"
  });
  assert.equal(lines.length, 1);
  assert.equal(lines[0]?.includes("must-not-log"), false);
});

test("Runtime Grant verifies every execution binding and prevents cross-invocation replay", async () => {
  const keys = keyPair();
  const verifier = new RuntimeGrantVerifier(keys.publicKey, () => NOW_SECONDS);
  const value = request();
  const token = await grant(keys.privateKey, value);

  assert.equal((await verifier.verify(token, value)).job_id, value.job_id);
  assert.equal((await verifier.verify(token, value)).invocation_id, value.invocation_id);

  const expired = await grant(keys.privateKey, value, { jti: "expired-grant" }, NOW_SECONDS - 10);
  await assert.rejects(
    verifier.verify(expired, value),
    (error: unknown) =>
      error instanceof RuntimeGrantError && error.code === "runtime_grant_invalid"
  );

  const other = structuredClone(value);
  other.invocation_id = "invocation-2";
  await assert.rejects(
    verifier.verify(token, other),
    (error: unknown) =>
      error instanceof RuntimeGrantError && error.code === "runtime_grant_binding_mismatch"
  );

  const otherRuntime = structuredClone(value);
  otherRuntime.runtime_kind = "python-v1";
  await assert.rejects(
    verifier.verify(token, otherRuntime),
    (error: unknown) =>
      error instanceof RuntimeGrantError && error.code === "runtime_grant_binding_mismatch"
  );

  const replayToken = await grant(keys.privateKey, other, { invocation_id: other.invocation_id });
  await assert.rejects(
    verifier.verify(replayToken, other),
    (error: unknown) =>
      error instanceof RuntimeGrantError && error.code === "runtime_grant_replayed"
  );
});

test("invocation registry starts one execution, replays terminal and rejects digest conflicts", async () => {
  let executions = 0;
  const executor: RuntimeExecutor = async (value, emitter) => {
    executions += 1;
    emitter.emit("execution_started", provenance(value));
    await Promise.resolve();
    return {
      status: "SUCCEEDED",
      final_answer: "done",
      usage: { input_tokens: 1, output_tokens: 1 },
      runtime_provenance: provenance(value)
    };
  };
  const registry = new InvocationRegistry(executor, 60_000);
  const first = await registry.acquire(request());
  const duplicate = await registry.acquire(request());
  const firstEvents: unknown[] = [];
  const duplicateEvents: unknown[] = [];
  first.subscribe((event) => firstEvents.push(event));
  duplicate.subscribe((event) => duplicateEvents.push(event));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(executions, 1);
  assert.deepEqual(firstEvents, duplicateEvents);
  assert.deepEqual(
    firstEvents.map((event: any) => event.sequence),
    [1, 2]
  );
  const replayed: unknown[] = [];
  registry.get("invocation-1")?.subscribe((event) => replayed.push(event));
  assert.deepEqual(replayed, firstEvents);

  const conflicting = request();
  conflicting.request_digest = "c".repeat(64);
  await assert.rejects(registry.acquire(conflicting), InvocationConflictError);
});

class MemoryTerminalLedger implements TerminalLedger {
  value?: PersistedTerminal;
  claimOwner: string | undefined;
  claimDigest: string | undefined;
  claimEvents: RuntimeEvent[] = [];

  async load(invocationId: string): Promise<PersistedTerminal | undefined> {
    if (this.value?.events[0]?.invocation_id !== invocationId) return undefined;
    return structuredClone(this.value);
  }

  async claim(
    value: AgentExecutionRequestV1,
    ownerInstanceId: string
  ): Promise<{ status: "CLAIMED" | "ORPHANED"; events: RuntimeEvent[] }> {
    if (this.claimDigest && this.claimDigest !== value.request_digest) {
      throw new Error("claim digest conflict");
    }
    if (!this.claimOwner) {
      this.claimOwner = ownerInstanceId;
      this.claimDigest = value.request_digest;
    }
    return {
      status: this.claimOwner === ownerInstanceId ? "CLAIMED" : "ORPHANED",
      events: structuredClone(this.claimEvents)
    };
  }

  async append(
    _value: AgentExecutionRequestV1,
    event: RuntimeEvent
  ): Promise<void> {
    this.claimEvents.push(structuredClone(event));
  }

  async save(
    value: AgentExecutionRequestV1,
    events: readonly RuntimeEvent[],
    terminalAt: Date
  ): Promise<void> {
    this.value = {
      requestDigest: value.request_digest,
      events: structuredClone([...events]),
      terminalAt
    };
    this.claimOwner = undefined;
    this.claimDigest = undefined;
    this.claimEvents = [];
  }
}

test("terminal ledger replays a completed invocation after Runtime restart", async () => {
  let executions = 0;
  const ledger = new MemoryTerminalLedger();
  const executor: RuntimeExecutor = async (value, emitter) => {
    executions += 1;
    emitter.emit("execution_started", provenance(value));
    return {
      status: "SUCCEEDED",
      final_answer: "persisted",
      usage: { input_tokens: 1, output_tokens: 1 },
      runtime_provenance: provenance(value)
    };
  };
  const firstRegistry = new InvocationRegistry(executor, 60_000, undefined, ledger);
  const first = await firstRegistry.acquire(request());
  const original: RuntimeEvent[] = [];
  first.subscribe((event) => original.push(event));
  await new Promise((resolve) => setImmediate(resolve));

  const restartedRegistry = new InvocationRegistry(executor, 60_000, undefined, ledger);
  const recovered = await restartedRegistry.acquire(request());
  const replayed: RuntimeEvent[] = [];
  recovered.subscribe((event) => replayed.push(event));

  assert.equal(executions, 1);
  assert.deepEqual(replayed, original);
  const conflict = request();
  conflict.request_digest = "d".repeat(64);
  await assert.rejects(restartedRegistry.acquire(conflict), InvocationConflictError);
});

test("Runtime restart fails an orphaned in-progress invocation without replaying the model", async () => {
  let executions = 0;
  const ledger = new MemoryTerminalLedger();
  const executor: RuntimeExecutor = async (value, emitter): Promise<never> => {
    executions += 1;
    emitter.emit("execution_started", provenance(value));
    return await new Promise<never>(() => undefined);
  };
  const firstRegistry = new InvocationRegistry(
    executor,
    60_000,
    undefined,
    ledger,
    "runtime-before-restart"
  );
  await firstRegistry.acquire(request());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(executions, 1);
  assert.equal(ledger.claimEvents.length, 1);

  const restartedRegistry = new InvocationRegistry(
    executor,
    60_000,
    undefined,
    ledger,
    "runtime-after-restart"
  );
  const recovered = await restartedRegistry.acquire(request());
  const events: RuntimeEvent[] = [];
  recovered.subscribe((event) => events.push(event));

  assert.equal(executions, 1);
  assert.equal(events.length, 2);
  assert.equal(events[0]?.event_type, "execution_started");
  assert.equal(events[1]?.event_type, "terminal");
  assert.equal(events[1]?.payload.status, "FAILED");
  assert.equal(
    events[1]?.payload.failure?.code,
    "runtime_orphaned_invocation"
  );
  assert.equal(events[1]?.payload.failure?.retry_class, "NEVER");

  const replayRegistry = new InvocationRegistry(
    executor,
    60_000,
    undefined,
    ledger,
    "runtime-later-restart"
  );
  const replayed: RuntimeEvent[] = [];
  (await replayRegistry.acquire(request())).subscribe((event) => replayed.push(event));
  assert.deepEqual(replayed, events);
  assert.equal(executions, 1);
});

test("cancelling a running invocation aborts once and preserves a single terminal", async () => {
  let aborted = false;
  const executor: RuntimeExecutor = async (value, emitter) => {
    await new Promise<void>((resolve) => {
      emitter.signal.addEventListener("abort", () => {
        aborted = true;
        resolve();
      });
    });
    return {
      status: "SUCCEEDED",
      final_answer: "too late",
      usage: { input_tokens: 0, output_tokens: 0 },
      runtime_provenance: provenance(value)
    };
  };
  const registry = new InvocationRegistry(executor, 60_000);
  const handle = await registry.acquire(request());
  const events: any[] = [];
  handle.subscribe((event) => events.push(event));
  await new Promise((resolve) => setImmediate(resolve));
  await handle.cancel("test");
  await handle.cancel("duplicate");
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(aborted, true);
  assert.equal(events.filter((event) => event.event_type === "terminal").length, 1);
  assert.equal(events.at(-1)?.payload.status, "CANCELLED");
});

class ReadyProbe implements ReadinessProbe {
  checks = 0;

  async check() {
    this.checks += 1;
    return { ready: true, database: "ready" as const, master_key: "ready" as const };
  }

  async close(): Promise<void> {}
}

class MemoryResponse extends EventEmitter {
  status = 200;
  headers = new Map<string, string>();
  chunks: Buffer[] = [];
  headersSent = false;
  writableEnded = false;

  writeHead(status: number, headers: Record<string, string>): this {
    this.status = status;
    this.headersSent = true;
    for (const [name, value] of Object.entries(headers)) {
      this.headers.set(name.toLowerCase(), value);
    }
    return this;
  }

  write(chunk: string | Buffer): boolean {
    this.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    return true;
  }

  end(chunk?: string | Buffer): this {
    if (chunk !== undefined) this.write(chunk);
    this.writableEnded = true;
    this.emit("finish");
    return this;
  }

  destroy(): this {
    this.writableEnded = true;
    this.emit("close");
    return this;
  }

  get body(): string {
    return Buffer.concat(this.chunks).toString("utf8");
  }
}

function memoryRequest(
  method: string,
  url: string,
  body = "",
  headers: Record<string, string> = {}
): IncomingMessage {
  const request = Readable.from(body ? [Buffer.from(body)] : []) as Readable & {
    method?: string;
    url?: string;
    headers?: Record<string, string>;
  };
  request.method = method;
  request.url = url;
  request.headers = {
    ...headers,
    ...(body ? { "content-length": String(Buffer.byteLength(body)) } : {})
  };
  return request as unknown as IncomingMessage;
}

test("HTTP runtime exposes passive health/version/readiness and strict NDJSON terminal", async () => {
  const keys = keyPair();
  const verifier = new RuntimeGrantVerifier(keys.publicKey, () => NOW_SECONDS);
  const executor: RuntimeExecutor = async (value, emitter) => {
    emitter.emit("execution_started", provenance(value));
    return {
      status: "SUCCEEDED",
      final_answer: "done",
      usage: { input_tokens: 2, output_tokens: 1 },
      runtime_provenance: provenance(value)
    };
  };
  const readiness = new ReadyProbe();
  const config = loadRuntimeConfig(runtimeEnv());
  const handler = createRuntimeRequestHandler({
    config,
    grantVerifier: verifier,
    registry: new InvocationRegistry(executor, 60_000),
    readiness,
    logger: new StructuredLogger("error", () => {})
  });

  async function dispatch(
    method: string,
    url: string,
    body = "",
    headers: Record<string, string> = {}
  ): Promise<MemoryResponse> {
    const response = new MemoryResponse();
    await handler(
      memoryRequest(method, url, body, headers),
      response as unknown as ServerResponse
    );
    if (!response.writableEnded) await once(response, "finish");
    return response;
  }

  assert.equal((await dispatch("GET", "/health")).status, 200);
  const version = JSON.parse((await dispatch("GET", "/version")).body);
  assert.equal(version.sdk_version, "0.3.226");
  assert.equal((await dispatch("GET", "/ready")).status, 200);
  assert.equal(readiness.checks, 1);

  const value = request();
  const runtimeGrant = await grant(keys.privateKey, value);
  const response = await dispatch(
    "POST",
    "/internal/v1/executions",
    JSON.stringify(value),
    {
      authorization: `Bearer ${runtimeGrant}`,
      "content-type": "application/json",
      "x-mcp-principal-token": "test-only-principal-token"
    }
  );
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /application\/x-ndjson/);
  const events = response.body
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  assert.deepEqual(
    events.map((event) => [event.sequence, event.event_type]),
    [
      [1, "execution_started"],
      [2, "terminal"]
    ]
  );
  assert.equal(events.at(-1)?.payload.last_sequence, 2);

  const cancelResponse = await dispatch(
    "POST",
    `/internal/v1/executions/${value.invocation_id}/cancel`,
    JSON.stringify({
      protocol_version: "1.0",
      invocation_id: value.invocation_id,
      request_digest: value.request_digest,
      reason: "JOB_CANCELLED"
    }),
    {
      authorization: `Bearer ${runtimeGrant}`,
      "content-type": "application/json"
    }
  );
  assert.equal(cancelResponse.status, 200);
  assert.equal(JSON.parse(cancelResponse.body).status, "already_terminal");
});
