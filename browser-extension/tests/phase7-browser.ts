import { collectorWorker } from "./extension-worker";
import {
  chromium,
  type BrowserContext,
  type Page,
  type Worker,
} from "playwright";
import { mkdir, readFile, writeFile, cp, rm, mkdtemp } from "node:fs/promises";
import { resolve } from "node:path";
import assert from "node:assert/strict";
// @ts-expect-error standalone fixture
import { startFixtures } from "../fixtures/server.mjs";
import { createPackage, validatePackage } from "../extension/export/package";
import { DEFAULT_POLICY } from "../shared/policy";
import { uuid, type BundleData } from "../shared/contracts";
import { writeAcceptance, type AcceptanceCheck } from "./acceptance-report";
const output = resolve(
  process.env.MES_TEST_OUTPUT ?? "output/playwright/phase7",
);
await mkdir(output, { recursive: true });
const extension = resolve(output, "test-extension");
await cp(resolve("dist"), extension, { recursive: true });
const manifest = JSON.parse(
  await readFile(resolve(extension, "manifest.json"), "utf8"),
);
manifest.host_permissions = ["http://127.0.0.1/*", "http://localhost/*"];
await writeFile(resolve(extension, "manifest.json"), JSON.stringify(manifest));
const profile = await mkdtemp("/private/tmp/mes-evidence-phase7-");
const fixture = await startFixtures({
  logFile: resolve(output, "fixture-backend.ndjson"),
});
let fixtureClosed = false;
let context: BrowserContext;
let ui!: Page;
let worker: Worker;
let extensionId: string;
let rid: string;
const checks: AcceptanceCheck[] = [];
function check(
  tIds: string[],
  name: string,
  condition: unknown,
  detail?: unknown,
  method?: string,
) {
  checks.push({ tIds, name, passed: !!condition, detail, method });
  assert.ok(condition, `${name}: ${JSON.stringify(detail)}`);
  console.log(`PASS ${name}`);
}
async function until<T>(
  read: () => Promise<T>,
  pred: (v: T) => unknown,
  label: string,
  ms = 15000,
) {
  const start = Date.now();
  let last: T;
  do {
    last = await read();
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 100));
  } while (Date.now() - start < ms);
  throw new Error(`等待超时 ${label}: ${JSON.stringify(last!).slice(0, 4000)}`);
}
const rpc = (type: string, data: any = {}) =>
  ui.evaluate(
    async ({ type, data }) => {
      const r = await chrome.runtime.sendMessage({ type, ...data });
      if (!r?.ok) throw Error(r?.error);
      return r;
    },
    { type, data },
  );
