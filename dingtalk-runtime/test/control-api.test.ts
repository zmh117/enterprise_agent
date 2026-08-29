import assert from "node:assert/strict";
import test from "node:test";
import {
  CardCallbackInputError,
  ControlApi,
  ControlApiError,
} from "../src/control-api.js";

test("submit reports compact UTF-8 JSON byte count", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        acknowledged: true,
        created: true,
        event_id: "event-1",
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  };
  try {
    const api = new ControlApi({
      baseUrl: "http://control-api.test",
      token: "runtime-token",
    });
    const normalized = {
      conversationId: "群聊-1",
      text: { content: "查询嵌套消息" },
    };
    await api.submit("runtime-1", "lease-1", "connector-1", {
      headers: { messageId: "message-1" },
      data: JSON.stringify(normalized),
    });

    assert.equal(
      requestBody?.request_bytes,
      Buffer.byteLength(JSON.stringify(normalized))
    );
    assert.deepEqual(requestBody?.normalized_event, normalized);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submit uses DingTalk msgId as the stable external event ID for quoted replies", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        acknowledged: true,
        created: true,
        event_id: "event-1",
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  };
  try {
    const api = new ControlApi({
      baseUrl: "http://control-api.test",
      token: "runtime-token",
    });
    await api.submit("runtime-1", "lease-1", "connector-1", {
      headers: { messageId: "header-message", eventId: "header-event" },
      data: JSON.stringify({
        msgId: "dingtalk-message",
        originalMsgId: "quoted-message",
        text: { content: "1" },
      }),
    });

    assert.equal(requestBody?.external_event_id, "dingtalk-message");
    assert.deepEqual(requestBody?.safe_summary, {
      msgtype: "",
      conversationType: "",
      hasText: true,
      hasQuote: true,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("control API errors expose only a validated safe error code", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: {
          code: "validation_failed",
          message: "sensitive server detail must not enter the runtime error",
        },
      }),
      {
        status: 400,
        headers: { "content-type": "application/json" },
      }
    );
  try {
    const api = new ControlApi({
      baseUrl: "http://control-api.test",
      token: "runtime-token",
    });
    await assert.rejects(
      api.submit("runtime-1", "lease-1", "connector-1", {
        headers: { messageId: "message-1" },
        data: JSON.stringify({ text: { content: "private" } }),
      }),
      (error: unknown) =>
        error instanceof ControlApiError &&
        error.status === 400 &&
        error.code === "validation_failed" &&
        !error.message.includes("sensitive server detail")
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("card callback forwards only governed action facts", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        acknowledged: true,
        duplicate: false,
        status: "APPROVED",
        response: {},
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };
  try {
    const api = new ControlApi({
      baseUrl: "http://control-api.test",
      token: "runtime-token",
    });
    await api.submitCardAction("runtime-1", "lease-1", "connector-1", {
      headers: { messageId: "message-1" },
      data: JSON.stringify({
        corpId: "corp-1",
        outTrackId: "action-1",
        userId: "staff-1",
        content: JSON.stringify({
          cardPrivateData: {
            params: {
              action: "confirm",
              expectedRevision: "2",
              intentToken: "v1.2.signature",
              supplement: "must not be forwarded in MVP",
            },
          },
        }),
      }),
    });
    assert.deepEqual(requestBody, {
      runtime_id: "runtime-1",
      lease_token: "lease-1",
      connector_id: "connector-1",
      corp_id: "corp-1",
      out_track_id: "action-1",
      user_id: "staff-1",
      action: "agree",
      revision: 2,
      intent_token: "v1.2.signature",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("card callback fails closed when the private intent token is absent", async () => {
  const api = new ControlApi({
    baseUrl: "http://control-api.test",
    token: "runtime-token",
  });
  await assert.rejects(
    api.submitCardAction("runtime-1", "lease-1", "connector-1", {
      headers: { messageId: "message-1" },
      data: JSON.stringify({
        corpId: "corp-1",
        outTrackId: "action-1",
        userId: "staff-1",
        content: JSON.stringify({
          cardPrivateData: {
            params: {
              action: "confirm",
              expectedRevision: "2",
            },
          },
        }),
      }),
    }),
    (error: unknown) =>
      error instanceof CardCallbackInputError &&
      error.code === "callback_token_missing"
  );
});
