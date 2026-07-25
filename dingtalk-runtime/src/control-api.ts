import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import type {
  ConnectorState,
  DesiredSnapshot,
  RuntimeLease,
} from "./contracts.js";

export class ControlApi {
  readonly baseUrl: string;
  readonly token: string;
  readonly timeoutMs: number;

  constructor(options: {
    baseUrl: string;
    token?: string;
    tokenFile?: string;
    timeoutMs?: number;
  }) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.token =
      options.token ??
      (options.tokenFile ? readFileSync(options.tokenFile, "utf8").trim() : "");
    this.timeoutMs = options.timeoutMs ?? 5_000;
    if (!this.token) throw new Error("DingTalk Runtime auth token is missing");
  }

  acquire(runtimeId: string): Promise<{ lease: RuntimeLease }> {
    return this.request("/lease/acquire", {
      method: "POST",
      body: { runtime_id: runtimeId },
    });
  }

  renew(runtimeId: string, leaseToken: string): Promise<{ lease: RuntimeLease }> {
    return this.request("/lease/renew", {
      method: "POST",
      body: { runtime_id: runtimeId, lease_token: leaseToken },
    });
  }

  release(runtimeId: string, leaseToken: string): Promise<{ released: boolean }> {
    return this.request("/lease/release", {
      method: "POST",
      body: { runtime_id: runtimeId, lease_token: leaseToken },
    });
  }

  desired(runtimeId: string, leaseToken: string): Promise<DesiredSnapshot> {
    return this.request("/desired-config", {
      method: "POST",
      body: { runtime_id: runtimeId, lease_token: leaseToken },
    });
  }

  report(
    runtimeId: string,
    leaseToken: string,
    states: ConnectorState[]
  ): Promise<{ status: string }> {
    return this.request("/states", {
      method: "POST",
      body: { runtime_id: runtimeId, lease_token: leaseToken, states },
    });
  }

  async submit(
    runtimeId: string,
    leaseToken: string,
    connectorId: string,
    envelope: { headers: { messageId: string; eventId?: string }; data: string }
  ): Promise<{ acknowledged: boolean; created: boolean; event_id: string }> {
    const parsed: unknown = JSON.parse(envelope.data);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("DingTalk callback payload is not an object");
    }
    const normalized = parsed as Record<string, unknown>;
    const encoded = JSON.stringify(normalized);
    const externalEventId =
      String(envelope.headers.eventId ?? "") ||
      String(normalized.eventId ?? normalized.msgId ?? envelope.headers.messageId);
    if (!externalEventId) throw new Error("DingTalk callback has no event ID");
    return this.request("/inbox", {
      method: "POST",
      body: {
        runtime_id: runtimeId,
        lease_token: leaseToken,
        connector_id: connectorId,
        external_event_id: externalEventId,
        correlation_id: randomUUID(),
        normalized_event: normalized,
        safe_summary: {
          msgtype: normalized.msgtype ?? "",
          conversationType: normalized.conversationType ?? "",
          hasText: Boolean(normalized.text),
        },
        payload_hash: createHash("sha256").update(encoded).digest("hex"),
        request_bytes: Buffer.byteLength(encoded),
      },
    });
  }

  private async request<T>(
    path: string,
    options: { method: "GET" | "POST"; body?: unknown }
  ): Promise<T> {
    const signal = AbortSignal.timeout(this.timeoutMs);
    const init: RequestInit = {
      method: options.method,
      headers: {
        authorization: `Bearer ${this.token}`,
        "content-type": "application/json",
      },
      signal,
    };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    const response = await fetch(`${this.baseUrl}${path}`, init);
    if (!response.ok) {
      throw new ControlApiError(
        response.status,
        await readSafeErrorCode(response)
      );
    }
    return (await response.json()) as T;
  }
}

export class ControlApiError extends Error {
  constructor(
    readonly status: number,
    readonly code = ""
  ) {
    super(
      `Control API request failed status=${status}` +
        (code ? ` code=${code}` : "")
    );
    this.name = "ControlApiError";
  }
}

async function readSafeErrorCode(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return "";
    }
    const detail = (payload as Record<string, unknown>).detail;
    if (!detail || typeof detail !== "object" || Array.isArray(detail)) {
      return "";
    }
    const code = (detail as Record<string, unknown>).code;
    if (typeof code !== "string" || !/^[a-z0-9_.-]{1,120}$/i.test(code)) {
      return "";
    }
    return code;
  } catch {
    return "";
  }
}
