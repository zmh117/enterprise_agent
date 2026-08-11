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

export interface PersistedClaim {
  readonly status: "CLAIMED" | "ORPHANED";
  readonly events: RuntimeEvent[];
}

export interface TerminalLedger {
  load(invocationId: string): Promise<PersistedTerminal | undefined>;
  claim(
    request: AgentExecutionRequestV1,
    ownerInstanceId: string
  ): Promise<PersistedClaim>;
  append(request: AgentExecutionRequestV1, event: RuntimeEvent): Promise<void>;
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

  async claim(
    request: AgentExecutionRequestV1,
    ownerInstanceId: string
  ): Promise<PersistedClaim> {
    const now = this.now();
    const expiresAt = new Date(now.getTime() + this.ttlSeconds * 1000);
    await this.pool.query(
      `INSERT INTO agent_runtime_invocation_claim
        (invocation_id, request_digest, runtime_kind, owner_instance_id, claimed_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (invocation_id) DO NOTHING`,
      [
        request.invocation_id,
        request.request_digest,
        request.runtime_kind,
        ownerInstanceId,
        now.toISOString(),
        expiresAt.toISOString()
      ]
    );
    const persisted = await this.pool.query<{
      request_digest: string;
      runtime_kind: string;
      owner_instance_id: string;
    }>(
      `SELECT request_digest, runtime_kind, owner_instance_id
         FROM agent_runtime_invocation_claim
        WHERE invocation_id = $1`,
      [request.invocation_id]
    );
    const row = persisted.rows[0];
    if (
      !row ||
      row.request_digest !== request.request_digest ||
      row.runtime_kind !== request.runtime_kind
    ) {
      throw new TerminalLedgerConflictError();
    }
    const events = await this.loadInvocationEvents(request);
    return {
      status: row.owner_instance_id === ownerInstanceId ? "CLAIMED" : "ORPHANED",
      events
    };
  }

  async append(
    request: AgentExecutionRequestV1,
    event: RuntimeEvent
  ): Promise<void> {
    assertContract("RuntimeEvent", event);
    if (
      event.event_type === "terminal" ||
      event.invocation_id !== request.invocation_id ||
      event.request_digest !== request.request_digest
    ) {
      throw new TerminalLedgerConflictError();
    }
    const encoded = JSON.stringify(event);
    const now = this.now();
    const expiresAt = new Date(now.getTime() + this.ttlSeconds * 1000);
    await this.pool.query(
      `INSERT INTO agent_runtime_invocation_event
        (invocation_id, request_digest, sequence, event_json, created_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (invocation_id, sequence) DO NOTHING`,
      [
        request.invocation_id,
        request.request_digest,
        event.sequence,
        encoded,
        now.toISOString(),
        expiresAt.toISOString()
      ]
    );
    const persisted = await this.pool.query<{
      request_digest: string;
      event_json: string;
    }>(
      `SELECT request_digest, event_json
         FROM agent_runtime_invocation_event
        WHERE invocation_id = $1 AND sequence = $2`,
      [request.invocation_id, event.sequence]
    );
    const row = persisted.rows[0];
    if (
      !row ||
      row.request_digest !== request.request_digest ||
      row.event_json !== encoded
    ) {
      throw new TerminalLedgerConflictError();
    }
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
    await this.pool.query(
      `DELETE FROM agent_runtime_invocation_claim
        WHERE invocation_id = $1 AND request_digest = $2`,
      [request.invocation_id, request.request_digest]
    );
    await this.pool.query(
      `DELETE FROM agent_runtime_invocation_event
        WHERE invocation_id = $1 AND request_digest = $2`,
      [request.invocation_id, request.request_digest]
    );
  }

  private async loadInvocationEvents(
    request: AgentExecutionRequestV1
  ): Promise<RuntimeEvent[]> {
    const result = await this.pool.query<{
      request_digest: string;
      sequence: number;
      event_json: string;
    }>(
      `SELECT request_digest, sequence, event_json
         FROM agent_runtime_invocation_event
        WHERE invocation_id = $1
        ORDER BY sequence`,
      [request.invocation_id]
    );
    return result.rows.map((row, index) => {
      if (
        row.request_digest !== request.request_digest ||
        row.sequence !== index + 1
      ) {
        throw new TerminalLedgerConflictError();
      }
      let event: unknown;
      try {
        event = JSON.parse(row.event_json);
        assertContract("RuntimeEvent", event);
      } catch {
        throw new TerminalLedgerConflictError();
      }
      const normalized = event as RuntimeEvent;
      if (
        normalized.event_type === "terminal" ||
        normalized.invocation_id !== request.invocation_id ||
        normalized.request_digest !== request.request_digest ||
        normalized.sequence !== row.sequence
      ) {
        throw new TerminalLedgerConflictError();
      }
      return normalized;
    });
  }

  private async prune(): Promise<void> {
    await this.pool.query(
      "DELETE FROM agent_runtime_terminal_ledger WHERE expires_at < $1",
      [this.now().toISOString()]
    );
    await this.pool.query(
      "DELETE FROM agent_runtime_invocation_claim WHERE expires_at < $1",
      [this.now().toISOString()]
    );
    await this.pool.query(
      "DELETE FROM agent_runtime_invocation_event WHERE expires_at < $1",
      [this.now().toISOString()]
    );
  }
}
