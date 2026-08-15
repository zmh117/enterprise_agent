import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
  type SdkMcpToolDefinition
} from "@anthropic-ai/claude-agent-sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import * as z from "zod/v4";

import {
  FileTransferBoundaryError,
  FileTransferCoordinator,
  type FileTransferContext
} from "./file-transfer.js";
import { HttpFileTransferPort, type RuntimeFetch } from "./file-transfer-http.js";

export const LOCAL_FILE_OUTPUT_TOOL = "select_sandbox_output";
const MATERIALIZE_TOOL = "file_prepare_materialization";
const COMMIT_TOOL = "file_create_commit_intent";
const MCP_CALL_ID_META_KEY = "enterprise-agent/mcp-call-id";
const AGENT_TOOL_CALL_ID_META_KEY = "enterprise-agent/agent-tool-call-id";
const OPAQUE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const DISPLAY_NAME = /^[^/\\\0]+\.txt$/;

type RemoteToolResult = CallToolResult & Record<string, unknown>;

export interface RemoteFileMcpClient {
  connect(signal: AbortSignal): Promise<void>;
  callTool(
    toolName: string,
    argumentsValue: Record<string, unknown>,
    signal: AbortSignal
  ): Promise<RemoteToolResult>;
  close(): Promise<void>;
}

export interface RuntimeFileBridge {
  readonly server: McpSdkServerConfigWithInstance;
  readonly localToolNames: readonly string[];
  connect(): Promise<void>;
  close(): Promise<void>;
}

export interface RuntimeFileBridgeOptions {
  readonly mcpServerUrl: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly frozenToolNames: readonly string[];
  readonly context: FileTransferContext;
  readonly timeoutMs: number;
  readonly remoteClient?: RemoteFileMcpClient;
  readonly runtimeFetch?: RuntimeFetch;
}

export type RuntimeFileBridgeFactory = (
  options: RuntimeFileBridgeOptions
) => RuntimeFileBridge;

class StandardRemoteFileMcpClient implements RemoteFileMcpClient {
  private readonly client = new Client(
    { name: "enterprise-agent-runtime-file-bridge", version: "0.1.0" },
    { capabilities: {} }
  );
  private readonly transport: StreamableHTTPClientTransport;
  private connected = false;

  constructor(
    mcpServerUrl: string,
    headers: Readonly<Record<string, string>>,
    private readonly timeoutMs: number,
    runtimeFetch?: RuntimeFetch
  ) {
    this.transport = new StreamableHTTPClientTransport(new URL(mcpServerUrl), {
      requestInit: { headers: { ...headers }, redirect: "error" },
      ...(runtimeFetch ? { fetch: runtimeFetch } : {})
    });
  }

  async connect(signal: AbortSignal): Promise<void> {
    await this.client.connect(this.transport as never, {
      signal,
      timeout: this.timeoutMs,
      maxTotalTimeout: this.timeoutMs
    });
    this.connected = true;
  }

  async callTool(
    toolName: string,
    argumentsValue: Record<string, unknown>,
    signal: AbortSignal
  ): Promise<RemoteToolResult> {
    if (!this.connected) {
      throw new FileTransferBoundaryError(
        "file_service_unavailable",
        "File Service MCP bridge is not connected"
      );
    }
    const result = await this.client.callTool(
      { name: toolName, arguments: argumentsValue },
      undefined,
      { signal, timeout: this.timeoutMs, maxTotalTimeout: this.timeoutMs }
    );
    if (!("content" in result) || !Array.isArray(result.content)) {
      throw new FileTransferBoundaryError(
        "file_service_unavailable",
        "File Service returned an unsupported tool result"
      );
    }
    return result as RemoteToolResult;
  }

  async close(): Promise<void> {
    if (!this.connected) return;
    this.connected = false;
    await this.client.close();
  }
}

function safeMeta(result: RemoteToolResult): Record<string, unknown> | undefined {
  const raw = result._meta;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const source = raw as Record<string, unknown>;
  const retained = Object.fromEntries(
    [MCP_CALL_ID_META_KEY, AGENT_TOOL_CALL_ID_META_KEY]
      .map((key) => [key, source[key]] as const)
      .filter(([, value]) => typeof value === "string" && OPAQUE.test(value))
  );
  return Object.keys(retained).length > 0 ? retained : undefined;
}

function modelResult(
  remote: RemoteToolResult,
  bridgeResult?: Record<string, unknown>
): CallToolResult {
  const content = [...remote.content];
  if (bridgeResult) {
    content.push({
      type: "text",
      text: JSON.stringify({ runtime_file_bridge: bridgeResult })
    });
  }
  const meta = safeMeta(remote);
  return {
    content,
    ...(remote.isError === true ? { isError: true } : {}),
    ...(remote.structuredContent && typeof remote.structuredContent === "object"
      ? { structuredContent: remote.structuredContent }
      : {}),
    ...(meta ? { _meta: meta } : {})
  };
}

