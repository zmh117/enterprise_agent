import { createHash } from "node:crypto";

import limitsV1 from "../contracts/v1/limits.json" with { type: "json" };
import limitsV11 from "../contracts/v1.1/limits.json" with { type: "json" };
import limitsV12 from "../contracts/v1.2/limits.json" with { type: "json" };
import type { AgentExecutionRequest } from "./runtime-contracts.js";
import { assertRuntimeContract } from "./runtime-contracts.js";

export class ProtocolBoundaryError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "ProtocolBoundaryError";
  }
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonicalValue(child)])
    );
  }
  return value;
}

export function canonicalRequestDigest(payload: Record<string, unknown>): string {
  const digestInput = { ...payload };
  delete digestInput.request_digest;
  const serialized = JSON.stringify(canonicalValue(digestInput));
  return createHash("sha256").update(serialized, "utf8").digest("hex");
}

export function validateExecutionRequest(
  payload: unknown,
  encodedBytes = Buffer.byteLength(JSON.stringify(payload), "utf8")
): asserts payload is AgentExecutionRequest {
  const requestedVersion =
    typeof payload === "object" && payload !== null
      ? (payload as { protocol_version?: unknown }).protocol_version
      : undefined;
  const protocolVersion = requestedVersion === "1.2" ? "1.2" : requestedVersion === "1.1" ? "1.1" : "1.0";
  const limits = protocolVersion === "1.2" ? limitsV12 : protocolVersion === "1.1" ? limitsV11 : limitsV1;
  if (encodedBytes > limits.max_request_bytes) {
    throw new ProtocolBoundaryError(
      "runtime_request_too_large",
      `request is ${encodedBytes} bytes; maximum is ${limits.max_request_bytes}`
    );
  }
  try {
    assertRuntimeContract(
      protocolVersion === "1.2"
        ? "AgentExecutionRequestV12"
        : protocolVersion === "1.1"
          ? "AgentExecutionRequestV11"
          : "AgentExecutionRequestV1",
      payload,
      protocolVersion
    );
  } catch (error) {
    throw new ProtocolBoundaryError(
      "runtime_request_invalid",
      error instanceof Error ? error.message : "request schema validation failed"
    );
  }
  const request = payload as AgentExecutionRequest;
  const serverCodes = request.mcp_servers.map((server) => server.server_code);
  if (new Set(serverCodes).size !== serverCodes.length) {
    throw new ProtocolBoundaryError(
      "runtime_mcp_server_duplicate",
      "each fixed MCP server may appear at most once"
    );
  }
  for (const server of request.mcp_servers) {
    const toolNames = server.tools.map((tool) => tool.tool_name);
    if (new Set(toolNames).size !== toolNames.length) {
      throw new ProtocolBoundaryError(
        "runtime_mcp_tool_duplicate",
        "each MCP Tool may appear at most once per server"
      );
    }
    if (
      server.server_code === "ones-mcp" &&
      toolNames.some((toolName) => toolName !== "ones_work_item_search")
    ) {
      throw new ProtocolBoundaryError(
        "runtime_mcp_tool_server_mismatch",
        "ones-mcp only accepts the fixed ONES query Tool"
      );
    }
    if (
      server.server_code === "tool-mcp" &&
      toolNames.includes("ones_work_item_search")
    ) {
      throw new ProtocolBoundaryError(
        "runtime_mcp_tool_server_mismatch",
        "ONES query Tool cannot be routed to tool-mcp"
      );
    }
  }
  const actual = canonicalRequestDigest(request as unknown as Record<string, unknown>);
  if (actual !== request.request_digest) {
    throw new ProtocolBoundaryError(
      "runtime_request_digest_mismatch",
      "request digest does not match the canonical request body"
    );
  }
}
