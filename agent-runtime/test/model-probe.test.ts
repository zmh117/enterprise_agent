import assert from "node:assert/strict";
import { test } from "node:test";

import type { Options, SDKMessage } from "@anthropic-ai/claude-agent-sdk";

import type { ModelProbeRequest } from "../src/generated/contracts.js";
import {
  ModelConnectionProbe,
  ModelProbeAuthenticationError,
  verifyModelProbeToken
} from "../src/model-probe.js";
import type { ResolvedModelBinding } from "../src/model-binding.js";
import type { ClaudeQuery } from "../src/claude-runtime.js";

const request: ModelProbeRequest = {
  protocol_version: "1.0",
  runtime_kind: "typescript-v1",
  probe_id: "probe-test-1",
  model_connection: {
    revision_id: "model-revision-1",
    config_hash: "a".repeat(64)
  },
  timeout_seconds: 3
};

const binding: ResolvedModelBinding = {
  protocol: "anthropic_compatible",
  baseUrl: "https://api.deepseek.com/anthropic",
  model: "deepseek-chat",
  defaultOpusModel: "deepseek-chat",
  defaultSonnetModel: "deepseek-chat",
  defaultHaikuModel: "deepseek-chat",
  subagentModel: "deepseek-chat",
  effortLevel: "max",
  connectionRevisionId: "model-revision-1",
  configHash: "a".repeat(64),
  apiKey: "fixture-key-must-never-be-returned"
};

function resultMessage(): SDKMessage {
  return {
    type: "result",
    subtype: "success",
    is_error: false,
    result: "OK",
    usage: { input_tokens: 1, output_tokens: 1 }
  } as unknown as SDKMessage;
}

test("model probe is a single-turn no-tool Runtime call with a safe response", async () => {
  let captured: Options | undefined;
  const query = ((parameters: { options?: Options }) => {
    captured = parameters.options;
    return (async function* () {
      yield resultMessage();
    })();
  }) as unknown as ClaudeQuery;
  const probe = new ModelConnectionProbe(
    { resolve: async () => binding },
    query,
    async () => new Response(null, { status: 404 }),
    (() => {
      let current = 1000;
      return () => current++;
    })()
  );

  const response = await probe.run(request);

  assert.equal(response.success, true);
  assert.equal(response.connection_revision_id, "model-revision-1");
  assert.equal(response.provider_host, "api.deepseek.com");
  assert.equal(response.sdk_version, "0.3.226");
  assert.deepEqual(captured?.allowedTools, []);
  assert.deepEqual(captured?.mcpServers, {});
  assert.equal(captured?.maxTurns, 1);
  assert.equal(JSON.stringify(response).includes(binding.apiKey), false);
  assert.equal(JSON.stringify(response).includes("OK"), false);
});

test("model probe rejects redirects and invalid service identity", async () => {
  const query = (() => {
    throw new Error("query must not be called after redirect");
  }) as unknown as ClaudeQuery;
  const probe = new ModelConnectionProbe(
    { resolve: async () => binding },
    query,
    async () => new Response(null, { status: 302 }),
    () => 1000
  );
  const response = await probe.run(request);
  assert.equal(response.success, false);
  assert.equal(response.failure?.code, "model_connection_test_failed");

  const expected = "probe-token-value-with-at-least-32-characters";
  verifyModelProbeToken(expected, expected);
  assert.throws(
    () => verifyModelProbeToken(expected, "wrong-token-value-with-at-least-32-characters"),
    ModelProbeAuthenticationError
  );
});