function toolDefinition(
  name: string,
  handler: (argumentsValue: Record<string, unknown>) => Promise<CallToolResult>
) {
  const opaque = () => z.string().regex(OPAQUE).max(128);
  const displayName = () => z.string().min(1).max(255).regex(DISPLAY_NAME);
  const definitions = {
    task_workspace_get: {
      description: "Read the current Job-bound task workspace summary.",
      shape: {}
    },
    task_workspace_list_files: {
      description: "List safe metadata for files visible to the current Job.",
      shape: {
        cursor: z.string().min(1).max(256).optional(),
        limit: z.number().int().min(1).max(50).optional()
      }
    },
    file_get_metadata: {
      description: "Read safe metadata for an exact Job Manifest file version.",
      shape: { file_id: opaque(), version_id: opaque() }
    },
    file_prepare_materialization: {
      description: "Materialize an exact Job Manifest TXT into the current Job Sandbox.",
      shape: {
        file_id: opaque(),
        version_id: opaque(),
        preferred_name: displayName().optional()
      }
    },
    file_create_commit_intent: {
      description: "Commit one explicitly selected sandbox TXT through File Service.",
      shape: {
        sandbox_entry_handle: opaque(),
        file_id: opaque().optional(),
        base_version_id: opaque().optional(),
        display_name: displayName(),
        user_intent: z.enum(["MODIFY", "GENERATE", "SAVE"]),
        delivery_mode: z.enum(["DEFAULT", "WORKSPACE_ONLY"])
      }
    },
    file_retain_version: {
      description: "Retain an authorized exact file version.",
      shape: { file_id: opaque(), version_id: opaque() }
    },
    file_deliver_version: {
      description: "Deliver an authorized exact file version to the frozen reply route.",
      shape: { file_id: opaque(), version_id: opaque() }
    }
  } as const;
  const definition = definitions[name as keyof typeof definitions];
  if (!definition) {
    throw new FileTransferBoundaryError(
      "file_tool_not_supported",
      "Runtime File MCP bridge received an unsupported frozen tool"
    );
  }
  return tool(name, definition.description, definition.shape, async (argumentsValue) =>
    handler(argumentsValue as Record<string, unknown>)
  );
}

export class ClaudeRuntimeFileBridge implements RuntimeFileBridge {
  readonly server: McpSdkServerConfigWithInstance;
  readonly localToolNames: readonly string[];
  private readonly coordinator: FileTransferCoordinator;
  private readonly remote: RemoteFileMcpClient;

  constructor(private readonly options: RuntimeFileBridgeOptions) {
    const frozen = [...new Set(options.frozenToolNames)];
    this.remote =
      options.remoteClient ??
      new StandardRemoteFileMcpClient(
        options.mcpServerUrl,
        options.headers,
        options.timeoutMs,
        options.runtimeFetch
      );
    this.coordinator = new FileTransferCoordinator(
      new HttpFileTransferPort(options.mcpServerUrl, options.runtimeFetch)
    );
    const tools: Array<SdkMcpToolDefinition<any>> = frozen.map((name) =>
      toolDefinition(name, (argumentsValue) => this.forward(name, argumentsValue))
    );
    const localToolNames: string[] = [];
    if (frozen.includes(COMMIT_TOOL)) {
      tools.push(
        tool(
          LOCAL_FILE_OUTPUT_TOOL,
          "Select one existing work/ or outputs/ TXT as the exact file for a later commit intent. Returns metadata and an opaque handle, never file content.",
          { relative_path: z.string().min(1).max(240) },
          async ({ relative_path }) => {
            const selected = await this.coordinator.selectSandboxOutput(
              relative_path,
              this.options.context
            );
            return {
              content: [
                {
                  type: "text",
                  text: JSON.stringify({ runtime_file_bridge: selected })
                }
              ]
            };
          }
        )
      );
      localToolNames.push(LOCAL_FILE_OUTPUT_TOOL);
    }
    this.localToolNames = localToolNames;
    this.server = createSdkMcpServer({
      name: "enterprise-file-bridge",
      version: "0.1.0",
      tools,
      alwaysLoad: true
    });
  }

  connect(): Promise<void> {
    return this.remote.connect(this.options.context.signal);
  }

  close(): Promise<void> {
    return this.remote.close();
  }

  private async forward(
    toolName: string,
    argumentsValue: Record<string, unknown>
  ): Promise<CallToolResult> {
    const remote = await this.remote.callTool(
      toolName,
      argumentsValue,
      this.options.context.signal
    );
    if (remote.isError === true) return modelResult(remote);
    if (toolName !== MATERIALIZE_TOOL && toolName !== COMMIT_TOOL) {
      return modelResult(remote);
    }
    const bridgeResult = await this.coordinator.processMcpControlResult(
      remote,
      this.options.context
    );
    return modelResult(remote, bridgeResult as unknown as Record<string, unknown>);
  }
}

export const createRuntimeFileBridge: RuntimeFileBridgeFactory = (options) =>
  new ClaudeRuntimeFileBridge(options);
