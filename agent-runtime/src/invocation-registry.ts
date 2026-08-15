import type {
  AgentExecutionRequest,
  ExecutionAccounting,
  RuntimeEvent,
  RuntimeFailure,
  RuntimeProvenance,
  TerminalResult,
  Usage
} from "./runtime-contracts.js";
import { randomUUID } from "node:crypto";
import { assertRuntimeContract } from "./runtime-contracts.js";
import type { TerminalLedger } from "./terminal-ledger.js";

export interface ExecutionEmitter {
  readonly signal: AbortSignal;
  emit(
    eventType:
      | "execution_started"
      | "runtime_initialized"
      | "model_call"
      | "api_retry"
      | "tool_event"
      | "assistant_text",
    payload: RuntimeEvent["payload"]
  ): void;
}

export interface InvocationSecretContext {
  readonly principalToken?: string;
  readonly filePrincipalToken?: string;
}

export interface TerminalDraft {
  readonly status: "SUCCEEDED" | "FAILED" | "CANCELLED";
  readonly final_answer?: string;
  readonly failure?: RuntimeFailure;
  readonly usage: Usage;
  readonly accounting?: ExecutionAccounting;
  readonly runtime_provenance: RuntimeProvenance;
}

export type RuntimeExecutor = (
  request: AgentExecutionRequest,
  emitter: ExecutionEmitter,
  secrets?: InvocationSecretContext
) => Promise<TerminalDraft>;

export class InvocationConflictError extends Error {
  readonly code = "runtime_invocation_conflict";

  constructor() {
    super("invocation_id is already bound to a different request digest");
    this.name = "InvocationConflictError";
  }
}

type EventListener = (event: RuntimeEvent) => void;

class InvocationRecord {
  readonly abortController = new AbortController();
  readonly events: RuntimeEvent[] = [];
  readonly listeners = new Set<EventListener>();
  terminalAt = 0;

  constructor(
    readonly request: AgentExecutionRequest,
    readonly secrets: InvocationSecretContext,
    private readonly now: () => Date
  ) {}

  get isTerminal(): boolean {
    return this.events.at(-1)?.event_type === "terminal";
  }

  prepareEvent(
    eventType:
      | "execution_started"
      | "runtime_initialized"
      | "model_call"
      | "api_retry"
      | "tool_event"
      | "assistant_text",
    payload: RuntimeEvent["payload"]
  ): RuntimeEvent | undefined {
    if (this.isTerminal) return undefined;
    const event = {
      protocol_version: this.request.protocol_version,
      invocation_id: this.request.invocation_id,
      request_digest: this.request.request_digest,
      sequence: this.events.length + 1,
      event_type: eventType,
      timestamp: this.now().toISOString(),
      payload
    } as RuntimeEvent;
    assertRuntimeContract("RuntimeEvent", event, this.request.protocol_version);
    return event;
  }

  commitEvent(event: RuntimeEvent): void {
    if (this.isTerminal) return;
    if (event.sequence !== this.events.length + 1 || event.event_type === "terminal") {
      throw new InvocationConflictError();
    }
    this.append(event);
  }

  prepareTerminal(draft: TerminalDraft): RuntimeEvent | undefined {
    if (this.isTerminal) return undefined;
    const sequence = this.events.length + 1;
    const terminal = {
      protocol_version: this.request.protocol_version,
      invocation_id: this.request.invocation_id,
      request_digest: this.request.request_digest,
      last_sequence: sequence,
      status: draft.status,
      ...(draft.final_answer === undefined ? {} : { final_answer: draft.final_answer }),
      ...(draft.failure === undefined ? {} : { failure: draft.failure }),
      usage: draft.usage,
      ...(this.request.protocol_version === "1.2"
        ? {
            accounting:
              draft.accounting ?? {
                status: "UNAVAILABLE",
                duration_ms: null,
                duration_api_ms: null,
                num_turns: null,
                usage: {
                  input_tokens: null,
                  output_tokens: null,
                  cache_read_input_tokens: null,
                  cache_creation_input_tokens: null
                },
                model_usage: [],
                estimated_cost_usd: null,
                permission_denials_count: 0
              }
          }
        : {}),
      runtime_provenance: draft.runtime_provenance
    } as TerminalResult;
    const event = {
      protocol_version: this.request.protocol_version,
      invocation_id: this.request.invocation_id,
      request_digest: this.request.request_digest,
      sequence,
      event_type: "terminal",
      timestamp: this.now().toISOString(),
      payload: terminal
    } as RuntimeEvent;
    assertRuntimeContract("RuntimeEvent", event, this.request.protocol_version);
    return event;
  }

