import type {
  AgentExecutionRequest,
  RuntimeFailure,
  RuntimeProvenance
} from "./runtime-contracts.js";
import type {
  ExecutionEmitter,
  InvocationSecretContext,
  RuntimeExecutor,
  TerminalDraft
} from "./invocation-registry.js";
import type { ModelBindingPort } from "./claude-runtime.js";

const MCP_CALL_ID_META_KEY = "enterprise-agent/mcp-call-id";
const AGENT_TOOL_CALL_ID_META_KEY = "enterprise-agent/agent-tool-call-id";

function failure(
  code: string,
  retryClass: RuntimeFailure["retry_class"],
  safeMessage: string
): RuntimeFailure {
  return { code, retry_class: retryClass, safe_message: safeMessage };
}

function provenance(
  request: AgentExecutionRequest,
  configHash: string
): RuntimeProvenance {
  return {
    runtime_kind: "typescript-v1",
    runtime_version: "0.1.0",
    protocol_version: request.protocol_version,
    sdk_version: "0.3.226",
    cli_version: "2.1.226",
    model_connection_revision_id: request.model_connection.revision_id,
    model_connection_config_hash: configHash
  };
}

async function waitForAbort(signal: AbortSignal, timeoutMilliseconds = 5_000): Promise<void> {
  if (signal.aborted) return;
  await new Promise<void>((resolve) => {
    const timeout = setTimeout(resolve, timeoutMilliseconds);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timeout);
        resolve();
      },
      { once: true }
    );
  });
}

/** Test-only deterministic provider path used by isolated Compose acceptance. */
export class DeterministicFakeProviderRuntimeExecutor {
  readonly execute: RuntimeExecutor;

  constructor(
    private readonly modelBindings: ModelBindingPort,
    private readonly toolMcpServerUrl = "http://tool-mcp:9103/mcp",
    private readonly onesMcpServerUrl = "http://ones-mcp:9104/mcp"
  ) {
    this.execute = this.run.bind(this);
  }

