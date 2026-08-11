import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import limits from "../contracts/v1/limits.json" with { type: "json" };
import type { CancelRequest, ModelProbeRequest } from "./generated/contracts.js";
import { assertContract } from "./generated/validators.js";
import { RuntimeGrantError, RuntimeGrantVerifier } from "./grant.js";
import {
  InvocationConflictError,
  InvocationRegistry
} from "./invocation-registry.js";
import type { StructuredLogger } from "./logger.js";
import { ModelBindingError } from "./model-binding.js";
import {
  ModelConnectionProbe,
  ModelProbeAuthenticationError,
  verifyModelProbeToken
} from "./model-probe.js";
import {
  ProtocolBoundaryError,
  validateExecutionRequest
} from "./protocol.js";
import type { ReadinessProbe } from "./readiness.js";
import {
  EXPECTED_CLI_VERSION,
  EXPECTED_SDK_VERSION,
  type RuntimeConfig
} from "./config.js";

export interface RuntimeServerDependencies {
  readonly config: RuntimeConfig;
  readonly grantVerifier: RuntimeGrantVerifier;
  readonly registry: InvocationRegistry;
  readonly readiness: ReadinessProbe;
  readonly logger: StructuredLogger;
  readonly modelProbe?: ModelConnectionProbe;
  readonly modelProbeToken?: string;
}

export type RuntimeRequestHandler = (
  request: IncomingMessage,
  response: ServerResponse
) => Promise<void>;

class RequestBodyError extends Error {
  constructor(readonly code: string, readonly status: number, message: string) {
    super(message);
  }
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const declared = Number(request.headers["content-length"] ?? "0");
  if (Number.isFinite(declared) && declared > limits.max_request_bytes) {
    throw new RequestBodyError("runtime_request_too_large", 413, "request body is too large");
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > limits.max_request_bytes) {
      throw new RequestBodyError("runtime_request_too_large", 413, "request body is too large");
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RequestBodyError("runtime_request_invalid", 400, "request body is not valid JSON");
  }
}

function bearerToken(request: IncomingMessage): string {
  const authorization = request.headers.authorization;
  if (!authorization?.startsWith("Bearer ")) {
    throw new RuntimeGrantError("runtime_grant_invalid", "Runtime Grant is required");
  }
  return authorization.slice("Bearer ".length).trim();
}

function sendJson(response: ServerResponse, status: number, body: object): void {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff"
  });
  response.end(JSON.stringify(body));
}

function safeError(error: unknown): { status: number; code: string; message: string } {
  if (error instanceof RequestBodyError) {
    return { status: error.status, code: error.code, message: "请求内容无效" };
  }
  if (error instanceof ProtocolBoundaryError) {
    const status = error.code === "runtime_request_too_large" ? 413 : 400;
    return { status, code: error.code, message: "Runtime 请求校验失败" };
  }
  if (error instanceof RuntimeGrantError) {
    return { status: 401, code: error.code, message: "Runtime 服务身份校验失败" };
  }
  if (error instanceof ModelProbeAuthenticationError) {
    return { status: 401, code: error.code, message: "模型探针服务身份校验失败" };
  }
  if (error instanceof ModelBindingError) {
    return { status: 422, code: error.code, message: "模型连接不可用于测试" };
  }
  if (error instanceof InvocationConflictError) {
    return { status: 409, code: error.code, message: "Invocation 与既有请求冲突" };
  }
  return { status: 500, code: "runtime_internal_error", message: "Runtime 暂时不可用" };
}

