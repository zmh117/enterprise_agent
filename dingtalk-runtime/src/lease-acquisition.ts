import type { RuntimeLease } from "./contracts.js";
import { ControlApiError } from "./control-api.js";

interface LeaseApi {
  acquire(runtimeId: string): Promise<{ lease: RuntimeLease }>;
}

export async function acquireLeaseWithRetry(
  api: LeaseApi,
  runtimeId: string,
  options: {
    timeoutMs: number;
    retryMs: number;
    sleep?: (milliseconds: number) => Promise<void>;
    now?: () => number;
  }
): Promise<RuntimeLease> {
  const now = options.now ?? Date.now;
  const sleep =
    options.sleep ??
    ((milliseconds: number) =>
      new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));
  const deadline = now() + Math.max(options.timeoutMs, 0);

  while (true) {
    try {
      return (await api.acquire(runtimeId)).lease;
    } catch (error) {
      if (!retryable(error) || now() >= deadline) throw error;
      await sleep(Math.max(options.retryMs, 100));
    }
  }
}

function retryable(error: unknown): boolean {
  if (!(error instanceof ControlApiError)) return true;
  return ![400, 401, 403, 422].includes(error.status);
}
