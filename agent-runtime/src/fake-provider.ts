import type {
  AgentExecutionRequestV1,
  RuntimeFailure,
  RuntimeProvenance
} from "./generated/contracts.js";
import type {
  ExecutionEmitter,
  RuntimeExecutor,
  TerminalDraft
} from "./invocation-registry.js";
import type { ModelBindingPort } from "./claude-runtime.js";

function failure(
  code: string,
  retryClass: RuntimeFailure["retry_class"],
  safeMessage: string
): RuntimeFailure {
  return { code, retry_class: retryClass, safe_message: safeMessage };
}

function provenance(
  request: AgentExecutionRequestV1,
  configHash: string
): RuntimeProvenance {
  return {
    runtime_kind: "typescript-v1",
    runtime_version: "0.1.0",
    protocol_version: "1.0",
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

  constructor(private readonly modelBindings: ModelBindingPort) {
    this.execute = this.run.bind(this);
  }

  private async run(
    request: AgentExecutionRequestV1,
    emitter: ExecutionEmitter
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
}
