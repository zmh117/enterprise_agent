import { timingSafeEqual } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  query as claudeQuery,
  type Options,
  type SDKMessage
} from "@anthropic-ai/claude-agent-sdk";

import { isolatedSdkEnvironment, type ClaudeQuery } from "./claude-runtime.js";
import type {
  DraftModelProbeRequest,
  ModelProbeRequest,
  ModelProbeResponse
} from "./generated/contracts.js";
import { assertContract } from "./generated/validators.js";
import type { ResolvedModelBinding } from "./model-binding.js";

const RUNTIME_VERSION = "0.1.0";
const SDK_VERSION = "0.3.226";
const PROBE_PROMPT = "Reply with the single word OK. Do not call tools.";
const PROBE_SYSTEM_PROMPT =
  "This is a connection health probe. Do not use tools, files, network tools, skills, or external context.";

export class ModelProbeAuthenticationError extends Error {
  readonly code = "model_probe_authentication_failed";
}

export interface ModelProbeBindingPort {
  resolve(request: ModelProbeRequest): Promise<ResolvedModelBinding>;
  resolveDraft(request: DraftModelProbeRequest): Promise<ResolvedModelBinding>;
}

type ProbeExecutionRequest = Pick<
  ModelProbeRequest,
  "probe_id" | "timeout_seconds"
>;

export function verifyModelProbeToken(expected: string, provided: string): void {
  const expectedBuffer = Buffer.from(expected, "utf8");
  const providedBuffer = Buffer.from(provided, "utf8");
  if (
    expectedBuffer.length < 32 ||
    providedBuffer.length !== expectedBuffer.length ||
    !timingSafeEqual(expectedBuffer, providedBuffer)
  ) {
    throw new ModelProbeAuthenticationError("Model probe service identity is invalid");
  }
}

function classifyFailure(message: string): ModelProbeResponse["failure"] {
  const normalized = message.toLowerCase();
  if (normalized.includes("401") || normalized.includes("authentication")) {
    return { code: "model_connection_credential_rejected", safe_message: "模型连接认证失败" };
  }
  if (normalized.includes("429") || normalized.includes("rate limit")) {
    return { code: "model_connection_rate_limited", safe_message: "模型服务当前繁忙" };
  }
  if (normalized.includes("timeout") || normalized.includes("abort")) {
    return { code: "model_connection_test_timeout", safe_message: "模型连接测试超时" };
  }
  return { code: "model_connection_test_failed", safe_message: "模型连接测试失败" };
}

export class ModelConnectionProbe {
  constructor(
    private readonly modelBindings: ModelProbeBindingPort,
    private readonly query: ClaudeQuery = claudeQuery,
    private readonly fetcher: typeof fetch = fetch,
    private readonly now: () => number = () => Date.now()
  ) {}

  async run(request: ModelProbeRequest): Promise<ModelProbeResponse> {
    assertContract("ModelProbeRequest", request);
    return this.runResolved(request, await this.modelBindings.resolve(request));
  }

  async runDraft(request: DraftModelProbeRequest): Promise<ModelProbeResponse> {
    assertContract("DraftModelProbeRequest", request);
    return this.runResolved(request, await this.modelBindings.resolveDraft(request));
  }

  private async runResolved(
    request: ProbeExecutionRequest,
    binding: ResolvedModelBinding
  ): Promise<ModelProbeResponse> {
    const started = this.now();
    const workspace = await mkdtemp(join(tmpdir(), "enterprise-agent-model-probe-"));
    const abortController = new AbortController();
    const timeout = setTimeout(
      () => abortController.abort("model_probe_timeout"),
      request.timeout_seconds * 1000
    );
    let failure: ModelProbeResponse["failure"] | undefined;
    let succeeded = false;
    try {
      const redirectResponse = await this.fetcher(binding.baseUrl, {
        method: "HEAD",
        redirect: "manual",
        signal: AbortSignal.timeout(Math.min(request.timeout_seconds * 1000, 5000))
      });
      if (redirectResponse.status >= 300 && redirectResponse.status < 400) {
        throw new Error("model provider redirect is forbidden");
      }
      const options: Options = {
        abortController,
        model: binding.model,
        systemPrompt: PROBE_SYSTEM_PROMPT,
        settingSources: [],
        strictMcpConfig: true,
        mcpServers: {},
        tools: [],
        skills: [],
        allowedTools: [],
        disallowedTools: [
          "Bash",
          "Write",
          "Edit",
          "NotebookEdit",
          "WebFetch",
          "WebSearch",
          "Shell"
        ],
        permissionMode: "dontAsk",
        persistSession: false,
        cwd: workspace,
        env: isolatedSdkEnvironment(binding, workspace),
        maxTurns: 1,
        effort: binding.effortLevel,
        includePartialMessages: false,
        forwardSubagentText: false,
        onElicitation: async () => ({ action: "decline" }),
        canUseTool: async (_toolName, _input, permissionOptions) => ({
          behavior: "deny",
          message: "Tools are disabled for model connection probes",
          interrupt: false,
          toolUseID: permissionOptions.toolUseID
        })
      };
      for await (const message of this.query({ prompt: PROBE_PROMPT, options })) {
        const candidate = message as SDKMessage;
        if (candidate.type !== "result") continue;
        succeeded = candidate.subtype === "success" && !candidate.is_error;
        if (!succeeded) failure = classifyFailure(candidate.subtype);
      }
      if (!succeeded && !failure) {
        failure = {
          code: "model_connection_test_failed",
          safe_message: "模型连接测试未返回有效终态"
        };
      }
    } catch (error) {
      failure = classifyFailure(error instanceof Error ? error.message : "unknown");
    } finally {
      clearTimeout(timeout);
      await rm(workspace, { recursive: true, force: true });
    }
    const response: ModelProbeResponse = {
      protocol_version: "1.0",
      runtime_kind: "typescript-v1",
      probe_id: request.probe_id,
      success: succeeded,
      connection_revision_id: binding.connectionRevisionId,
      provider_host: new URL(binding.baseUrl).hostname,
      model: binding.model,
      runtime_version: RUNTIME_VERSION,
      sdk_version: SDK_VERSION,
      duration_ms: Math.min(30000, Math.max(0, this.now() - started)),
      ...(failure ? { failure } : {})
    };
    assertContract("ModelProbeResponse", response);
    return response;
  }
}
