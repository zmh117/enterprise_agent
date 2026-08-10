import type { Pool } from "pg";

import type {
  AgentExecutionRequestV1,
  RuntimeEvent
} from "./generated/contracts.js";
import { assertContract } from "./generated/validators.js";

export interface PersistedTerminal {
  readonly requestDigest: string;
  readonly events: RuntimeEvent[];
  readonly terminalAt: Date;
}

export interface TerminalLedger {
  load(invocationId: string): Promise<PersistedTerminal | undefined>;
  save(
    request: AgentExecutionRequestV1,
    events: readonly RuntimeEvent[],
    terminalAt: Date
  ): Promise<void>;
}

export class TerminalLedgerConflictError extends Error {
  readonly code = "runtime_terminal_ledger_conflict";

  constructor() {
    super("persisted invocation terminal conflicts with the execution request");
    this.name = "TerminalLedgerConflictError";
  }
}

export class PostgresTerminalLedger implements TerminalLedger {
  constructor(
    private readonly pool: Pool,
    private readonly ttlSeconds: number,
    private readonly now: () => Date = () => new Date()
  ) {}

  async load(invocationId: string): Promise<PersistedTerminal | undefined> {
    await this.prune();
    const result = await this.pool.query<{
      request_digest: string;
      events_json: string;
      terminal_at: string | Date;
    }>(
      `SELECT request_digest, events_json, terminal_at
         FROM agent_runtime_terminal_ledger
        WHERE invocation_id = $1 AND expires_at >= $2`,
      [invocationId, this.now().toISOString()]
    );
    const row = result.rows[0];
    if (!row) return undefined;
    let events: unknown;
    try {
      events = JSON.parse(row.events_json);
    } catch {
      throw new TerminalLedgerConflictError();
    }
    if (!Array.isArray(events) || events.length === 0) {
      throw new TerminalLedgerConflictError();
    }
    for (const event of events) assertContract("RuntimeEvent", event);
    const normalized = events as RuntimeEvent[];
    if (normalized.at(-1)?.event_type !== "terminal") {
      throw new TerminalLedgerConflictError();
    }
    return {
      requestDigest: row.request_digest,
      events: normalized,
      terminalAt: new Date(row.terminal_at)
    };
  }

  async save(
    request: AgentExecutionRequestV1,
    events: readonly RuntimeEvent[],
    terminalAt: Date
  ): Promise<void> {
    if (events.at(-1)?.event_type !== "terminal") {
      throw new TerminalLedgerConflictError();
    }
    for (const event of events) assertContract("RuntimeEvent", event);
    const eventsJson = JSON.stringify(events);
    const expiresAt = new Date(terminalAt.getTime() + this.ttlSeconds * 1000);
    await this.pool.query(
      `INSERT INTO agent_runtime_terminal_ledger
        (invocation_id, request_digest, events_json, terminal_at, expires_at)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (invocation_id) DO NOTHING`,
      [
        request.invocation_id,
        request.request_digest,
        eventsJson,
        terminalAt.toISOString(),
        expiresAt.toISOString()
      ]
    );
    const persisted = await this.pool.query<{
      request_digest: string;
      events_json: string;
    }>(
      `SELECT request_digest, events_json
         FROM agent_runtime_terminal_ledger
        WHERE invocation_id = $1`,
      [request.invocation_id]
    );
    const row = persisted.rows[0];
    if (
      !row ||
      row.request_digest !== request.request_digest ||
      row.events_json !== eventsJson
    ) {
      throw new TerminalLedgerConflictError();
    }
  }

  private async prune(): Promise<void> {
    await this.pool.query(
      "DELETE FROM agent_runtime_terminal_ledger WHERE expires_at < $1",
      [this.now().toISOString()]
    );
  }
}