  commitTerminal(event: RuntimeEvent, terminalAt = this.now()): void {
    if (this.isTerminal) return;
    this.append(event);
    this.terminalAt = terminalAt.getTime();
    this.listeners.clear();
  }

  restore(events: readonly RuntimeEvent[], terminalAt: Date): void {
    if (this.events.length > 0) throw new InvocationConflictError();
    for (const [index, event] of events.entries()) {
      assertRuntimeContract("RuntimeEvent", event, this.request.protocol_version);
      if (
        event.invocation_id !== this.request.invocation_id ||
        event.request_digest !== this.request.request_digest ||
        event.sequence !== index + 1
      ) {
        throw new InvocationConflictError();
      }
      this.events.push(event);
    }
    if (!this.isTerminal) throw new InvocationConflictError();
    this.terminalAt = terminalAt.getTime();
  }

  restorePrefix(events: readonly RuntimeEvent[]): void {
    if (this.events.length > 0) throw new InvocationConflictError();
    for (const [index, event] of events.entries()) {
      assertRuntimeContract("RuntimeEvent", event, this.request.protocol_version);
      if (
        event.event_type === "terminal" ||
        event.invocation_id !== this.request.invocation_id ||
        event.request_digest !== this.request.request_digest ||
        event.sequence !== index + 1
      ) {
        throw new InvocationConflictError();
      }
      this.events.push(event);
    }
  }

  subscribe(listener: EventListener): () => void {
    for (const event of this.events) listener(event);
    if (!this.isTerminal) this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private append(event: RuntimeEvent): void {
    assertRuntimeContract("RuntimeEvent", event, this.request.protocol_version);
    this.events.push(event);
    for (const listener of this.listeners) listener(event);
  }
}

export interface InvocationHandle {
  readonly request: AgentExecutionRequest;
  readonly isTerminal: boolean;
  subscribe(listener: EventListener): () => void;
  cancel(reason: string): Promise<void>;
}

export class InvocationRegistry {
  private readonly records = new Map<string, InvocationRecord>();

  constructor(
    private readonly executor: RuntimeExecutor,
    private readonly ttlMilliseconds: number,
    private readonly now: () => Date = () => new Date(),
    private readonly terminalLedger?: TerminalLedger,
    private readonly ownerInstanceId: string = randomUUID()
  ) {}

  async acquire(
    request: AgentExecutionRequest,
    secrets: InvocationSecretContext = {}
  ): Promise<InvocationHandle> {
    this.prune();
    const existing = this.records.get(request.invocation_id);
    if (existing) {
      if (existing.request.request_digest !== request.request_digest) {
        throw new InvocationConflictError();
      }
      return this.handle(existing);
    }
    const record = new InvocationRecord(request, secrets, this.now);
    const persisted = await this.terminalLedger?.load(request.invocation_id);
    if (persisted) {
      if (persisted.requestDigest !== request.request_digest) {
        throw new InvocationConflictError();
      }
      record.restore(persisted.events, persisted.terminalAt);
      this.records.set(request.invocation_id, record);
      return this.handle(record);
    }
    const claim = await this.terminalLedger?.claim(request, this.ownerInstanceId);
    if (claim?.status === "ORPHANED") {
      record.restorePrefix(claim.events);
      this.records.set(request.invocation_id, record);
      await this.finalize(record, {
        status: "FAILED",
        failure: {
          code: "runtime_orphaned_invocation",
          retry_class: "NEVER",
          safe_message: "Agent Runtime 在执行中重启；为避免重复模型调用，本次执行已失败"
        },
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: this.provenance(request)
      });
      return this.handle(record);
    }
    this.records.set(request.invocation_id, record);
    queueMicrotask(() => void this.execute(record));
    return this.handle(record);
  }