const status = () => rpc("session.status");
async function page(url: string) {
  const p = await context.newPage();
  await p.goto(url);
  await p.evaluate("globalThis.__name=fn=>fn");
  return p;
}
async function tab(p: Page) {
  return (await ui.evaluate(
    async (url) => (await chrome.tabs.query({})).find((t) => t.url === url)?.id,
    p.url(),
  ))!;
}
async function reopen() {
  ui = await page(`chrome-extension://${extensionId}/control.html`);
  await ui.evaluate("globalThis.__name = fn => fn");
}
async function bundle(id = rid): Promise<BundleData> {
  return ui.evaluate(async (id) => {
    const db = await new Promise<IDBDatabase>((r, j) => {
      const q = indexedDB.open("mes-evidence-v1");
      q.onsuccess = () => r(q.result);
      q.onerror = () => j(q.error);
    });
    const get = (s: string, one = false) =>
      new Promise<any>((r, j) => {
        const q = one
          ? db.transaction(s).objectStore(s).get(id)
          : db.transaction(s).objectStore(s).index("recordingId").getAll(id);
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
const events = (b: BundleData) => b.chunks.flatMap((c) => c.events);
const business = (b: BundleData) =>
  events(b).filter((e) => e.channel !== "control");
async function start(pages: Page[], title: string) {
  rid = uuid();
  const dir = await rpc("scope.list");
  const policy = {
    ...structuredClone(DEFAULT_POLICY),
    pageOrigins: ["http://127.0.0.1:4317", "http://localhost:4318"],
    apiRules: [
      { origin: "http://127.0.0.1:4317", pathPrefix: "/api/" },
      { origin: "http://localhost:4318", pathPrefix: "/api/" },
    ],
    captureStreaming: true,
    businessRules: [
      {
        origin: "http://127.0.0.1:4317",
        pathPrefix: "/api/",
        codePath: "code",
        successValues: ["OK"],
      },
    ],
  };
  await rpc("session.start", {
    recordingId: rid,
    commandId: uuid(),
    browserRunId: dir.browserRunId,
    rootBrowserTabIds: await Promise.all(pages.map(tab)),
    title,
    environmentId: "LOCAL-FIXTURE",
    policy,
  });
  return until(
    status,
    (s) =>
      s.targets.every(
        (t: any) =>
          t.channels.page.state === "ACTIVE" &&
          t.channels.network.state === "ACTIVE",
      ),
    title,
  );
}
async function save(name: string) {
  await rpc("session.stop", { recordingId: rid, commandId: uuid() });
  await until(status, (s) => s.recording.state === "READY", "保存");
  const b = await bundle();
  const p = await createPackage(b);
  const validation = await validatePackage(p.zip);
  await writeFile(resolve(output, `${name}.zip`), p.zip);
  await writeFile(resolve(output, `${name}.json`), JSON.stringify(b));
  await writeFile(
    resolve(output, `${name}-validation.json`),
    JSON.stringify(validation, null, 2),
  );
  return b;
}
async function child(parent: Page, id: string, features = "") {
  await parent.bringToFront();
  const created = context.waitForEvent("page");
  await parent.evaluate(
    ({ id, features }) => window.open("/?id=" + id, "_blank", features),
    { id, features },
  );
  const p = await created;
  await p.waitForLoadState();
  const idNum = await tab(p);
  await until(
    status,
    (s) =>
      s.targets.some(
        (t: any) =>
          t.browserTabId === idNum && t.channels.page.state === "ACTIVE",
      ),
    "后代就绪",
  );
  return p;
}
try {
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    ...(process.env.MES_TEST_CHROME
      ? { executablePath: process.env.MES_TEST_CHROME }
      : {}),
    headless: process.env.HEADED !== "1",
    acceptDownloads: true,
    ignoreDefaultArgs: ["--disable-back-forward-cache"],
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  worker = await collectorWorker(context);
  extensionId = new URL(worker.url()).host;
  await reopen();
  // 范围：真实标签/窗口生命周期，API 创建的无关页明确不冒充 Ctrl+T。
  const a = await page("http://127.0.0.1:4317/?id=scope");
  const same = await page(a.url());
  const aId = await ui.evaluate(async () => {
    const t = await chrome.tabs.query({
      url: "http://127.0.0.1:4317/?id=scope",
    });
    return t.map((t) => t.id!);
  });
  // 同 URL 不能靠 URL helper 选择：显式激活并取真实活动 tab ID。
  await a.bringToFront();
  const selectedId = await ui.evaluate(
    async () =>
      (await chrome.tabs.query({ active: true, lastFocusedWindow: true }))[0]!
        .id!,
  );
  await same.goto("http://127.0.0.1:4317/?id=same-unselected");
  await start([a], "范围补充");
  await same.goto(a.url());
  const unrelatedPromise = context.waitForEvent("page");
  await same.bringToFront();
  await same.evaluate(() => window.open("/?id=unselected-child", "_blank"));
  const unrelatedChild = await unrelatedPromise;
  await unrelatedChild.waitForLoadState();
  const c = await child(a, "middle");
  const d = await child(c, "leaf");
  const cId = await tab(c),
    dId = await tab(d);
  const before = (await status()).targets.find(
    (t: any) => t.browserTabId === dId,
  );
  const popup = await child(a, "popup");
  const popupId = await tab(popup);
  const win = await ui.evaluate(
    async (tabId) =>
      chrome.windows.create({ tabId, type: "normal", focused: false }),
    popupId,
  );
  const popupWindow = win!.id!;
  const extra = await ui.evaluate(
    async (windowId) =>
      chrome.tabs.create({
        windowId,
        url: "http://127.0.0.1:4317/?id=unrelated-window-tab",
      }),
    popupWindow,
  );
  await c.close();
  await until(
    status,
    (s) =>
      s.targets.find((t: any) => t.browserTabId === cId)?.lifecycle ===
      "CLOSED",
    "中间节点关闭",
  );
  await d.click("#program");
  await ui.evaluate(
    async ({ id, windowId }) => chrome.tabs.move(id, { windowId, index: -1 }),
    { id: dId, windowId: popupWindow },
  );
  await d.evaluate(() => {
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "7.777";
  });
  let s = await until(
    status,
    (s) =>
      s.targets.find((t: any) => t.browserTabId === dId)?.windowId ===
      popupWindow,
    "移窗",
  );
  check(
    ["T06", "T08"],
    "中间节点关闭后叶子继续；移窗保持原实例和文档流",
    s.targets.find((t: any) => t.browserTabId === dId).accepting &&
      s.targets.find((t: any) => t.browserTabId === dId).captureGeneration ===
        before.captureGeneration &&
      s.targets.find((t: any) => t.browserTabId === dId).documents[0]
        .recorderStreamId === before.documents[0].recorderStreamId,
  );
  check(
    ["T01", "T04", "T09"],
    "同 URL 未选页的子页、新窗口内无关页均不在范围",
    !s.targets.some((t: any) =>
      [extra.id, aId.find((id) => id !== selectedId)].includes(t.browserTabId),
    ) &&
      !(await unrelatedChild.evaluate(
        () => !!(window as any).__mesEvidenceRecorder,
      )),
    s.targets.map((t: any) => t.browserTabId),
  );
  await new Promise((r) => setTimeout(r, 1100));
  await ui.evaluate(async (id) => chrome.windows.remove(id), popupWindow);
  await until(
    status,
    (s) =>
      s.targets
        .filter((t: any) => [popupId, dId].includes(t.browserTabId))
        .every((t: any) => t.lifecycle === "CLOSED"),
    "整窗关闭",
  );
  await a.click("#program");
  const scope = await save("scope");
  check(
    ["T07", "T08"],
    "整窗多个成员分别截止，根继续；移窗后语义引用可解析",
    scope.targets
      .filter((t) => [popupId, dId].includes(t.browserTabId))
      .every((t) => !!t.cutoffObservedAt) &&
      events(scope).some(
        (e) =>
          e.browserTabId === dId && JSON.stringify(e.payload).includes("7.777"),
      ),
  );
  check(
    ["T18"],
    "已关闭目标的业务观察均不晚于截止",
    scope.targets.every(
      (t) =>
        !t.cutoffObservedAt ||
        business(scope)
          .filter((e) => e.tabInstanceId === t.tabInstanceId)
          .every((e) => e.observedAt <= t.cutoffObservedAt!),
    ),
  );
  await Promise.all(
    context
      .pages()
      .filter((p) => p !== ui)
      .map((p) => p.close()),
  );
  // 窗口复选框冻结当时的根集合；API 新建明确不冒充原生快捷键。
  await ui.locator("#new").click();
  const selectedWindow = await ui.evaluate(() =>
    chrome.windows.create({
      url: [
        "http://127.0.0.1:4317/?id=WINDOW-A",
        "http://127.0.0.1:4317/?id=WINDOW-B",
      ],
      type: "normal",
      focused: false,
    }),
  );
  const windowA = (await until(
    async () => context.pages().find((p) => p.url().includes("id=WINDOW-A")),
    Boolean,
    "窗口根 A",
  )) as Page;
  const windowB = (await until(
    async () => context.pages().find((p) => p.url().includes("id=WINDOW-B")),
    Boolean,
    "窗口根 B",
  )) as Page;
  await Promise.all([windowA.waitForLoadState(), windowB.waitForLoadState()]);
  const windowRootIds = [await tab(windowA), await tab(windowB)];
  await ui.click("#refresh");
  await ui
    .locator(".window-group")
    .filter({ hasText: `窗口 ${selectedWindow!.id}` })
    .locator(".window-heading input")
    .check();
  await ui.locator("#policy-details summary").click();
  await ui.click("#fixture-policy");
  const afterSelection = await ui.evaluate(
    async (windowId) =>
      chrome.tabs.create({
        windowId,
        url: "http://127.0.0.1:4317/?id=AFTER-WINDOW-SELECTION",
      }),
    selectedWindow!.id!,
  );
  await ui.click("#start");
  let windowState = await until(
    status,
    (x) =>
      x.recording?.state === "RECORDING" &&
      x.targets.length === 2 &&
      x.targets.every((t: any) => t.channels.page.state === "ACTIVE"),
    "固定窗口根就绪",
  );
  rid = windowState.recording.recordingId;
  check(
    ["T02"],
    "窗口全选冻结当时两根，选择后 API 创建的新页未被追加",
    windowState.targets.every((t: any) =>
      windowRootIds.includes(t.browserTabId),
    ) &&
      !windowState.targets.some(
        (t: any) => t.browserTabId === afterSelection.id,
      ),
    { selectedIds: windowRootIds, excluded: afterSelection.id },
    "真实窗口复选框与 tabs.create；不计 Ctrl/Cmd+T",
  );
  await windowA.bringToFront();
  const namedEvent = context.waitForEvent("page");
  await windowA.click("#named");
  const named = await namedEvent;
  await named.waitForLoadState();
  const namedId = await tab(named);
  windowState = await until(
    status,
    (x) =>
      x.targets.some(
        (t: any) =>
          t.browserTabId === namedId && t.channels.page.state === "ACTIVE",
      ),
    "命名新目标就绪",
  );
  const namedInstance = windowState.targets.find(
    (t: any) => t.browserTabId === namedId,
  ).tabInstanceId;
  await windowA.bringToFront();
  await windowA.click("#named");
  await new Promise((r) => setTimeout(r, 500));
  windowState = await status();
  check(
    ["T15"],
    "选中根首次打开命名目标自动纳入，随后复用保持同一实例且不重复登记",
    windowState.targets.filter((t: any) => t.browserTabId === namedId)
      .length === 1 &&
      windowState.targets.find((t: any) => t.browserTabId === namedId)
        .tabInstanceId === namedInstance &&
      windowState.targets.find((t: any) => t.browserTabId === namedId)
        .parentTabInstanceId ===
        windowState.targets.find(
          (t: any) => t.browserTabId === windowRootIds[0],
        ).tabInstanceId,
  );
  const windowScope = await save("window-selection");
  check(
    ["T02", "T15"],
    "固定窗口与命名目标问题包无未选根，谱系与引用可独立校验",
    windowScope.targets.length === 3 &&
      !windowScope.targets.some((t) => t.browserTabId === afterSelection.id),
  );
  await Promise.all(
    context
      .pages()
      .filter((p) => p !== ui)
      .map((p) => p.close()),
  );
  // 并发、多跳、双侧正文以及真实在途关闭。
  const n = await page("http://127.0.0.1:4317/?id=network");
  await start([n], "并发与多跳正文");
  await n.evaluate(async () => {
    await Promise.all(
      ["alpha", "beta", "gamma"].map((id) =>
        fetch("/api/hops?id=" + id, { headers: { "x-case": id } }).then((r) =>
          r.json(),
        ),
      ),
    );
    await Promise.all(
      ["alpha", "beta"].map((id) =>
        fetch("/api/echo?id=" + id, {
          method: "POST",
          headers: { "content-type": "application/json", "x-case": id },
          body: JSON.stringify({ precision: id, quantity: "3.00" }),
        }).then((r) => r.json()),
      ),
    );
    await fetch("/api/empty");
    await fetch("/api/large").then((r) => r.text());
    await fetch("/api/echo?id=large-post", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ quantity: "x".repeat(1100 * 1024) }),
    }).then((r) => r.text());
    await fetch("/api/error").then((r) => r.text());
    await fetch("/api/network-fail").catch(() => {});
  });
  await n.click("#save");
  await n.locator("#result").filter({ hasText: "版本已变化" }).waitFor();
  await until(
    bundle,
    (b) =>
      b.network.filter((x) => x.request.url.includes("/api/hops")).length ===
        9 &&
      b.network
        .filter(
          (x) => x.request.url.includes("/api/hops") && x.redirectOrdinal === 2,
        )
        .every((x) => x.response.bodyCaptureStatus === "captured"),
    "逐跳持久化",
  );
  await n.click("#slow");
  await until(
    bundle,
    (b) =>
      b.network.some(
        (x) =>
          x.request.url.includes("/api/slow") &&
          x.networkOutcome === "incomplete",
      ),
    "在途已接受",
  );
  await n.close();
  await new Promise((r) => setTimeout(r, 2000));
  const network = await save("network");
  const hops = network.network.filter((x) =>
    x.request.url.includes("/api/hops"),
  );
  const blobs = new Map(network.blobs.map((b) => [b.path, b.data]));
  check(
    ["T30"],
    "三条并发链的每跳身份、双侧头、ExtraInfo 和最终正文精确匹配",
    hops.length === 9 &&
      ["alpha", "beta", "gamma"].every((id) => {
        const chain = hops
          .filter((x) => new URL(x.request.url).searchParams.get("id") === id)
          .sort((a, b) => a.redirectOrdinal - b.redirectOrdinal);
        return (
          chain.length === 3 &&
          new Set(chain.map((x) => x.cdpRequestId)).size === 1 &&
          new Set(chain.map((x) => x.requestKey)).size === 3 &&
          chain.every(
            (x, i) =>
              x.redirectOrdinal === i &&
              x.request.headers["x-case"] === id &&
              x.response.headers["x-case"] === id &&
              x.response.headers["x-hop"] === String(i) &&
              x.extraInfoStatus === "matched_by_protocol_order" &&
              (i < 2
                ? x.response.bodyRef === null &&
                  x.response.bodyCaptureReason === "redirect_body_not_available"
                : JSON.parse(String(blobs.get(x.response.bodyRef!))).marker ===
                  id),
          )
        );
      }),
    hops.map((x) => ({
      url: x.request.url,
      ordinal: x.redirectOrdinal,
      request: x.request.headers,
      response: x.response.headers,
      extra: x.extraInfoStatus,
    })),
  );
  check(
    ["T32"],
    "并发 POST 双侧正文按 requestKey 关联、精度保留",
    ["alpha", "beta"].every((id) => {
      const x = network.network.find(
        (x) =>
          x.request.url.endsWith("id=" + id) && x.request.url.includes("/echo"),
      );
      return (
        x &&
        JSON.parse(String(blobs.get(x.request.bodyRef!))).quantity === "3.00" &&
        JSON.parse(String(blobs.get(x.response.bodyRef!))).marker === id
      );
    }),
  );
  check(
    ["T31", "T32"],
    "HTTP/业务/网络结果分离，空/超限/大 POST 读取失败均明确",
    network.network.some(
      (x) =>
        x.businessCode === "VERSION_CONFLICT" &&
        x.response.httpStatus === 200 &&
        x.businessOutcome === "failure",
    ) &&
      network.network.some(
        (x) => x.response.httpStatus === 500 && x.networkOutcome === "finished",
      ) &&
      network.network.some((x) => x.networkOutcome === "failed") &&
      network.network.some(
        (x) =>
          x.request.url.includes("/empty") &&
          x.request.bodyCaptureStatus === "empty" &&
          x.response.bodyCaptureStatus === "empty",
      ) &&
      network.network.some(
        (x) =>
          x.request.url.includes("large-post") &&
          ((x.request.bodyCaptureStatus === "unavailable" &&
            x.request.bodyCaptureReason === "getRequestPostData_failed") ||
            (x.request.bodyCaptureStatus === "excluded_by_policy" &&
              x.request.bodyCaptureReason ===
                "body_size_limit_no_partial_json")),
      ) &&
      network.network.some(
        (x) =>
          x.request.url.includes("/large") &&
          x.response.bodyCaptureStatus === "excluded_by_policy",
      ),
  );
  check(
    ["T17", "T18"],
    "确认已接受的在途请求关闭后不保存迟到正文",
    network.network.some(
      (x) =>
        x.request.url.includes("/slow") &&
        x.response.bodyCaptureStatus === "incomplete_target_closed",
    ) && !JSON.stringify(network).includes("SHOULD_NOT_APPEAR_AFTER_CUTOFF"),
  );
  // 单 frame 下 WS 双方向与 SSE，随后加入专属 iframe/worker 及两个消费者共享 worker。
  const stream = await page("http://127.0.0.1:4317/?id=stream");
  const unselected = await page("http://127.0.0.1:4317/?id=shared-unselected");
  await start([stream], "流与子目标截止");
  await stream.click("#stream");
  await stream.waitForFunction(
    () => (window as any).demoSocket?.readyState === 1,
  );
  await stream.evaluate(() =>
    (window as any).demoSocket.send(
      JSON.stringify({ code: "OK", quantity: "WS_SENT_BEFORE" }),
    ),
  );
  await until(
    bundle,
    (b) =>
      events(b).some(
        (e) =>
          e.kind === "network.stream_message" && e.payload.direction === "sent",
      ),
    "WS发送已采集",
  );
  await stream.click("#frames");
  await until(
    status,
    (s) =>
      s.targets[0].documents.filter(
        (d: any) => d.chromeFrameId !== 0 && d.baselineRef,
      ).length >= 2,
    "frame 基线",
  );
  await new Promise((r) => setTimeout(r, 500));
  await stream
    .frameLocator('iframe[title="同源"]')
    .locator("#frame-program")
    .click();
  await stream
    .frameLocator('iframe[title="跨源"]')
    .locator("#frame-program")
    .click();
  await stream.evaluate(() => {
    (window as any).markedWorker = new Worker("/marked-worker.js");
  });
  await new Promise((r) => setTimeout(r, 400));
  await stream.evaluate(() =>
    (window as any).markedWorker.postMessage("BEFORE"),
  );
  for (const [p, id] of [
    [stream, "SELECTED"],
    [unselected, "UNSELECTED"],
  ] as const)
    await p.evaluate((id) => {
      const w = new SharedWorker("/shared-worker.js");
      (window as any).shared = w;
      (window as any).sharedReplies = [];
      w.port.onmessage = (e) => (window as any).sharedReplies.push(e.data);
      w.port.start();
      w.port.postMessage(id);
    }, id);
  await until(
    async () => unselected.evaluate(() => (window as any).sharedReplies),
    (x) => x.length > 0,
    "共享 worker 两个消费者",
  );
  await until(
    bundle,
    (b) =>
      b.network.some(
        (x) =>
          x.request.url.includes("DEDICATED_BEFORE") &&
          x.response.bodyCaptureStatus === "captured",
      ) &&
      b.network.filter(
        (x) =>
          x.request.url.includes("/api/token") &&
          x.chromeFrameId !== null &&
          x.chromeFrameId !== 0,
      ).length >= 2,
    "子目标业务已采集",
  );
  // 多 frame 新建 WS 无可靠 frame 来源，必须被排除。
  await stream.evaluate(() => {
    (window as any).ambiguous = new WebSocket(
      "ws://" + location.host + "/api/socket",
    );
  });
  await until(
    bundle,
    (b) => b.recording.gaps.some((g) => g.code === "websocket_frame_ambiguous"),
    "多 frame WS 排除落盘",
  );
  const pre = await bundle();
  const messages = events(pre).filter(
    (e) => e.kind === "network.stream_message",
  );
  check(
    ["T33"],
    "WS 收发与 SSE 接收分别有可引用的实际消息",
    messages.some(
      (e) =>
        e.payload.direction === "sent" &&
        JSON.stringify(e.payload).includes("WS_SENT_BEFORE"),
    ) &&
      messages.some(
        (e) =>
          e.payload.direction === "received" &&
          e.payload.eventName !== undefined,
      ) &&
      messages.some(
        (e) =>
          e.payload.direction === "received" &&
          e.payload.eventName === undefined,
      ),
    messages.map((e) => e.payload),
  );
  check(
    ["T34"],
    "共享 worker 真实完成两消费者请求，但内部流量不入包",
    !JSON.stringify(pre).includes("SHARED_INTERNAL_") &&
      (await unselected.evaluate(
        () => (window as any).sharedReplies[0].clients,
      )) === 2,
  );
  check(
    ["T33", "T44"],
    "专属 worker/iframe 已采集；多 frame WebSocket 排除原因可见",
    pre.network.some((x) => x.request.url.includes("DEDICATED_BEFORE")) &&
      pre.recording.gaps.some((g) =>
        /websocket.*(frame|scope)|socket.*(frame|scope)/i.test(
          g.code + " " + g.detail,
        ),
      ),
    pre.recording.gaps,
  );
  await worker.evaluate("globalThis.__name=fn=>fn");
  await worker.evaluate(() => {
    const original = chrome.debugger.sendCommand.bind(chrome.debugger);
    (globalThis as any).__releaseBodies = [];
    (globalThis as any).__bodyCalls = 0;
    chrome.debugger.sendCommand = (async (...args: any[]) => {
      const value = await (original as any)(...args);
      if (args[1] === "Network.getResponseBody") {
        (globalThis as any).__bodyCalls++;
        await new Promise<void>((resolve) =>
          (globalThis as any).__releaseBodies.push(resolve),
        );
      }
      return value;
    }) as any;
  });
  await stream.evaluate(async () => {
    await Promise.all(
      Array.from({ length: 6 }, (_, i) =>
        fetch("/api/echo?id=QUEUED_" + i).then((r) => r.text()),
      ),
    );
  });
  const queued = await until(
    status,
    (s) =>
      s.resources.bodyQueues.some(
        (q: any) => q.running === 2 && q.waiting >= 4,
      ),
    "真实正文在途与排队",
  );
  const callsBeforeStop = await worker.evaluate(
    () => (globalThis as any).__bodyCalls,
  );
  const streamData = await save("stream");
  await worker.evaluate(() =>
    (globalThis as any).__releaseBodies
      .splice(0)
      .forEach((r: () => void) => r()),
  );
  await new Promise((r) => setTimeout(r, 1200));
  check(
    ["T18", "T20", "T44"],
    "STOP 取消真实排队读取，迟到正文丢弃计数增加",
    (await worker.evaluate(() => (globalThis as any).__bodyCalls)) ===
      callsBeforeStop && (await status()).targets[0].lateResults >= 2,
    {
      queueBefore: queued.resources.bodyQueues,
      after: (await status()).resources,
      lateResults: (await status()).targets[0].lateResults,
    },
  );
  await stream.evaluate(() => {
    (window as any).demoSocket.send(
      JSON.stringify({ quantity: "WS_SENT_AFTER" }),
    );
    (window as any).markedWorker.postMessage("AFTER");
    (window as any).shared.port.postMessage("AFTER");
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "AFTER_STOP";
  });
  await stream
    .frameLocator('iframe[title="同源"]')
    .locator("#frame-program")
    .click();
  await new Promise((r) => setTimeout(r, 1500));
  const streamAfter = await bundle();
  check(
    ["T20", "T44"],
    "停止后存活 WS/SSE、worker 与 iframe 均不能追加业务",
    business(streamAfter).length === business(streamData).length &&
      !JSON.stringify(streamAfter).includes("WS_SENT_AFTER") &&
      !streamAfter.network.some((x) =>
        x.request.url.includes("DEDICATED_AFTER"),
      ),
  );
  const ownDetached = await ui.evaluate(async (tabId) => {
    try {
      await chrome.debugger.sendCommand({ tabId }, "Page.getFrameTree");
      return false;
    } catch (e) {
      return String(e).includes("not attached");
    }
  }, streamData.targets[0]!.browserTabId);
  const connections = await stream.evaluate(() => ({
    ws: (window as any).demoSocket.readyState,
    sse: (window as any).demoEventSource.readyState,
  }));
  check(
    ["T20"],
    "停止释放本扩展调试连接，业务 WS/SSE 继续存活",
    ownDetached && connections.ws === 1 && connections.sse === 1,
    { ownDetached, connections },
  );
  await Promise.all(
    context
      .pages()
      .filter((p) => p !== ui)
      .map((p) => p.close()),
  );
  // 时钟仅在该测试页改写，不改主机或扩展时钟。
  const clockPage = await page("http://127.0.0.1:4317/?id=clock");
  await start([clockPage], "源时钟偏移与倒退");
  await clockPage.evaluate(() => {
    (window as any).__realNow = performance.now.bind(performance);
    (window as any).__offset = 86_400_000;
    Object.defineProperty(performance, "now", {
      value: () => (window as any).__realNow() + (window as any).__offset,
      configurable: true,
    });
    const real = Date.now.bind(Date);
    Date.now = () => real() + (window as any).__offset;
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "CLOCK_FORWARD";
  });
  await new Promise((r) => setTimeout(r, 200));
  await clockPage.evaluate(() => {
    (window as any).__offset = -86_400_000;
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "CLOCK_BACKWARD";
  });
  await new Promise((r) => setTimeout(r, 1100));
  const clockData = await save("clock");
  const clockEvents = events(clockData).filter(
    (e) =>
      e.kind === "ui.action" &&
      e.payload.action === "programmatic_change" &&
      String(e.payload.after?.value?.value).startsWith("CLOCK_"),
  );
  check(
    ["T46"],
    "页面时钟正负一天跳变保留原始 sourceTime，观察时间/序号独立且不伪造 UTC",
    clockEvents.length === 2 &&
      clockEvents[0]!.sourceTime! > clockEvents[1]!.sourceTime! &&
      clockEvents[0]!.sourceSeq < clockEvents[1]!.sourceSeq &&
      clockEvents.every(
        (e) =>
          e.sourceClock === "document_performance_ms" &&
          e.normalizedAt === null,
      ) &&
      clockEvents[0]!.observedAt <= clockEvents[1]!.observedAt &&
      clockData.recording.policy.logTimeMarginSeconds === 120,
    clockEvents.map((e) => ({
      eventId: e.eventId,
      sourceTime: e.sourceTime,
      sourceClock: e.sourceClock,
      observedAt: e.observedAt,
      seq: e.sourceSeq,
      normalizedAt: e.normalizedAt,
    })),
  );
  await clockPage.evaluate(() => {
    (window as any).__offset = -172_800_000;
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "CLOCK_AFTER_STOP";
  });
  await new Promise((r) => setTimeout(r, 500));
  check(
    ["T46"],
    "源时间倒退不能越过 STOP gate",
    business(await bundle()).length === business(clockData).length,
  );
  // 保存后关闭 fixture，并同时阻断该 profile 的所有网络；已保存证据仍能封包。
  await fixture.close();
  fixtureClosed = true;
  await context.setOffline(true);
  await context.route(/^https?:/, (route) =>
    route.abort("internetdisconnected"),
  );
  await ui.close();
  await reopen();
  check(
    ["T41"],
    "fixture 已关闭且浏览器网络被阻断",
    await ui.evaluate(async () => {
      try {
        await fetch("http://127.0.0.1:4317/api/empty");
        return false;
      } catch {
        return true;
      }
    }),
  );
  await ui.locator('nav a[href="#records"]').click();
  const row = () => ui.locator(`.history-row[data-recording-id="${rid}"]`);
  const exportStates = () =>
    ui.evaluate(async (id) => {
      const db = await new Promise<IDBDatabase>((r) => {
        const q = indexedDB.open("mes-evidence-v1");
        q.onsuccess = () => r(q.result);
      });
      const result = await new Promise<any[]>((r) => {
        const q = db
          .transaction("exports")
          .objectStore("exports")
          .index("recordingId")
          .getAll(id);
        q.onsuccess = () => r(q.result);
      });
      db.close();
      return result;
    }, rid);
  const downloadZip = async (name: string) => {
    const pending = ui.waitForEvent("download");
    await row().getByRole("button", { name: "导出", exact: true }).click();
    const d = await pending;
    const path = resolve(output, name);
    await d.saveAs(path);
    const result = await validatePackage(new Uint8Array(await readFile(path)));
    assert.equal(result.recordingId, rid);
    return result;
  };
  await downloadZip("offline.zip");
  await until(
    exportStates,
    (a) => a.some((x) => x.state === "complete"),
    "下载完成状态",
  );
  check(["T41"], "真正离线重开控制页后实际下载 ZIP 且独立校验", true);
  // 使用浏览器真实 downloads.cancel API 取消一次新下载，不替换 downloads.download。
  await ui.evaluate(() => {
    (window as any).__cancelDownload = (
      item: chrome.downloads.DownloadItem,
    ) => {
      void chrome.downloads.cancel(item.id).catch((e) => {
        (window as any).__cancelError = String(e);
      });
    };
    chrome.downloads.onCreated.addListener((window as any).__cancelDownload);
  });
  const canceledEvent = ui.waitForEvent("download");
  await row().getByRole("button", { name: "导出", exact: true }).click();
  const canceled = await canceledEvent;
  const canceledReason = await canceled.failure();
  await until(
    exportStates,
    (a) => a.some((x) => x.state === "download_interrupted"),
    "真实下载取消",
  );
  await ui.evaluate(() =>
    chrome.downloads.onCreated.removeListener((window as any).__cancelDownload),
  );
  check(
    ["T41"],
    "真实取消下载后状态为未完成且证据仍在",
    !!canceledReason &&
      business(await bundle()).length === business(clockData).length,
    { canceledReason },
  );
  await downloadZip("offline-after-cancel.zip");
  // 本地摘要/散列失败注入不修改唯一数据。
  await ui.evaluate(() => {
    (window as any).__digest = crypto.subtle.digest.bind(crypto.subtle);
    crypto.subtle.digest = async () => {
      throw Error("FIXTURE_EXPORT_FAILURE");
    };
  });
  await row().getByRole("button", { name: "导出", exact: true }).click();
  await until(
    exportStates,
    (a) => a.some((x) => x.state === "failed"),
    "失败状态",
  );
  check(
    ["T41"],
    "生成失败状态可见，本地原始证据保留",
    (await ui
      .locator("#delivery-status")
      .textContent()
      .then((t) => t?.includes("导出失败"))) &&
      business(await bundle()).length === business(clockData).length,
  );
  await ui.evaluate(() => {
    crypto.subtle.digest = (window as any).__digest;
  });
  await downloadZip("offline-retried.zip");
  // 让真实生成在异步 digest 等待期间保持进行中，关闭拥有该任务的控制页。
  await ui.evaluate(() => {
    crypto.subtle.digest = () => new Promise(() => {});
  });
  await row().getByRole("button", { name: "导出", exact: true }).click();
  await until(
    exportStates,
    (a) =>
      a.sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0]?.state ===
      "generating",
    "生成进行中",
  );
  await ui.close();
  await reopen();
  await until(
    () => row().textContent(),
    (t) => t?.includes("上次生成未确认完成"),
    "重开提示",
  );
  check(
    ["T50"],
    "生成中关闭控制页后显示未确认完成，保留唯一数据可重试",
    business(await bundle()).length === business(clockData).length,
  );
  await downloadZip("offline-reopened.zip");
  await writeFile(
    resolve(output, "export-attempts.json"),
    JSON.stringify(await exportStates(), null, 2),
  );
  await writeAcceptance(
    output,
    extension,
    context.browser()!.version(),
    checks,
    { artifacts: ["scope.zip", "network.zip", "stream.zip", "clock.zip"] },
  );
  console.log(`第 7 组专项完成 ${checks.length} 项`);
} catch (e) {
  await writeFile(
    resolve(output, "failure-bundle.json"),
    JSON.stringify(await bundle().catch(() => null)),
  );
  await writeFile(
    resolve(output, "failure.json"),
    JSON.stringify({ error: String(e), checks }, null, 2),
  );
  console.error(e);
  process.exitCode = 1;
} finally {
  await context!?.close();
  if (!fixtureClosed) await fixture.close();
  await rm(profile, { recursive: true, force: true });
}