  private async run(
    request: AgentExecutionRequest,
    emitter: ExecutionEmitter,
    secrets: InvocationSecretContext = {}
  ): Promise<TerminalDraft> {
    const binding = await this.modelBindings.resolve(request);
    const runtimeProvenance = provenance(request, binding.configHash);
    emitter.emit("execution_started", runtimeProvenance);
    const question = request.prompt.user_question;
    if (question.includes("[smoke:restart-slow]")) {
      await waitForAbort(emitter.signal, 30_000);
    } else if (question.includes("[smoke:slow]")) {
      await waitForAbort(emitter.signal);
    }
    if (emitter.signal.aborted) {
      return {
        status: "CANCELLED",
        failure: failure("runtime_cancelled", "NEVER", "Agent 执行已取消"),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    if (question.includes("[smoke:mcp:tool-mcp]")) {
      return this.runMcpTool(
        request,
        emitter,
        runtimeProvenance,
        "tool-mcp",
        "get_er_context",
        { query: "enterprise agent acceptance" },
        undefined,
        1
      );
    }
    if (question.includes("[smoke:mcp:ones-mcp")) {
      if (!secrets.principalToken) {
        return {
          status: "FAILED",
          failure: failure(
            "runtime_principal_token_missing",
            "CONFIGURATION",
            "当前调用缺少平台身份凭证"
          ),
          usage: { input_tokens: 0, output_tokens: 0 },
          runtime_provenance: runtimeProvenance
        };
      }
      return this.runMcpTool(
        request,
        emitter,
        runtimeProvenance,
        "ones-mcp",
        "ones_work_item_search",
        { keyword: "traceability", issue_type: "demand", limit: 5 },
        secrets.principalToken,
        question.includes("[smoke:mcp:ones-mcp-concurrent]") ? 2 : 1
      );
    }
    if (
      question.includes("[smoke:retry-once]") &&
      request.invocation_id.endsWith(".attempt-0")
    ) {
      return {
        status: "FAILED",
        failure: failure(
          "runtime_fake_transient",
          "TRANSIENT",
          "Fake provider 暂时不可用"
        ),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    if (question.includes("[smoke:dead]")) {
      return {
        status: "FAILED",
        failure: failure("runtime_fake_permanent", "NEVER", "Fake provider 请求失败"),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    return {
      status: "SUCCEEDED",
      final_answer: "TypeScript Runtime fake-provider smoke completed.",
      usage: { input_tokens: 1, output_tokens: 1 },
      runtime_provenance: runtimeProvenance
    };
  }

  private async runMcpTool(
    request: AgentExecutionRequest,
    emitter: ExecutionEmitter,
    runtimeProvenance: RuntimeProvenance,
    serverCode: "tool-mcp" | "ones-mcp",
    toolName: string,
    args: Record<string, unknown>,
    principalToken: string | undefined,
    callCount: number
  ): Promise<TerminalDraft> {
    if (request.protocol_version !== "1.1" && request.protocol_version !== "1.2") {
      return {
        status: "FAILED",
        failure: failure(
          "runtime_fake_mcp_protocol_unsupported",
          "CONFIGURATION",
          "确定性 MCP 验收只支持 Runtime v1.1/v1.2"
        ),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    const binding = request.mcp_servers
      .find((server) => server.server_code === serverCode)
      ?.tools.find((tool) => tool.tool_name === toolName);
    if (!binding) {
      return {
        status: "FAILED",
        failure: failure(
          "runtime_fake_mcp_binding_missing",
          "CONFIGURATION",
          "确定性 MCP 验收缺少冻结工具绑定"
        ),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    const calls = Array.from({ length: callCount }, () => ({
      toolCallId: `fake-${serverCode}-${crypto.randomUUID()}`,
      correlationId: `fake-${serverCode}-${crypto.randomUUID()}`
    }));
    for (const call of calls) {
      emitter.emit("tool_event", {
        tool_call_id: call.toolCallId,
        tool_origin: "mcp",
        server_code: serverCode,
        mcp_call_id: null,
        persisted_tool_call_id: null,
        tool_name: toolName,
        status: "STARTED",
        request_summary: { available: true },
        response_summary: { available: false },
        duration_ms: 0
      });
    }
    try {
      const results = await Promise.all(
        calls.map(async (call) => {
          const started = performance.now();
          const ids = await this.callMcpTool(
            request,
            serverCode,
            toolName,
            args,
            principalToken,
            call.correlationId
          );
          emitter.emit("tool_event", {
            tool_call_id: call.toolCallId,
            tool_origin: "mcp",
            server_code: serverCode,
            mcp_call_id: ids.mcpCallId,
            persisted_tool_call_id: ids.agentToolCallId,
            tool_name: toolName,
            status: "SUCCEEDED",
            request_summary: { available: true },
            response_summary: { available: true },
            duration_ms: Math.max(0, Math.trunc(performance.now() - started))
          });
          return ids;
        })
      );
      if (results.length !== callCount) throw new Error("incomplete deterministic MCP calls");
    } catch {
      for (const call of calls) {
        emitter.emit("tool_event", {
          tool_call_id: call.toolCallId,
          tool_origin: "mcp",
          server_code: serverCode,
          mcp_call_id: null,
          persisted_tool_call_id: null,
          tool_name: toolName,
          status: "FAILED",
          request_summary: { available: true },
          response_summary: { available: false },
          duration_ms: 0,
          failure: failure(
            "runtime_fake_mcp_failed",
            "NEVER",
            "确定性 MCP 验收调用失败"
          )
        });
      }
      return {
        status: "FAILED",
        failure: failure(
          "runtime_fake_mcp_failed",
          "NEVER",
          "确定性 MCP 验收调用失败"
        ),
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: runtimeProvenance
      };
    }
    return {
      status: "SUCCEEDED",
      final_answer: `TypeScript Runtime ${serverCode} MCP smoke completed.`,
      usage: { input_tokens: 1, output_tokens: 1 },
      runtime_provenance: runtimeProvenance
    };
  }

  private async callMcpTool(
    request: AgentExecutionRequest,
    serverCode: "tool-mcp" | "ones-mcp",
    toolName: string,
    args: Record<string, unknown>,
    principalToken: string | undefined,
    correlationId: string
  ): Promise<{ mcpCallId: string; agentToolCallId: string }> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "x-invocation-id": request.invocation_id,
      "x-correlation-id": correlationId
    };
    const url = serverCode === "ones-mcp" ? this.onesMcpServerUrl : this.toolMcpServerUrl;
    if (serverCode === "ones-mcp") {
      if (!principalToken) throw new Error("principal token is missing");
      headers.authorization = `Bearer ${principalToken}`;
    } else {
      Object.assign(headers, {
        "x-job-id": request.job_id,
        "x-app-user-id": request.app_user_id,
        "x-project-code": request.project_code,
        "x-agent-publication-id": request.agent_publication_id,
        "x-application-publication-id": request.application_publication_id
      });
    }
    await this.postMcp(url, headers, {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "runtime-acceptance", version: "1" }
      }
    });
    const payload = await this.postMcp(
      url,
      { ...headers, "mcp-protocol-version": "2025-06-18" },
      {
        jsonrpc: "2.0",
        id: 2,
        method: "tools/call",
        params: { name: toolName, arguments: args }
      }
    );
    const result = payload.result;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new Error("deterministic MCP result is missing");
    }
    const values = result as Record<string, unknown>;
    if (values.isError === true) throw new Error("deterministic MCP Tool returned an error");
    const meta = values._meta;
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) {
      throw new Error("deterministic MCP Tool metadata is missing");
    }
    const metadata = meta as Record<string, unknown>;
    const mcpCallId = String(metadata[MCP_CALL_ID_META_KEY] ?? "");
    const agentToolCallId = String(metadata[AGENT_TOOL_CALL_ID_META_KEY] ?? "");
    if (!mcpCallId || !agentToolCallId) {
      throw new Error("deterministic MCP Tool metadata is incomplete");
    }
    return { mcpCallId, agentToolCallId };
  }

  private async postMcp(
    url: string,
    headers: Record<string, string>,
    body: Record<string, unknown>
  ): Promise<Record<string, unknown>> {
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      redirect: "error",
      signal: AbortSignal.timeout(10_000)
    });
    if (!response.ok) throw new Error("deterministic MCP HTTP request failed");
    let text = await response.text();
    if (text.length > 1024 * 1024) throw new Error("deterministic MCP response is too large");
    if ((response.headers.get("content-type") ?? "").includes("text/event-stream")) {
      const lines = text
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());
      const last = lines.at(-1);
      if (!last) throw new Error("deterministic MCP SSE response is empty");
      text = last;
    }
    const decoded: unknown = JSON.parse(text);
    if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
      throw new Error("deterministic MCP response is invalid");
    }
    return decoded as Record<string, unknown>;
  }
}