export function createRuntimeRequestHandler(
  dependencies: RuntimeServerDependencies
): RuntimeRequestHandler {
  const {
    grantVerifier,
    registry,
    readiness,
    logger,
    modelProbe,
    modelProbeToken
  } = dependencies;
  return async (request, response) => {
    const correlationId = String(request.headers["x-correlation-id"] ?? "").slice(0, 128);
    try {
      if (request.method === "GET" && request.url === "/health") {
        sendJson(response, 200, { status: "ok" });
        return;
      }
      if (request.method === "GET" && request.url === "/version") {
        sendJson(response, 200, {
          runtime: "typescript-v1",
          runtime_version: "0.1.0",
          protocol_version: "1.0",
          sdk_version: EXPECTED_SDK_VERSION,
          cli_version: EXPECTED_CLI_VERSION
        });
        return;
      }
      if (request.method === "GET" && request.url === "/ready") {
        const status = await readiness.check();
        sendJson(response, status.ready ? 200 : 503, status);
        return;
      }
      if (request.method === "POST" && request.url === "/internal/v1/executions") {
        const encodedLength = Number(request.headers["content-length"] ?? "0") || undefined;
        const payload = await readJsonBody(request);
        validateExecutionRequest(payload, encodedLength);
        if (payload.runtime_kind !== "typescript-v1") {
          throw new ProtocolBoundaryError(
            "runtime_kind_mismatch",
            "execution request targets another Runtime"
          );
        }
        await grantVerifier.verify(bearerToken(request), payload);
        const handle = await registry.acquire(payload);
        response.writeHead(200, {
          "content-type": "application/x-ndjson; charset=utf-8",
          "cache-control": "no-store",
          "x-content-type-options": "nosniff"
        });
        let unsubscribe: () => void = () => {};
        unsubscribe = handle.subscribe((event) => {
          const line = `${JSON.stringify(event)}\n`;
          if (Buffer.byteLength(line, "utf8") > limits.max_event_line_bytes) {
            void handle.cancel("event_line_limit_exceeded");
            return;
          }
          response.write(line);
          if (event.event_type === "terminal") {
            unsubscribe();
            response.end();
          }
        });
        response.on("close", () => {
          unsubscribe();
          if (!response.writableEnded && !handle.isTerminal) {
            void handle.cancel("client_disconnected");
          }
        });
        return;
      }
      if (request.method === "POST" && request.url === "/internal/v1/model-probes") {
        if (!modelProbe || !modelProbeToken) {
          throw new RequestBodyError(
            "model_connection_test_unavailable",
            503,
            "model probe is unavailable"
          );
        }
        verifyModelProbeToken(modelProbeToken, bearerToken(request));
        const payload = await readJsonBody(request);
        assertContract("ModelProbeRequest", payload);
        if ((payload as ModelProbeRequest).runtime_kind !== "typescript-v1") {
          throw new ProtocolBoundaryError(
            "runtime_kind_mismatch",
            "model probe targets another Runtime"
          );
        }
        const result = await modelProbe.run(payload as ModelProbeRequest);
        sendJson(response, 200, result);
        return;
      }
      const cancelMatch = request.url?.match(/^\/internal\/v1\/executions\/([^/]+)\/cancel$/);
      if (request.method === "POST" && cancelMatch) {
        const invocationId = decodeURIComponent(cancelMatch[1] ?? "");
        const handle = registry.get(invocationId);
        if (!handle) {
          sendJson(response, 404, { code: "runtime_invocation_not_found", message: "未找到执行" });
          return;
        }
        const payload = await readJsonBody(request);
        assertContract("CancelRequest", payload);
        const cancel = payload as CancelRequest;
        if (
          cancel.invocation_id !== handle.request.invocation_id ||
          cancel.request_digest !== handle.request.request_digest
        ) {
          throw new ProtocolBoundaryError(
            "runtime_request_digest_mismatch",
            "cancel request does not match invocation"
          );
        }
        await grantVerifier.verify(bearerToken(request), handle.request);
        const alreadyTerminal = handle.isTerminal;
        await handle.cancel(cancel.reason);
        sendJson(response, 200, { status: alreadyTerminal ? "already_terminal" : "cancelled" });
        return;
      }
      sendJson(response, 404, { code: "runtime_route_not_found", message: "未找到接口" });
    } catch (error) {
      const safe = safeError(error);
      logger.log(safe.status >= 500 ? "error" : "warn", "runtime_request_rejected", {
        correlation_id: correlationId,
        method: request.method,
        path: request.url,
        status: safe.status,
        code: safe.code,
        error_class: error instanceof Error ? error.constructor.name : "UnknownError"
      });
      if (!response.headersSent) sendJson(response, safe.status, safe);
      else response.destroy();
    }
  };
}

export function createRuntimeServer(dependencies: RuntimeServerDependencies): Server {
  const handler = createRuntimeRequestHandler(dependencies);
  return createServer((request, response) => {
    void handler(request, response);
  });
}
