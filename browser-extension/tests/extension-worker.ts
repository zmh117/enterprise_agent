import type { BrowserContext, Worker } from "playwright";

/** A fresh profile can still contain built-in extension workers (e.g. Chrome 125).
 * Select the collector by its manifest, never by serviceWorkers() array order. */
export async function collectorWorker(
  context: BrowserContext,
  timeout = 30_000,
): Promise<Worker> {
  const deadline = Date.now() + timeout;
  const seen = new Map<string, string>();
  while (Date.now() < deadline) {
    for (const worker of context.serviceWorkers()) {
      if (!worker.url().startsWith("chrome-extension://")) continue;
      try {
        const manifest = await worker.evaluate(() =>
          chrome.runtime.getManifest(),
        );
        seen.set(worker.url(), manifest.name);
        if (
          manifest.name === "浏览器采集助手" &&
          manifest.background &&
          "service_worker" in manifest.background &&
          manifest.background.service_worker === "background.js"
        )
          return worker;
      } catch {
        /* A retiring worker does not identify the next active worker. */
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(
    `未找到采集器后台 worker；已观察：${JSON.stringify([...seen])}`,
  );
}
