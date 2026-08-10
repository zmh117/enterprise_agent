import { createHash } from "node:crypto";

import limits from "../contracts/v1/limits.json" with { type: "json" };
import type { AgentExecutionRequestV1 } from "./generated/contracts.js";
import { assertContract } from "./generated/validators.js";

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
): asserts payload is AgentExecutionRequestV1 {
  if (encodedBytes > limits.max_request_bytes) {
    throw new ProtocolBoundaryError(
      "runtime_request_too_large",
      `request is ${encodedBytes} bytes; maximum is ${limits.max_request_bytes}`
    );
  }
  try {
    assertContract("AgentExecutionRequestV1", payload);
  } catch (error) {
    throw new ProtocolBoundaryError(
      "runtime_request_invalid",
      error instanceof Error ? error.message : "request schema validation failed"
    );
  }
  const request = payload as AgentExecutionRequestV1;
  const actual = canonicalRequestDigest(request as unknown as Record<string, unknown>);
  if (actual !== request.request_digest) {
    throw new ProtocolBoundaryError(
      "runtime_request_digest_mismatch",
      "request digest does not match the canonical request body"
    );
  }
}
