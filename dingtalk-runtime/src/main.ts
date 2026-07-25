import { createServer } from "node:http";
import { ControlApi } from "./control-api.js";
import { acquireLeaseWithRetry } from "./lease-acquisition.js";
import { RuntimeManager } from "./runtime-manager.js";
import { DingTalkSdkClient } from "./sdk-client.js";

const runtimeId = process.env.RUNTIME_ID ?? "dingtalk-runtime-1";
const intervalMs = Number(process.env.RECONCILE_INTERVAL_MS ?? "3000");
const leaseAcquireTimeoutMs = Number(
  process.env.LEASE_ACQUIRE_TIMEOUT_MS ?? "30000"
);
const leaseAcquireRetryMs = Number(
  process.env.LEASE_ACQUIRE_RETRY_MS ?? "1000"
);
const controlOptions: ConstructorParameters<typeof ControlApi>[0] = {
  baseUrl:
    process.env.CONTROL_API_BASE_URL ??
    "http://agent-control-api:8000/api/internal/dingtalk-runtime",
  timeoutMs: Number(process.env.CONTROL_API_TIMEOUT_MS ?? "5000"),
};
if (process.env.DINGTALK_RUNTIME_AUTH_TOKEN) {
  controlOptions.token = process.env.DINGTALK_RUNTIME_AUTH_TOKEN;
}
if (process.env.DINGTALK_RUNTIME_AUTH_TOKEN_FILE) {
  controlOptions.tokenFile = process.env.DINGTALK_RUNTIME_AUTH_TOKEN_FILE;
}
const controlApi = new ControlApi(controlOptions);
let lease = await acquireLeaseWithRetry(controlApi, runtimeId, {
  timeoutMs: leaseAcquireTimeoutMs,
  retryMs: leaseAcquireRetryMs,
});
const manager = new RuntimeManager(
  runtimeId,
  controlApi,
  (connector) => new DingTalkSdkClient(connector),
  lease.lease_token
);
let shuttingDown = false;
let controlHealthy = true;

const tick = async (): Promise<void> => {
  try {
    const renewed = await controlApi.renew(runtimeId, lease.lease_token);
    lease = renewed.lease;
    manager.setLeaseToken(lease.lease_token);
    const snapshot = await controlApi.desired(runtimeId, lease.lease_token);
    await manager.reconcile(snapshot);
    await controlApi.report(runtimeId, lease.lease_token, manager.states());
    controlHealthy = true;
  } catch {
    // Preserve current healthy clients when the control plane is temporarily unavailable.
    controlHealthy = false;
  }
};

await tick();
const timer = setInterval(() => void tick(), Math.max(intervalMs, 1000));

const healthPort = Number(process.env.HEALTH_PORT ?? "8081");
const server = createServer((_request, response) => {
  const counts = manager.counts();
  response.statusCode = controlHealthy ? 200 : 503;
  response.setHeader("content-type", "application/json");
  response.end(
    JSON.stringify({
      status: controlHealthy ? "ok" : "degraded",
      lease: Boolean(lease.lease_token),
      ...counts,
    })
  );
});
server.listen(healthPort, "0.0.0.0");

const shutdown = async (): Promise<void> => {
  if (shuttingDown) return;
  shuttingDown = true;
  clearInterval(timer);
  server.close();
  await manager.shutdown();
  try {
    await controlApi.release(runtimeId, lease.lease_token);
  } finally {
    process.exit(0);
  }
};
process.on("SIGTERM", () => void shutdown());
process.on("SIGINT", () => void shutdown());
