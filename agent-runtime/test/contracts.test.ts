import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import errors from "../contracts/v1/errors.json" with { type: "json" };
import executionRequest from "../contracts/v1/golden/execution-request.json" with { type: "json" };
import executionRequestV11 from "../contracts/v1.1/golden/execution-request.json" with { type: "json" };
import executionRequestV12 from "../contracts/v1.2/golden/execution-request.json" with { type: "json" };
import safeRuntimeFixture from "../contracts/v1/golden/safe-runtime-fixture.json" with { type: "json" };
import safeRuntimeFixtureV11 from "../contracts/v1.1/golden/safe-runtime-fixture.json" with { type: "json" };
import safeRuntimeFixtureV12 from "../contracts/v1.2/golden/safe-runtime-fixture.json" with { type: "json" };
import limits from "../contracts/v1/limits.json" with { type: "json" };
import { assertContract, ContractValidationError } from "../src/generated/validators.js";
import {
  assertContract as assertV11Contract,
  ContractValidationError as ContractValidationErrorV11
} from "../src/generated/validators-v1_1.js";
import {
  assertContract as assertV12Contract,
  ContractValidationError as ContractValidationErrorV12
} from "../src/generated/validators-v1_2.js";
import {
  canonicalRequestDigest,
  ProtocolBoundaryError,
  validateExecutionRequest
} from "../src/protocol.js";

test("golden request has the same canonical digest and validates", () => {
  assert.equal(canonicalRequestDigest(executionRequest), executionRequest.request_digest);
  assert.doesNotThrow(() => validateExecutionRequest(executionRequest));
});

test("v1.0, v1.1 and v1.2 remain strict while the Runtime boundary reads supported minors", () => {
  assert.equal(
    canonicalRequestDigest(executionRequestV11),
    executionRequestV11.request_digest
  );
  assert.doesNotThrow(() => validateExecutionRequest(executionRequest));
  assert.doesNotThrow(() => validateExecutionRequest(executionRequestV11));
  assert.equal(
    canonicalRequestDigest(executionRequestV12),
    executionRequestV12.request_digest
  );
  assert.doesNotThrow(() => validateExecutionRequest(executionRequestV12));
  assert.throws(
    () => assertContract("AgentExecutionRequestV1", executionRequestV11),
    ContractValidationError
  );
  assert.throws(
    () => assertV11Contract("AgentExecutionRequestV11", executionRequest),
    ContractValidationErrorV11
  );
  assert.throws(
    () => assertV12Contract("AgentExecutionRequestV12", executionRequestV11),
    ContractValidationErrorV12
  );
});

test("v1.1 Tool Events distinguish MCP and SDK origins without fuzzy server defaults", () => {
  assert.doesNotThrow(() => assertV11Contract("ToolEvent", safeRuntimeFixtureV11.tool_event));
  const sdkUnknown = {
    ...safeRuntimeFixtureV11.tool_event,
    tool_origin: "unknown",
    server_code: null,
    mcp_call_id: null,
    persisted_tool_call_id: null
  };
  assert.doesNotThrow(() => assertV11Contract("ToolEvent", sdkUnknown));
  assert.throws(
    () => assertV11Contract("ToolEvent", { ...sdkUnknown, server_code: "tool-mcp" }),
    ContractValidationErrorV11
  );
  const mcpTerminalWithoutIds = {
    ...safeRuntimeFixtureV11.tool_event,
    mcp_call_id: null,
    persisted_tool_call_id: null
  };
  assert.doesNotThrow(() => assertV11Contract("ToolEvent", mcpTerminalWithoutIds));
  assert.doesNotThrow(() =>
    assertV11Contract("ToolEvent", {
      ...safeRuntimeFixtureV11.tool_event,
      server_code: "future-readonly-mcp"
    })
  );
});

test("v1.2 validates safe runtime initialization, model calls, retries and accounting", () => {
  const fixture = safeRuntimeFixtureV12 as Record<string, unknown>;
  for (const name of ["runtime_initialized_event", "model_call_event", "api_retry_event", "terminal_event"]) {
    assert.doesNotThrow(() => assertV12Contract("RuntimeEvent", fixture[name]));
  }
  assert.throws(
    () =>
      assertV12Contract("ModelCall", {
        ...(fixture.model_call as Record<string, unknown>),
        duration_source: "PROVIDER_HTTP"
      }),
    ContractValidationErrorV12
  );
});

test("contract rejects unknown fields and unsupported protocol versions", () => {
  const unknown = structuredClone(executionRequest) as Record<string, unknown>;
  unknown.untrusted = true;
  assert.throws(
    () => assertContract("AgentExecutionRequestV1", unknown),
    ContractValidationError
  );

  const unsupported = structuredClone(executionRequest);
  Object.assign(unsupported, { protocol_version: "2.0" });
  assert.throws(
    () => assertContract("AgentExecutionRequestV1", unsupported),
    ContractValidationError
  );
});

test("single protocol accepts both fixed Runtime kinds and rejects unknown kinds", () => {
  const pythonRequest = structuredClone(executionRequest);
  Object.assign(pythonRequest, { runtime_kind: "python-v1" });
  pythonRequest.request_digest = canonicalRequestDigest(pythonRequest);
  assert.doesNotThrow(() => validateExecutionRequest(pythonRequest));

  const unknown = structuredClone(executionRequest);
  Object.assign(unknown, { runtime_kind: "ruby-v1" });
  unknown.request_digest = canonicalRequestDigest(unknown);
  assert.throws(
    () => assertContract("AgentExecutionRequestV1", unknown),
    ContractValidationError
  );

  const pythonProvenance = structuredClone(safeRuntimeFixture.runtime_provenance);
  Object.assign(pythonProvenance, {
    runtime_kind: "python-v1",
    sdk_version: "0.1.0"
  });
  assert.doesNotThrow(() => assertContract("RuntimeProvenance", pythonProvenance));
});

test("request boundary rejects digest mismatch and byte limit", () => {
  const mismatched = structuredClone(executionRequest);
  mismatched.prompt.user_question = "changed after signing";
  assert.throws(
    () => validateExecutionRequest(mismatched),
    (error: unknown) =>
      error instanceof ProtocolBoundaryError &&
      error.code === "runtime_request_digest_mismatch"
  );
  assert.throws(
    () => validateExecutionRequest(executionRequest, limits.max_request_bytes + 1),
    (error: unknown) =>
      error instanceof ProtocolBoundaryError && error.code === "runtime_request_too_large"
  );
});

test("stable errors, event, usage and provenance fixture remain schema-safe", async () => {
  assertContract("ToolEvent", safeRuntimeFixture.tool_event);
  assertContract("Usage", safeRuntimeFixture.usage);
  assertContract("RuntimeProvenance", safeRuntimeFixture.runtime_provenance);
  assertContract("RuntimeFailure", safeRuntimeFixture.failure);

  const fixtureText = await readFile(
    new URL("../contracts/v1/golden/safe-runtime-fixture.json", import.meta.url),
    "utf8"
  );
  for (const field of errors.sensitive_field_denylist) {
    assert.equal(fixtureText.toLowerCase().includes(`"${field}"`), false);
  }
  assert.equal(
    new Set(errors.errors.map((item) => item.code)).size,
    errors.errors.length
  );
});
