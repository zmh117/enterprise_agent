import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import errors from "../contracts/v1/errors.json" with { type: "json" };
import executionRequest from "../contracts/v1/golden/execution-request.json" with { type: "json" };
import safeRuntimeFixture from "../contracts/v1/golden/safe-runtime-fixture.json" with { type: "json" };
import limits from "../contracts/v1/limits.json" with { type: "json" };
import { assertContract, ContractValidationError } from "../src/generated/validators.js";
import {
  canonicalRequestDigest,
  ProtocolBoundaryError,
  validateExecutionRequest
} from "../src/protocol.js";

test("golden request has the same canonical digest and validates", () => {
  assert.equal(canonicalRequestDigest(executionRequest), executionRequest.request_digest);
  assert.doesNotThrow(() => validateExecutionRequest(executionRequest));
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
