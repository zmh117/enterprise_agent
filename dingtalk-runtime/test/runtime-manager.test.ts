import assert from "node:assert/strict";
import test from "node:test";
import type {
  DesiredConnector,
  StreamClient,
  StreamEnvelope,
} from "../src/contracts.js";
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
