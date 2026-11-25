import { chromium, type BrowserContext, type Page } from "playwright";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import assert from "node:assert/strict";
// @ts-expect-error standalone fixture
import { startFixtures } from "../fixtures/server.mjs";
import { collectorWorker } from "./extension-worker";
import { writeAcceptance, type AcceptanceCheck } from "./acceptance-report";
import { createPackage, validatePackage } from "../extension/export/package";
import { DEFAULT_POLICY } from "../shared/policy";
import { uuid, type BundleData, type Target } from "../shared/contracts";

const output = resolve(
  process.env.MES_TEST_OUTPUT ?? `output/playwright/opening-${Date.now()}`,
);
await mkdir(output, { recursive: true });
const extension = resolve(output, "test-extension");
await cp(resolve("dist"), extension, { recursive: true });
const manifest = JSON.parse(
  await readFile(resolve(extension, "manifest.json"), "utf8"),
);
manifest.host_permissions = ["http://127.0.0.1/*"];
await writeFile(resolve(extension, "manifest.json"), JSON.stringify(manifest));
const profile = await mkdtemp("/private/tmp/mes-evidence-opening-");
const fixture = await startFixtures({
  port: 4497,
  crossPort: 4498,
  logFile: resolve(output, "fixture-backend.ndjson"),
});
const origin = "http://127.0.0.1:4497";
let context: BrowserContext | undefined;
let ui: Page;
let browserVersion = "";
const checks: AcceptanceCheck[] = [];
const attempts: {
  mode: string;
  trial: number;
  marker: string;
  method: string;
  parentId: number;
  tabId: number;
  target: Target;
}[] = [];
const modes = [
  "blank",
  "noopener",
  "noreferrer",
  "window-open",
  "new-window",
  "middle",
  "modifier",
  "fast-parent-close",
] as const;
const rpc = (type: string, data: any = {}) =>
  ui.evaluate(
    async ({ type, data }) => {
      const result = await chrome.runtime.sendMessage({ type, ...data });
      if (!result?.ok) throw Error(result?.error);
      return result;
    },
    { type, data },
  );
const status = () => rpc("session.status");
async function until<T>(
  read: () => Promise<T>,
  pred: (v: T) => unknown,
  label: string,
) {
  const started = Date.now();
  let last: T;
  do {
    last = await read();
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 100));
  } while (Date.now() - started < 15_000);
  throw Error(`${label}: ${JSON.stringify(last!).slice(0, 6000)}`);
}
function check(
  tIds: string[],
  name: string,
  passed: unknown,
  detail?: unknown,
) {
  checks.push({ tIds, name, passed: !!passed, detail });
  assert.ok(passed, `${name}: ${JSON.stringify(detail)}`);
  console.log("PASS " + name);
}
const tabId = (page: Page) =>
  ui.evaluate(
    async (url) =>
      (await chrome.tabs.query({})).find((t) => t.url === url)!.id!,
    page.url(),
  );