  get(invocationId: string): InvocationHandle | undefined {
    const record = this.records.get(invocationId);
    return record ? this.handle(record) : undefined;
  }

  private handle(record: InvocationRecord): InvocationHandle {
    return {
      request: record.request,
      get isTerminal() {
        return record.isTerminal;
      },
      subscribe: (listener) => record.subscribe(listener),
      cancel: async (reason) => {
        if (record.isTerminal) return;
        record.abortController.abort(reason);
        await this.finalize(record, {
          status: "CANCELLED",
          failure: {
            code: "runtime_cancelled",
            retry_class: "NEVER",
            safe_message: "Agent 执行已取消"
          },
          usage: { input_tokens: 0, output_tokens: 0 },
          runtime_provenance: this.provenance(record.request)
        });
      }
    };
  }

  private async execute(record: InvocationRecord): Promise<void> {
    let eventPersistence = Promise.resolve();
    try {
      const terminal = await this.executor(record.request, {
        signal: record.abortController.signal,
        emit: (eventType, payload) => {
          eventPersistence = eventPersistence.then(async () => {
            const event = record.prepareEvent(eventType, payload);
            if (!event) return;
            await this.terminalLedger?.append(record.request, event);
            record.commitEvent(event);
          });
        }
      }, record.secrets);
      await eventPersistence;
      await this.finalize(record, terminal);
    } catch {
      try {
        await eventPersistence;
      } catch {
        // The stable Runtime failure below is persisted when possible.
      }
      await this.finalize(record, {
        status: "FAILED",
        failure: {
          code: "runtime_internal_error",
          retry_class: "TRANSIENT",
          safe_message: "Agent Runtime 暂时不可用，请稍后重试"
        },
        usage: { input_tokens: 0, output_tokens: 0 },
        runtime_provenance: this.provenance(record.request)
      });
    }
  }

  private async finalize(record: InvocationRecord, draft: TerminalDraft): Promise<void> {
    const terminal = record.prepareTerminal(draft);
    if (!terminal) return;
    const terminalAt = this.now();
    if (this.terminalLedger) {
      try {
        await this.terminalLedger.save(
          record.request,
          [...record.events, terminal],
          terminalAt
        );
      } catch {
        const ledgerFailure = record.prepareTerminal({
          status: "FAILED",
          failure: {
            code: "runtime_terminal_ledger_unavailable",
            retry_class: "TRANSIENT",
            safe_message: "Agent Runtime 终态暂时无法保存，请稍后重试"
          },
          usage: { input_tokens: 0, output_tokens: 0 },
          runtime_provenance: this.provenance(record.request)
        });
        if (ledgerFailure) record.commitTerminal(ledgerFailure, terminalAt);
        return;
      }
    }
    record.commitTerminal(terminal, terminalAt);
  }

  private provenance(request: AgentExecutionRequest): RuntimeProvenance {
    return {
      runtime_kind: "typescript-v1",
      runtime_version: "0.1.0",
      protocol_version: request.protocol_version,
      sdk_version: "0.3.226",
      cli_version: "2.1.226",
      model_connection_revision_id: request.model_connection.revision_id,
      model_connection_config_hash: request.model_connection.config_hash
    };
  }

  private prune(): void {
    const cutoff = this.now().getTime() - this.ttlMilliseconds;
    for (const [invocationId, record] of this.records) {
      if (record.terminalAt > 0 && record.terminalAt < cutoff) {
        this.records.delete(invocationId);
      }
    }
  }
}
