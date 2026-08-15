import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import type {
  McpSdkServerConfigWithInstance,
  Options,
  SDKMessage
} from "@anthropic-ai/claude-agent-sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import executionRequestFixtureV12 from "../contracts/v1.2/golden/execution-request.json" with { type: "json" };
import {
  ClaudeAgentRuntimeExecutor,
  type ClaudeQuery,
  type InvocationWorkspaceFactory
} from "../src/claude-runtime.js";
import {
  ClaudeRuntimeFileBridge,
  type RemoteFileMcpClient,
  type RuntimeFileBridgeFactory
} from "../src/file-mcp-bridge.js";
import type { AgentExecutionRequestV12 } from "../src/generated/contracts-v1_2.js";
import type { InvocationSecretContext, ExecutionEmitter } from "../src/invocation-registry.js";
import type { ResolvedModelBinding } from "../src/model-binding.js";

const sourceBytes = Buffer.from("initial TXT from File Service", "utf8");

function digest(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function successResult(): SDKMessage {
  return {
    type: "result",
    subtype: "success",
    is_error: false,
    result: "runtime file bridge complete",
    usage: { input_tokens: 1, output_tokens: 1 }
  } as unknown as SDKMessage;
}

function toolResultMessage(
  toolUseId: string,
  result: Awaited<ReturnType<Client["callTool"]>>
): SDKMessage {
  return {
    type: "user",
    parent_tool_use_id: null,
    tool_use_result: result,
    message: {
      role: "user",
      content: [
        {
          type: "tool_result",
          tool_use_id: toolUseId,
          content: "content" in result ? result.content : [],
          is_error: "isError" in result ? result.isError : false
        }
      ]
    }
  } as unknown as SDKMessage;
}

test("real TypeScript Runtime SDK loop materializes and commits only through its local File MCP bridge", async () => {
  const request = structuredClone(executionRequestFixtureV12) as AgentExecutionRequestV12;
  request.mcp_servers = [
    {
      server_code: "file-service",
      tools: [
        {
          tool_name: "file_prepare_materialization",
          required_scope: "mcp:file-service:file_prepare_materialization:invoke",
          tool_schema_hash: "a".repeat(64)
        },
        {
          tool_name: "file_create_commit_intent",
          required_scope: "mcp:file-service:file_create_commit_intent:invoke",
          tool_schema_hash: "b".repeat(64)
        }
      ]
    }
  ];
  request.limits.max_tool_calls = 8;
  const root = await mkdtemp(join(tmpdir(), "runtime-file-bridge-loop-"));
  const sandboxPath = join(root, "sandbox");
  await Promise.all(
    ["inputs", "work", "outputs", "tmp"].map((name) =>
      mkdir(join(sandboxPath, name), { recursive: true })
    )
  );
  let cleaned = false;
  const workspaces: InvocationWorkspaceFactory = {
    async create() {
      return {
        path: sandboxPath,
        authorizeTool: async (_toolName, input) => input as Record<string, unknown>,
        cleanup: async () => {
          cleaned = true;
          await rm(root, { recursive: true, force: true });
        }
      };
    }
  };
  const uploaded: Buffer[] = [];
  let remoteCall = 0;
  const remote: RemoteFileMcpClient = {
    connect: async () => undefined,
    close: async () => undefined,
    async callTool(toolName, args) {
      remoteCall += 1;
      if (toolName === "file_prepare_materialization") {
        return {
          content: [{ type: "text", text: JSON.stringify({ status: "PREPARED" }) }],
          _meta: {
            "enterprise-agent/mcp-call-id": `mcp-call-${remoteCall}`,
            "enterprise-agent/agent-tool-call-id": `persisted-call-${remoteCall}`,
            "enterprise-agent/file-transfer": {
              protocol: "enterprise-agent.file-transfer/v1",
              action: "MATERIALIZE",
              transfer_id: "transfer-1",
              sandbox_entry_handle: "sandbox-entry-1",
              relative_path: "inputs/source-12345678.txt",
              expected_size_bytes: sourceBytes.byteLength,
              expected_sha256: digest(sourceBytes)
            }
          }
        };
      }
      assert.equal(toolName, "file_create_commit_intent");
      assert.equal(typeof args.sandbox_entry_handle, "string");
      return {
        content: [{ type: "text", text: JSON.stringify({ status: "PREPARED" }) }],
        _meta: {
          "enterprise-agent/mcp-call-id": `mcp-call-${remoteCall}`,
          "enterprise-agent/agent-tool-call-id": `persisted-call-${remoteCall}`,
          "enterprise-agent/file-transfer": {
            protocol: "enterprise-agent.file-transfer/v1",
            action: "UPLOAD_COMMIT",
            commit_id: `commit-${remoteCall}`,
            sandbox_entry_handle: args.sandbox_entry_handle
          }
        }
      };
    }
  };
  const runtimeFetch: typeof fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (init?.method === "GET") {
      assert.equal(url.pathname, "/internal/v1/file-transfers/transfer-1/content");
      return new Response(sourceBytes, {
        headers: { "Content-Type": "application/octet-stream" }
      });
    }
    assert.equal(init?.method, "PUT");
    const chunks: Buffer[] = [];
    for await (const chunk of init?.body as unknown as AsyncIterable<Uint8Array>) {
      chunks.push(Buffer.from(chunk));
    }
    const body = Buffer.concat(chunks);
    uploaded.push(body);
    return Response.json({
      version_id: `version-${uploaded.length}`,
      size_bytes: body.byteLength,
      sha256: digest(body)
    });
  };
  const fileBridgeFactory: RuntimeFileBridgeFactory = (options) =>
    new ClaudeRuntimeFileBridge({ ...options, remoteClient: remote, runtimeFetch });
  const query = ((params: { options?: Options }) => {
    const options = params.options!;
    return (async function* (): AsyncGenerator<SDKMessage> {
      const config = options.mcpServers?.files as McpSdkServerConfigWithInstance;
      assert.equal(config.type, "sdk");
      const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
      await config.instance.connect(serverTransport);
      const client = new Client({ name: "runtime-loop-test", version: "0.1.0" });
      await client.connect(clientTransport as never);
      try {
        const materializeTool = "mcp__files__file_prepare_materialization";
        const materializeUseId = "tool-use-materialize";
        assert.equal(
          (
            await options.canUseTool?.(
              materializeTool,
              { file_id: "file-1", version_id: "version-1" },
              {
                signal: new AbortController().signal,
                toolUseID: materializeUseId,
                requestId: "permission-materialize"
              }
            )
          )?.behavior,
          "allow"
        );
        const materialized = await client.callTool({
          name: "file_prepare_materialization",
          arguments: { file_id: "file-1", version_id: "version-1" }
        });
        assert.equal(
          await readFile(join(sandboxPath, "inputs/source-12345678.txt"), "utf8"),
          sourceBytes.toString("utf8")
        );
        const serializedMaterialized = JSON.stringify(materialized);
        assert.equal(serializedMaterialized.includes("enterprise-agent/file-transfer"), false);
        assert.equal(serializedMaterialized.includes(sourceBytes.toString("utf8")), false);
        yield toolResultMessage(materializeUseId, materialized);

        assert.equal(
          (
            await options.canUseTool?.(
              "Edit",
              {
                file_path: "inputs/source-12345678.txt",
                old_string: sourceBytes.toString("utf8"),
                new_string: "edited materialized TXT"
              },
              {
                signal: new AbortController().signal,
                toolUseID: "tool-use-edit",
                requestId: "permission-edit"
              }
            )
          )?.behavior,
          "allow"
        );
        await writeFile(
          join(sandboxPath, "inputs/source-12345678.txt"),
          "edited materialized TXT",
          "utf8"
        );
        const commitTool = "mcp__files__file_create_commit_intent";
        const commitUseId = "tool-use-commit";
        const commitArguments = {
          sandbox_entry_handle: "sandbox-entry-1",
          file_id: "file-1",
          base_version_id: "version-1",
          display_name: "source.txt",
          user_intent: "MODIFY",
          delivery_mode: "WORKSPACE_ONLY"
        };
        assert.equal(
          (
            await options.canUseTool?.(commitTool, commitArguments, {
              signal: new AbortController().signal,
              toolUseID: commitUseId,
              requestId: "permission-commit"
            })
          )?.behavior,
          "allow"
        );
        const committed = await client.callTool({
          name: "file_create_commit_intent",
          arguments: commitArguments
        });
        assert.equal(uploaded[0]?.toString("utf8"), "edited materialized TXT");
        yield toolResultMessage(commitUseId, committed);

        await writeFile(join(sandboxPath, "outputs/new.txt"), "new generated TXT", "utf8");
        const selectTool = "mcp__files__select_sandbox_output";
        const selectUseId = "tool-use-select";
        assert.equal(
          (
            await options.canUseTool?.(
              selectTool,
              { relative_path: "outputs/new.txt" },
              {
                signal: new AbortController().signal,
                toolUseID: selectUseId,
                requestId: "permission-select"
              }
            )
          )?.behavior,
          "allow"
        );
        const selected = await client.callTool({
          name: "select_sandbox_output",
          arguments: { relative_path: "outputs/new.txt" }
        });
        const selectedText =
          "content" in selected && Array.isArray(selected.content)
            ? selected.content[0]
            : undefined;
        assert.equal(selectedText?.type, "text");
        const selectedPayload = JSON.parse((selectedText as { text: string }).text);
        const selectedHandle = selectedPayload.runtime_file_bridge.sandbox_entry_handle;
        assert.match(selectedHandle, /^sandbox-entry:/);
        yield toolResultMessage(selectUseId, selected);

        const generatedCommitUseId = "tool-use-generated-commit";
        const generatedArguments = {
          sandbox_entry_handle: selectedHandle,
          display_name: "new.txt",
          user_intent: "GENERATE",
          delivery_mode: "DEFAULT"
        };
        assert.equal(
          (
            await options.canUseTool?.(commitTool, generatedArguments, {
              signal: new AbortController().signal,
              toolUseID: generatedCommitUseId,
              requestId: "permission-generated-commit"
            })
          )?.behavior,
          "allow"
        );
        const generatedCommit = await client.callTool({
          name: "file_create_commit_intent",
          arguments: generatedArguments
        });
        assert.equal(uploaded[1]?.toString("utf8"), "new generated TXT");
        yield toolResultMessage(generatedCommitUseId, generatedCommit);
        yield successResult();
      } finally {
        await client.close();
        await config.instance.close();
      }
    })();
  }) as unknown as ClaudeQuery;
  const modelBinding: ResolvedModelBinding = {
    protocol: "anthropic_compatible",
    baseUrl: "https://model.invalid/anthropic",
    model: "test-model",
    defaultOpusModel: "test-model",
    defaultSonnetModel: "test-model",
    defaultHaikuModel: "test-model",
    subagentModel: "test-model",
    effortLevel: "max",
    connectionRevisionId: "model-revision-1",
    configHash: "c".repeat(64),
    apiKey: "test-only-model-key"
  };
  const events: Array<{ eventType: string; payload: unknown }> = [];
  const emitter: ExecutionEmitter = {
    signal: new AbortController().signal,
    emit: (eventType, payload) => events.push({ eventType, payload })
  };
  const runtime = new ClaudeAgentRuntimeExecutor(
    { resolve: async () => modelBinding },
    query,
    workspaces,
    undefined,
    undefined,
    undefined,
    "http://file-service:9105/mcp",
    fileBridgeFactory
  );
  const secrets: InvocationSecretContext = {
    filePrincipalToken: "test-only-file-principal"
  };

  const terminal = await runtime.execute(request, emitter, secrets);

  assert.equal(terminal.status, "SUCCEEDED");
  assert.equal(terminal.final_answer, "runtime file bridge complete");
  assert.equal(uploaded.length, 2);
  assert.equal(cleaned, true);
  assert.equal(
    JSON.stringify(events).includes("initial TXT from File Service"),
    false,
    JSON.stringify(events)
  );
  assert.equal(JSON.stringify(events).includes("test-only-file-principal"), false);
});
