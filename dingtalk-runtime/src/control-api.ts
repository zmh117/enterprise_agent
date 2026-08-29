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
      String(normalized.msgId ?? "") ||
      String(normalized.eventId ?? envelope.headers.eventId ?? envelope.headers.messageId);
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
          hasQuote: Boolean(normalized.originalMsgId),
        },
        payload_hash: createHash("sha256").update(encoded).digest("hex"),
        request_bytes: Buffer.byteLength(encoded),
      },
    });
  }

  async submitCardAction(
    runtimeId: string,
    leaseToken: string,
    connectorId: string,
    envelope: { headers: { messageId: string }; data: string }
  ): Promise<{
    acknowledged: boolean;
    duplicate: boolean;
    status: string;
    response: Record<string, unknown>;
  }> {
    const outer = parseCardObject(
      envelope.data,
      "callback_payload_invalid"
    );
    const content =
      typeof outer.content === "string"
        ? parseCardObject(outer.content, "callback_content_invalid")
        : firstDecodedObject(outer.content) ?? {};
    const nestedAction = firstDecodedObject(
      content.cardActionData,
      content.CardActionData,
      outer.cardActionData,
      outer.CardActionData
    );
    const actionContainer = firstDecodedObject(
      content.cardPrivateData,
      content.CardPrivateData,
      nestedAction?.cardPrivateData,
      nestedAction?.CardPrivateData,
      outer.cardPrivateData,
      outer.CardPrivateData
    );
    if (!actionContainer) {
      throw new CardCallbackInputError("callback_action_container_missing");
    }
    const rawActionIds = actionContainer.actionIds ?? actionContainer.ActionIds;
    const actionIds = Array.isArray(rawActionIds)
      ? rawActionIds.filter(
          (value): value is string => typeof value === "string"
        )
      : [];
    const params = firstDecodedObject(
      actionContainer.params,
      actionContainer.Params
    );
    if (!params) {
      throw new CardCallbackInputError("callback_params_missing");
    }
    const allowedActions = ["agree", "confirm", "reject", "revise"];
    const parameterAction = boundedString(params?.action, 32);
    const semanticActionIds = actionIds.filter((value) =>
      allowedActions.includes(value)
    );
    if (parameterAction && !allowedActions.includes(parameterAction)) {
      throw new CardCallbackInputError("callback_action_invalid");
    }
    if (
      parameterAction &&
      semanticActionIds.some((value) => value !== parameterAction)
    ) {
      throw new CardCallbackInputError("callback_action_inconsistent");
    }
    const templateAction = parameterAction || semanticActionIds[0] || "";
    if (!templateAction || (!parameterAction && semanticActionIds.length !== 1)) {
      throw new CardCallbackInputError("callback_action_missing");
    }
    // The current confirmation template calls its positive action `confirm`.
    // Keep the control-plane domain vocabulary stable and remain compatible
    // with already-published cards that used the older `agree` action ID.
    const action = templateAction === "confirm" ? "agree" : templateAction;
    const revision = Number(
      params?.revisionNo ?? params?.expectedRevision ?? params?.revision ?? 0
    );
    const intentToken = boundedString(params?.intentToken, 256);
    const outTrackId = boundedString(
      outer.outTrackId ?? content.outTrackId,
      128
    );
    const userId = boundedString(outer.userId ?? content.userId, 256);
    const corpId = boundedString(outer.corpId ?? content.corpId, 128);
    if (!Number.isSafeInteger(revision) || revision < 1) {
      throw new CardCallbackInputError("callback_revision_invalid");
    }
    if (!intentToken) {
      throw new CardCallbackInputError("callback_token_missing");
    }
    if (!outTrackId) {
      throw new CardCallbackInputError("callback_out_track_missing");
    }
    if (!userId) {
      throw new CardCallbackInputError("callback_user_missing");
    }
    if (!corpId) {
      throw new CardCallbackInputError("callback_corp_missing");
    }
    return this.request("/card-actions", {
      method: "POST",
      body: {
        runtime_id: runtimeId,
        lease_token: leaseToken,
        connector_id: connectorId,
        corp_id: corpId,
        out_track_id: outTrackId,
        user_id: userId,
        action,
        revision,
        intent_token: intentToken,
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

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} payload is not an object`);
  }
  return parsed as Record<string, unknown>;
}

function firstObject(...values: unknown[]): Record<string, unknown> | undefined {
  return values.find(
    (value): value is Record<string, unknown> =>
      Boolean(value) && typeof value === "object" && !Array.isArray(value)
  );
}

function firstDecodedObject(
  ...values: unknown[]
): Record<string, unknown> | undefined {
  for (const value of values) {
    const direct = firstObject(value);
    if (direct) return direct;
    if (typeof value !== "string") continue;
    try {
      const parsed: unknown = JSON.parse(value);
      const decoded = firstObject(parsed);
      if (decoded) return decoded;
    } catch {
      // A later candidate may still contain the governed object.
    }
  }
  return undefined;
}

function parseCardObject(
  value: string,
  code: string
): Record<string, unknown> {
  try {
    return parseObject(value, "DingTalk card callback");
  } catch {
    throw new CardCallbackInputError(code);
  }
}

function boundedString(value: unknown, maximum: number): string {
  return typeof value === "string" && value.length <= maximum ? value : "";
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

export class CardCallbackInputError extends Error {
  constructor(readonly code: string) {
    super("DingTalk card callback failed bounded validation");
    this.name = "CardCallbackInputError";
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