async function ready(id: number) {
  const s = await until(
    status,
    (s) =>
      s.targets.some(
        (t: Target) =>
          t.browserTabId === id &&
          t.channels.page.state === "ACTIVE" &&
          t.channels.network.state === "ACTIVE",
      ),
    `目标 ${id} 就绪`,
  );
  return s.targets.find((t: Target) => t.browserTabId === id) as Target;
}
async function readBundle(id: string): Promise<BundleData> {
  return ui.evaluate(async (id) => {
    const db = await new Promise<IDBDatabase>((r, j) => {
      const q = indexedDB.open("mes-evidence-v1");
      q.onsuccess = () => r(q.result);
      q.onerror = () => j(q.error);
    });
    const get = (name: string, one = false) =>
      new Promise<any>((r, j) => {
        const store = db.transaction(name).objectStore(name);
        const q = one ? store.get(id) : store.index("recordingId").getAll(id);
        q.onsuccess = () => r(q.result);
        q.onerror = () => j(q.error);
      });
    const [recording, targets, chunks, blobs, network] = await Promise.all([
      get("recordings", true),
      get("targets"),
      get("chunks"),
      get("blobs"),
      get("network"),
    ]);
    db.close();
    chunks.sort((a: any, b: any) => a.chunkSeq - b.chunkSeq);
    return { recording, targets, chunks, blobs, network };
  }, id);
}
try {
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    ...(process.env.MES_TEST_CHROME
      ? { executablePath: process.env.MES_TEST_CHROME }
      : {}),
    headless: process.env.HEADED !== "1",
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  browserVersion = context.browser()!.version();
  const worker = await collectorWorker(context);
  await worker.evaluate(() => {
    (globalThis as any).__openingEvents = [];
    chrome.tabs.onCreated.addListener((tab) =>
      (globalThis as any).__openingEvents.push({
        type: "tabs.onCreated",
        observedAt: new Date().toISOString(),
        tab,
      }),
    );
    chrome.webNavigation.onCreatedNavigationTarget.addListener((event) =>
      (globalThis as any).__openingEvents.push({
        type: "webNavigation.onCreatedNavigationTarget",
        observedAt: new Date().toISOString(),
        event,
      }),
    );
  });
  ui = await context.newPage();
  await ui.goto(
    `chrome-extension://${new URL(worker.url()).host}/control.html`,
  );
  await ui.evaluate("globalThis.__name=fn=>fn");
  const root = await context.newPage();
  await root.goto(origin + "/?id=OPENING-ROOT");
  const rootId = await tabId(root),
    recordingId = uuid();
  await rpc("session.start", {
    recordingId,
    commandId: uuid(),
    browserRunId: (await rpc("scope.list")).browserRunId,
    rootBrowserTabIds: [rootId],
    title: "逐方式首请求测量",
    policy: {
      ...structuredClone(DEFAULT_POLICY),
      pageOrigins: [origin],
      apiRules: [{ origin, pathPrefix: "/api/" }],
    },
  });
  await ready(rootId);
  for (const mode of modes) {
    for (let trial = 1; trial <= 3; trial++) {
      const marker = `${mode}-${trial}-${uuid()}`;
      let parent = root;
      if (mode === "fast-parent-close") {
        await root.bringToFront();
        const created = context.waitForEvent("page");
        await root.evaluate(
          (url) => window.open(url, "_blank"),
          origin + "/?id=PARENT-" + marker,
        );
        parent = await created;
        await parent.waitForLoadState();
        await ready(await tabId(parent));
      }
      const parentId = await tabId(parent);
      await parent.bringToFront();
      // 唯一 marker 标识每一次真实打开；不刷新子页、不重放首请求。
      await parent.evaluate(
        ({ mode, marker }) => {
          const anchor = document.querySelector<HTMLAnchorElement>("#child")!;
          anchor.href = "/?id=" + marker;
          anchor.target = ["middle", "modifier"].includes(mode)
            ? "_self"
            : "_blank";
          anchor.rel = mode === "noopener" || mode === "noreferrer" ? mode : "";
          document.querySelector<HTMLButtonElement>("#window-open")!.onclick =
            () => {
              window.open(
                "/?id=" + marker,
                "_blank",
                mode === "new-window" ? "width=760,height=680" : "",
              );
              if (mode === "fast-parent-close") window.close();
            };
        },
        { mode, marker },
      );
      const created = context.waitForEvent("page");
      if (["window-open", "new-window", "fast-parent-close"].includes(mode))
        await parent.click("#window-open");
      else
        await parent.click(
          "#child",
          mode === "middle"
            ? { button: "middle" }
            : mode === "modifier"
              ? {
                  modifiers: [
                    process.platform === "darwin" ? "Meta" : "Control",
                  ],
                }
              : {},
        );
      const child = await created;
      await child.waitForLoadState();
      const id = await tabId(child),
        target = await ready(id);
      if (mode === "fast-parent-close")
        await until(async () => parent.isClosed(), Boolean, "父页同步关闭");
      attempts.push({
        mode,
        trial,
        marker,
        method:
          mode === "middle"
            ? "真实链接中键点击"
            : mode === "modifier"
              ? `真实链接 ${process.platform === "darwin" ? "Cmd" : "Ctrl"} 点击`
              : mode === "fast-parent-close"
                ? "脚本可关闭父页中同一次按钮处理打开子页并同步 window.close"
                : "真实页面按钮/链接点击；不计原生右键菜单",
        parentId,
        tabId: id,
        target,
      });
      // 后续唯一请求用于区分“首请求漏采”与整条网络通道失效。
      await child.evaluate(
        (marker) => fetch("/api/echo?id=" + marker).then((r) => r.json()),
        marker,
      );
      await child.close();
    }
    check(
      mode === "fast-parent-close"
        ? ["T11"]
        : ["middle", "modifier"].includes(mode)
          ? ["T14"]
          : ["T13"],
      `${mode} 三次真实打开均确认来源并建立页面/网络通道`,
      attempts.filter((a) => a.mode === mode).length === 3,
    );
  }
  await rpc("session.stop", { recordingId, commandId: uuid() });
  await until(status, (s) => s.recording.state === "READY", "保存");
  const data = await readBundle(recordingId);
  const server = (
    await readFile(resolve(output, "fixture-backend.ndjson"), "utf8")
  )
    .trim()
    .split("\n")
    .map((row) => JSON.parse(row));
  const rows = attempts.map((a) => {
    const target = data.targets.find(
      (t) => t.tabInstanceId === a.target.tabInstanceId,
    )!;
    const parent = data.targets.find((t) => t.browserTabId === a.parentId)!;
    const first = data.network.filter(
      (n) =>
        n.tabInstanceId === target.tabInstanceId &&
        new URL(n.request.url).pathname === "/api/first" &&
        new URL(n.request.url).searchParams.get("id") === a.marker,
    );
    const later = data.network.filter(
      (n) =>
        n.tabInstanceId === target.tabInstanceId &&
        new URL(n.request.url).pathname === "/api/echo" &&
        new URL(n.request.url).searchParams.get("id") === a.marker,
    );
    return {
      ...a,
      target: undefined,
      tabInstanceId: target.tabInstanceId,
      parentTabInstanceId: target.parentTabInstanceId,
      expectedParentTabInstanceId: parent.tabInstanceId,
      lineageEvidence: target.lineageEvidence,
      createdObservedAt: target.createdObservedAt,
      lineageConfirmedAt: target.lineageConfirmedAt,
      networkReadyAt: target.networkReadyAt,
      firstBaselineAt: target.firstBaselineAt,
      cutoffObservedAt: target.cutoffObservedAt,
      serverFirstRequests: server.filter(
        (row) => row.path === "/api/first" && row.marker === a.marker,
      ),
      capturedFirstRequests: first.map((n) => ({
        requestKey: n.requestKey,
        sourceTime: n.sourceTime,
        sourceClock: n.sourceClock,
        startedAt: n.startedAt,
        requestId: n.serverCorrelation.requestId,
      })),
      laterRequestKeys: later.map((n) => n.requestKey),
    };
  });
  const perMode = modes.map((mode) => {
    const items = rows.filter((r) => r.mode === mode);
    const captured = items.filter(
      (r) => r.capturedFirstRequests.length === 1,
    ).length;
    return {
      mode,
      trials: items.length,
      captured,
      ratio: captured / items.length,
    };
  });
  await writeFile(
    resolve(output, "first-request-timings.json"),
    JSON.stringify(
      {
        method:
          "每方式三次，唯一 marker 对应一次服务端到达；保留原始时钟，不直接相减 CDP 与 ISO 时钟；不承诺首请求零丢失",
        pending: ["原生右键菜单新标签", "原生右键菜单新窗口"],
        perMode,
        attempts: rows,
        browserSourceEvents: await worker.evaluate(
          () => (globalThis as any).__openingEvents,
        ),
      },
      null,
      2,
    ),
  );
  check(
    ["T16"],
    "24 次首请求各有唯一服务端到达，捕获比例可逐方式复核",
    rows.length === 24 &&
      rows.every(
        (r) =>
          r.serverFirstRequests.length === 1 &&
          r.capturedFirstRequests.length <= 1,
      ),
    perMode,
  );
  check(
    ["T11", "T13", "T14"],
    "每次后代归属实际父实例、仅登记一次且保留真实来源",
    rows.every(
      (r) =>
        r.parentTabInstanceId === r.expectedParentTabInstanceId &&
        r.lineageEvidence.length > 0 &&
        data.targets.filter((t) => t.browserTabId === r.tabId).length === 1,
    ),
  );
  check(
    ["T16"],
    "首请求测量后各目标仍可采集正常请求",
    rows.every((r) => r.laterRequestKeys.length === 1),
  );
  const result = await createPackage(data),
    validation = await validatePackage(result.zip);
  await writeFile(resolve(output, "opening.zip"), result.zip);
  await writeFile(
    resolve(output, "opening-validation.json"),
    JSON.stringify(validation, null, 2),
  );
  check(
    ["T48"],
    "逐方式问题包通过结构、hash、身份和引用校验",
    validation.valid,
    validation,
  );
} catch (error) {
  await writeFile(
    resolve(output, "failure.json"),
    JSON.stringify(
      {
        error: String(error),
        status: await status().catch(() => null),
        attempts,
      },
      null,
      2,
    ),
  );
  throw error;
} finally {
  await writeAcceptance(output, extension, browserVersion, checks);
  await context?.close();
  await fixture.close();
  await rm(profile, { recursive: true, force: true });
}
