import assert from "node:assert/strict";
import test from "node:test";

import { ControlApiError } from "../src/control-api.js";
import { acquireLeaseWithRetry } from "../src/lease-acquisition.js";

test("lease acquisition waits through a stale handover window", async () => {
  let attempts = 0;
  let currentTime = 0;
  const lease = await acquireLeaseWithRetry(
    {
      acquire: async () => {
        attempts += 1;
        if (attempts < 3) throw new ControlApiError(409);
        return {
          lease: {
            lease_name: "dingtalk-stream-runtime-singleton",
            runtime_id: "runtime-one",
            lease_token: "lease-token",
            expires_at: "2026-07-25T00:00:00Z",
          },
        };
      },
    },
    "runtime-one",
    {
      timeoutMs: 5_000,
      retryMs: 1_000,
      now: () => currentTime,
      sleep: async (milliseconds) => {
        currentTime += milliseconds;
      },
    }
  );
  assert.equal(attempts, 3);
  assert.equal(lease.lease_token, "lease-token");
});

test("lease acquisition does not retry invalid service credentials", async () => {
  let attempts = 0;
  await assert.rejects(
    acquireLeaseWithRetry(
      {
        acquire: async () => {
          attempts += 1;
          throw new ControlApiError(401);
        },
      },
      "runtime-one",
      { timeoutMs: 5_000, retryMs: 1_000 }
    ),
    (error: unknown) =>
      error instanceof ControlApiError && error.status === 401
  );
  assert.equal(attempts, 1);
});
