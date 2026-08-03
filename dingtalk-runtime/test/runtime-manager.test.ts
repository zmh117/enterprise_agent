import assert from "node:assert/strict";
import test from "node:test";
import type {
  DesiredConnector,
  StreamClient,
  StreamEnvelope,
} from "../src/contracts.js";
import { ControlApiError } from "../src/control-api.js";
import { RuntimeManager } from "../src/runtime-manager.js";

class FakeClient implements StreamClient {
  connected = false;
  registered = false;
  reconnecting = false;
  disconnected = false;
  handler?: (message: StreamEnvelope) => Promise<void>;

  constructor(readonly config: DesiredConnector) {}
  async connect(): Promise<void> {
    if (this.config.client_secret === "bad") throw new Error("unauthorized");
    if (this.config.client_secret === "connected-only") {
      this.connected = true;
      return;
    }
    if (this.config.client_secret === "reconnecting") {
      this.reconnecting = true;
      return;
    }
    this.connected = true;
    this.registered = true;
  }
  disconnect(): void {
    this.connected = false;
    this.registered = false;
    this.disconnected = true;
  }
  onRobotMessage(handler: (message: StreamEnvelope) => Promise<void>): void {
    this.handler = handler;
  }
  acknowledge(): void {}
}

const connector = (
  id: string,
  revision = 1,
  secret = "ok"
): DesiredConnector => ({
  connector_id: id,
  revision,
  name: id,
  client_id: id,
  client_secret: secret,
  tenant_code: "default",
  allow_private_chat: true,
  allow_group_chat: true,
  require_group_at: true,
});

test("clients start, restart, and stop independently", async () => {
  const created = new Map<string, FakeClient[]>();
  const api = { submit: async () => ({ acknowledged: true, created: true, event_id: "e" }) };
  const manager = new RuntimeManager(
    "runtime",
    api as never,
    (config) => {
      const client = new FakeClient(config);
      created.set(config.connector_id, [...(created.get(config.connector_id) ?? []), client]);
      return client;
    },
    "lease"
  );
  await manager.reconcile({ revision: 1, connectors: [connector("a"), connector("b")] });
  assert.equal(manager.counts().registered, 2);
  await manager.reconcile({
    revision: 2,
    connectors: [connector("a", 2), connector("b")],
  });
  assert.equal(created.get("a")?.length, 2);
  assert.equal(created.get("b")?.length, 1);
  assert.equal(manager.counts().registered, 2);
  await manager.reconcile({ revision: 2, connectors: [connector("b")] });
  assert.equal(manager.counts().total, 1);
  assert.equal(manager.states()[0]?.connector_id, "b");
});

test("one client failure does not stop another client", async () => {
  const api = { submit: async () => ({ acknowledged: true, created: true, event_id: "e" }) };
  const manager = new RuntimeManager(
    "runtime",
    api as never,
    (config) => new FakeClient(config),
    "lease"
  );
  await manager.reconcile({
    revision: 1,
    connectors: [connector("bad", 1, "bad"), connector("good")],
  });
  const states = new Map(manager.states().map((state) => [state.connector_id, state]));
  assert.equal(states.get("bad")?.status, "AUTH_FAILED");
  assert.equal(states.get("good")?.status, "REGISTERED");
});

test("connected is not ready and reconnecting remains explicit", async () => {
  const api = { submit: async () => ({ acknowledged: true, created: true, event_id: "e" }) };
  const manager = new RuntimeManager(
    "runtime",
    api as never,
    (config) => new FakeClient(config),
    "lease"
  );
  await manager.reconcile({
    revision: 1,
    connectors: [
      connector("socket-only", 1, "connected-only"),
      connector("reconnecting", 1, "reconnecting"),
    ],
  });
  const states = new Map(manager.states().map((state) => [state.connector_id, state]));
  assert.equal(states.get("socket-only")?.status, "CONNECTED");
  assert.equal(states.get("socket-only")?.registered, false);
  assert.equal(states.get("reconnecting")?.status, "RECONNECTING");
  assert.equal(manager.counts().registered, 0);
});

test("successful inbox submission confirms registration when SDK flag stays false", async () => {
  const clients: FakeClient[] = [];
  const api = {
    submit: async () => ({ acknowledged: true, created: true, event_id: "e" }),
  };
  const manager = new RuntimeManager(
    "runtime",
    api as never,
    (config) => {
      const client = new FakeClient(config);
      clients.push(client);
      return client;
    },
    "lease"
  );
  await manager.reconcile({
    revision: 1,
    connectors: [connector("socket-only", 1, "connected-only")],
  });
  assert.equal(manager.states()[0]?.status, "CONNECTED");
  assert.equal(manager.states()[0]?.registered, false);

  const message = {
    headers: { messageId: "message-1", topic: "robot" },
    data: JSON.stringify({ text: { content: "registration proof" } }),
  };
  await clients[0]?.handler?.(message);

  assert.equal(manager.states()[0]?.status, "REGISTERED");
  assert.equal(manager.states()[0]?.registered, true);
  assert.equal(manager.counts().registered, 1);

  const client = clients[0];
  assert.ok(client);
  client.connected = false;
  client.reconnecting = true;
  assert.equal(manager.states()[0]?.status, "RECONNECTING");
  assert.equal(manager.states()[0]?.registered, false);

  client.connected = true;
  client.reconnecting = false;
  assert.equal(manager.states()[0]?.status, "CONNECTED");
  assert.equal(manager.states()[0]?.registered, false);
  await client.handler?.(message);
  assert.equal(manager.states()[0]?.status, "REGISTERED");
  assert.equal(manager.states()[0]?.registered, true);
});

test("inbox rejection is reported without logging message content", async () => {
  const clients: FakeClient[] = [];
  const warnings: string[] = [];
  const originalWarn = console.warn;
  console.warn = (message?: unknown) => warnings.push(String(message));
  try {
    const api = {
      submit: async () => {
        throw new ControlApiError(400, "validation_failed");
      },
    };
    const manager = new RuntimeManager(
      "runtime",
      api as never,
      (config) => {
        const client = new FakeClient(config);
        clients.push(client);
        return client;
      },
      "lease"
    );
    await manager.reconcile({
      revision: 1,
      connectors: [connector("connector-a", 1, "connected-only")],
    });
    await clients[0]?.handler?.({
      headers: { messageId: "message-1", topic: "robot" },
      data: JSON.stringify({ text: { content: "不得写入日志的正文" } }),
    });

    const state = manager.states()[0];
    assert.equal(state?.error_code, "inbox_validation_failed");
    assert.equal(
      state?.error_summary,
      "Control API rejected DingTalk inbox status=400"
    );
    assert.equal(state?.status, "CONNECTED");
    assert.equal(state?.registered, false);
    assert.equal(warnings.length, 1);
    assert.match(warnings[0] ?? "", /dingtalk_inbox_rejected/);
    assert.doesNotMatch(warnings[0] ?? "", /不得写入日志的正文/);
  } finally {
    console.warn = originalWarn;
  }
});
