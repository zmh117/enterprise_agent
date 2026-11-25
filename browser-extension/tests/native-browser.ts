import { collectorWorker } from "./extension-worker";
import {
  chromium,
  type Page,
  type BrowserContext,
  type Worker,
} from "playwright";
import {
  readFile,
  writeFile,
  mkdir,
  cp,
  mkdtemp,
  rm,
  appendFile,
} from "node:fs/promises";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
// @ts-expect-error standalone fixture
import { startFixtures } from "../fixtures/server.mjs";
import { DEFAULT_POLICY } from "../shared/policy";
import { uuid } from "../shared/contracts";
import { writeAcceptance, type AcceptanceCheck } from "./acceptance-report";
import { createPackage, validatePackage } from "../extension/export/package";
import type { BundleData } from "../shared/contracts";
const output = resolve(
  process.env.MES_TEST_OUTPUT ?? `output/playwright/native-${Date.now()}`,
);
await mkdir(output, { recursive: true });
// 不消费以前运行遗留的人工确认。
await writeFile(resolve(output, ".native-run"), new Date().toISOString(), {
  flag: "wx",
});
const extension = resolve(output, "test-extension");
await cp(resolve("dist"), extension, { recursive: true });
const profile = await mkdtemp("/private/tmp/mes-evidence-native-");
const fixture = await startFixtures({
  port: 4477,
  crossPort: 4478,
  logFile: resolve(output, "fixture-backend.ndjson"),
});
let context: BrowserContext | undefined;
let worker: Worker;
let extId: string;
let ui: Page;
let root: Page;
let denied: Page;
const checks: AcceptanceCheck[] = [];
const platform: any[] = [];
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
const tab = (url: string) =>
  ui.evaluate(
    async (url) => (await chrome.tabs.query({})).find((t) => t.url === url)?.id,
    url,
  );
async function until(
  read: () => Promise<any>,
  pred: (s: any) => boolean,
  label: string,
  ms = 180000,
) {
  const at = Date.now();
  let s;
  while (Date.now() - at < ms) {
    s = await read();
    if (pred(s)) return s;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error(`等待 ${label} 超时 ${JSON.stringify(s).slice(0, 2000)}`);
}
async function checkpoint(name: string, instruction: string) {
  const startedAt = new Date().toISOString();
  await writeFile(
    resolve(output, "stage.json"),
    JSON.stringify(
      {
        name,
        at: startedAt,
        instruction,
        confirmation: `在本次输出目录写入 continue-${name}.json：{"action":"实际完成的操作","evidence":"界面截图路径或详细人工观察"}`,
        status: await status().catch(() => null),
      },
      null,
      2,
    ),
  );
  console.log(`NATIVE_STAGE ${name}\n${instruction}\n输出：${output}`);
  const confirmation = await until(
    () =>
      readFile(resolve(output, `continue-${name}.json`), "utf8")
        .then(JSON.parse)
        .catch(() => null),
    (c) =>
      typeof c?.action === "string" &&
      c.action.trim().length > 0 &&
      typeof c?.evidence === "string" &&
      c.evidence.trim().length > 0,
    name,
    Number(process.env.MES_NATIVE_STAGE_TIMEOUT_MS ?? 600000),
  );
  await ui.screenshot({
    path: resolve(output, `control-after-${name}.png`),
    fullPage: true,
  });
  await appendFile(
    resolve(output, "native-actions.ndjson"),
    JSON.stringify({
      name,
      instruction,
      startedAt,
      confirmedAt: new Date().toISOString(),
      confirmation,
      permissions: await ui.evaluate(() => chrome.permissions.getAll()),
      status: await status(),
    }) + "\n",
  );
}
function check(tIds: string[], name: string, c: unknown, detail?: unknown) {
  checks.push({
    tIds,
    name,
    passed: !!c,
    detail,
    method:
      "未经修改的生产 manifest；独立 headed profile，原生界面操作与读取断言分开",
  });
  assert.ok(c, name);
  console.log("PASS " + name);
}
async function configure(ids: number[], origins: string[]) {
  await ui.bringToFront();
  await ui.click("#refresh");
  for (const selected of await ui.locator("input[data-tab-id]:checked").all())
    await selected.uncheck();
  for (const id of ids) await ui.locator(`input[data-tab-id="${id}"]`).check();
  if (
    !(await ui
      .locator("#policy-details")
      .evaluate((e) => (e as HTMLDetailsElement).open))
  )
    await ui.locator("#policy-details summary").click();
  await ui.fill(
    "#policy",
    JSON.stringify({
      ...structuredClone(DEFAULT_POLICY),
      pageOrigins: origins,
      apiRules: origins.map((origin) => ({ origin, pathPrefix: "/api/" })),
    }),
  );
}
async function bundle(): Promise<BundleData> {
  const recordingId = (await status()).recording.recordingId;
  return ui.evaluate(async (id) => {
    const db = await new Promise<IDBDatabase>((r, j) => {
      const q = indexedDB.open("mes-evidence-v1");
      q.onsuccess = () => r(q.result);
      q.onerror = () => j(q.error);
    });
    const get = (name: string, one = false) =>
      new Promise<any>((r, j) => {
        const s = db.transaction(name).objectStore(name),
          q = one ? s.get(id) : s.index("recordingId").getAll(id);
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
  }, recordingId);
}
async function save(name: string) {
  if ((await status()).recording?.state !== "FAILED") {
    await ui.bringToFront();
    await ui.click("#stop");
    await until(status, (s) => s.recording?.state === "READY", "保存 " + name);
  }
  const data = await bundle(),
    result = await createPackage(data),
    validation = await validatePackage(result.zip);
  await writeFile(resolve(output, name + ".zip"), result.zip);
  await writeFile(
    resolve(output, name + "-validation.json"),
    JSON.stringify(validation, null, 2),
  );
  assert.ok(validation.valid, JSON.stringify(validation));
  return data;
}
async function verifyDebuggerLoss(label: string, rootId: number) {
  await until(
    status,
    (s) =>
      s.targets.find((t: any) => t.browserTabId === rootId)?.channels.network
        .state === "LOST",
    label,
  );
  const marker = "NATIVE-AFTER-DETACH-" + uuid();
  await root.evaluate(async (marker) => {
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      marker;
    await fetch("/api/echo?id=" + marker);
  }, marker);
  // 接受过的页面证据与 UI 状态一并检查，不能拿操作前的 s 证明没有重连。
  await until(
    async () => JSON.stringify((await bundle()).chunks),
    (s) => s.includes(marker),
    "降级后的页面证据",
  );
  await until(
    () => ui.locator("#status-pill").textContent(),
    (s) => s === "部分采集",
    "部分采集提示",
  );
  const s = await status(),
    target = s.targets.find((t: any) => t.browserTabId === rootId),
    data = await bundle();
  check(
    ["T36"],
    label + " 后页面继续保存、降级可见且未自动重连",
    target.channels.page.state === "ACTIVE" &&
      target.channels.semantic.state === "ACTIVE" &&
      target.channels.network.state === "LOST" &&
      target.channels.runtime.state === "LOST" &&
      target.debuggerBlocked &&
      !data.network.some((n) => n.request.url.includes(marker)),
    { target, marker },
  );
}
try {
  context = await chromium.launchPersistentContext(profile, {
    executablePath: process.env.MES_TEST_CHROME,
    headless: false,
    viewport: { width: 1200, height: 1000 },
    ignoreDefaultArgs: ["--disable-back-forward-cache"],
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  worker = await collectorWorker(context);
  const productionManifest = await readFile(resolve("dist/manifest.json"));
  const testManifest = await readFile(resolve(extension, "manifest.json"));
  assert.deepEqual(testManifest, productionManifest);
  await writeFile(
    resolve(output, "manifest-proof.json"),
    JSON.stringify(
      {
        unchanged: true,
        sha256: createHash("sha256").update(testManifest).digest("hex"),
      },
      null,
      2,
    ),
  );
  extId = new URL(worker.url()).host;
  ui = await context.newPage();
  await ui.goto(`chrome-extension://${extId}/control.html`);
  await ui.evaluate("globalThis.__name=fn=>fn");
  root = await context.newPage();
  await root.goto("http://127.0.0.1:4477/?id=NATIVE-ROOT");
  denied = await context.newPage();
  await denied.goto("http://localhost:4477/?id=DENIED-ROOT");
  const rootId = (await tab(root.url()))!,
    deniedId = (await tab(denied.url()))!;
  const selectedWindow = await ui.evaluate(
    (tabId) => chrome.windows.create({ tabId, type: "normal", focused: false }),
    rootId,
  );
  await configure([], ["http://127.0.0.1:4477"]);
  await ui
    .locator(".window-group")
    .filter({ hasText: `窗口 ${selectedWindow!.id}` })
    .locator(".window-heading input")
    .check();
  await root.bringToFront();
  await checkpoint(
    "native-unrelated",
    "窗口复选框已选定当时的根。在根页面所在窗口按 Cmd+T（Windows/Linux 为 Ctrl+T），打开 http://127.0.0.1:4477/?id=NATIVE-UNRELATED，然后确认；此时还未开始采集。",
  );
  await ui.bringToFront();
  await checkpoint(
    "grant-first-origin",
    "在采集控制页点击开始，在 Chrome 原生权限弹窗允许 127.0.0.1。完成后记录实际操作和界面证据。",
  );
  let s = await until(
    status,
    (s) =>
      s.recording?.state === "RECORDING" &&
      s.targets[0]?.channels.page.state === "ACTIVE",
    "首次授权",
  );
  check(
    ["T43"],
    "生产 manifest 原生许可后根页面已采集",
    true,
    await ui.evaluate(() => chrome.permissions.getAll()),
  );
  s = await status();
  await writeFile(
    resolve(output, "native-opening-status.json"),
    JSON.stringify(s, null, 2),
  );
  check(
    ["T02"],
    "窗口选择冻结后原生快捷键新建的无关页未纳入",
    (await ui.evaluate(() => chrome.tabs.query({}))).some((t) =>
      t.url?.includes("NATIVE-UNRELATED"),
    ) &&
      s.targets.length === 1 &&
      s.targets[0].browserTabId === rootId &&
      !s.targets.some((t: any) => t.url.includes("NATIVE-UNRELATED")),
  );
  const menuRows: any[] = [];
  for (const mode of ["new-tab", "new-window"]) {
    const marker = "native-" + mode + "-" + uuid();
    await root.evaluate((marker) => {
      document.querySelector<HTMLAnchorElement>("#child")!.href =
        "/?id=" + marker;
    }, marker);
    await root.bringToFront();
    await checkpoint(
      "context-" + mode,
      `在根页面“普通子标签”链接上点击鼠标右键，选择“在新${mode === "new-tab" ? "标签页" : "窗口"}中打开”。目标 URL 含 ${marker}，完成后记录原生菜单操作证据。`,
    );
    const result = await until(
      status,
      (s) =>
        s.targets.some(
          (t: any) =>
            t.url.includes(marker) &&
            t.channels.page.state === "ACTIVE" &&
            t.channels.network.state === "ACTIVE",
        ),
      "菜单目标就绪",
    );
    const target = result.targets.find((t: any) => t.url.includes(marker)),
      parent = result.targets.find((t: any) => t.browserTabId === rootId);
    check(
      ["T14"],
      `原生菜单 ${mode} 的唯一新目标归属实际根`,
      result.targets.filter((t: any) => t.url.includes(marker)).length === 1 &&
        target.parentTabInstanceId === parent.tabInstanceId &&
        target.lineageEvidence.length > 0 &&
        (mode === "new-tab"
          ? target.windowId === parent.windowId
          : target.windowId !== parent.windowId),
      target,
    );
    menuRows.push({
      mode,
      marker,
      tabInstanceId: target.tabInstanceId,
      createdObservedAt: target.createdObservedAt,
      lineageConfirmedAt: target.lineageConfirmedAt,
      networkReadyAt: target.networkReadyAt,
      firstBaselineAt: target.firstBaselineAt,
      lineageEvidence: target.lineageEvidence,
    });
  }
  const opening = await save("native-opening");
  const server = (
    await readFile(resolve(output, "fixture-backend.ndjson"), "utf8")
  )
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const timing = menuRows.map((row) => ({
    ...row,
    serverRequests: server.filter(
      (r) => r.path === "/api/first" && r.marker === row.marker,
    ),
    capturedFirstRequests: opening.network
      .filter(
        (n) =>
          n.tabInstanceId === row.tabInstanceId &&
          new URL(n.request.url).pathname === "/api/first",
      )
      .map((n) => ({
        requestKey: n.requestKey,
        sourceTime: n.sourceTime,
        sourceClock: n.sourceClock,
        startedAt: n.startedAt,
      })),
  }));
  await writeFile(
    resolve(output, "first-request-timings.json"),
    JSON.stringify(
      {
        method: "原生菜单人工操作，保留原始时钟；不要求首请求零丢失",
        attempts: timing,
      },
      null,
      2,
    ),
  );
  check(
    ["T16"],
    "两种菜单各有唯一首请求服务端到达与独立测量",
    timing.every(
      (r) =>
        r.serverRequests.length === 1 && r.capturedFirstRequests.length <= 1,
    ),
    timing,
  );
  await ui.click("#new");
  await configure(
    [rootId, deniedId],
    ["http://127.0.0.1:4477", "http://localhost:4477"],
  );
  await checkpoint(
    "deny-second-origin",
    "在采集控制页点击开始，在 Chrome 新增 localhost 权限弹窗拒绝；127.0.0.1 的既有权限保留。",
  );
  s = await until(
    status,
    (s) =>
      s.recording?.state === "RECORDING" &&
      s.targets.length === 2 &&
      s.targets.find((t: any) => t.browserTabId === rootId)?.channels.page
        .state === "ACTIVE" &&
      s.targets.find((t: any) => t.browserTabId === deniedId)?.channels.page
        .state === "BLOCKED",
    "混合根",
  );
  check(
    ["T43"],
    "新增 origin 原生拒绝仍保留已有授权根，未授权根无页面通道",
    s.targets.find((t: any) => t.browserTabId === rootId)?.channels.page
      .state === "ACTIVE" &&
      s.targets.find((t: any) => t.browserTabId === deniedId)?.channels.page
        .state === "BLOCKED",
    s.targets,
  );
  const rootBeforeNavigation = s.targets.find(
    (t: any) => t.browserTabId === rootId,
  );
  await root.goto("http://localhost:4477/?id=NATIVE-UNAUTHORIZED");
  await until(
    status,
    (s) =>
      s.targets.find((t: any) => t.browserTabId === rootId)?.captureState ===
      "BLOCKED",
    "未授权导航",
  );
  await root.evaluate(async () => {
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      "NATIVE-UNAUTHORIZED-ACTION";
    await fetch("/api/echo?id=NATIVE-UNAUTHORIZED-ACTION");
  });
  await root.goto("http://127.0.0.1:4477/?id=NATIVE-RETURNED");
  const returned = await until(
    status,
    (s) =>
      s.targets.find((t: any) => t.browserTabId === rootId)?.channels.page
        .state === "ACTIVE" &&
      s.targets.find((t: any) => t.browserTabId === rootId)?.channels.network
        .state === "ACTIVE",
    "授权域名返回",
  );
  const returnedTarget = returned.targets.find(
    (t: any) => t.browserTabId === rootId,
  );
  check(
    ["T37"],
    "生产权限下未授权导航停止、返回重建基线",
    returnedTarget.documents.at(-1).documentId !==
      rootBeforeNavigation.documents.at(-1).documentId &&
      !!returnedTarget.documents.at(-1).baselineRef,
  );
  await root.bringToFront();
  await checkpoint(
    "cancel-debugger",
    "在 Chrome 的“浏览器采集助手已开始调试此浏览器”提示条点击取消。不要调用 debugger.detach API。",
  );
  await verifyDebuggerLoss("原生取消调试", rootId);
  await until(
    bundle,
    (b) =>
      b.targets.some(
        (t: any) => t.browserTabId === rootId && t.debuggerBlocked,
      ),
    "调试拒绝持久化",
  );
  const cdp = await context.newCDPSession(ui),
    versions: any[] = [];
  cdp.on("ServiceWorker.workerVersionUpdated", (event) =>
    versions.push(...event.versions),
  );
  await cdp.send("ServiceWorker.enable");
  await until(
    async () => versions,
    (v) => v.some((x: any) => x.scriptURL === worker.url()),
    "后台版本",
  );
  await cdp.send("ServiceWorker.stopWorker", {
    versionId: versions.filter((v) => v.scriptURL === worker.url()).at(-1)
      .versionId,
  });
  await until(
    status,
    (s) =>
      s.recording.gaps.some(
        (g: any) => g.code === "service_worker_restarted",
      ) &&
      s.targets.find((t: any) => t.browserTabId === rootId)?.channels.page
        .state === "ACTIVE",
    "原生取消后后台恢复",
  );
  worker = await collectorWorker(context);
  await cdp.detach();
  await verifyDebuggerLoss("原生取消后后台唤醒", rootId);

  const mixed = await save("native-mixed");
  const deniedTarget = mixed.targets.find((t) => t.browserTabId === deniedId)!;
  check(
    ["T43"],
    "混合权限包中未授权根没有任何业务事件或请求",
    !mixed.chunks
      .flatMap((c) => c.events)
      .some(
        (e) =>
          e.tabInstanceId === deniedTarget.tabInstanceId &&
          e.channel !== "control",
      ) &&
      !mixed.network.some(
        (n) => n.tabInstanceId === deniedTarget.tabInstanceId,
      ),
  );
  check(
    ["T37"],
    "未授权导航区间无业务哨兵",
    !JSON.stringify({
      events: mixed.chunks
        .flatMap((c) => c.events)
        .filter((e) => e.channel !== "control"),
      network: mixed.network,
      blobs: mixed.blobs,
    }).includes("NATIVE-UNAUTHORIZED-ACTION"),
  );
  await ui.click("#new");
  await configure([deniedId], ["http://localhost:4477"]);
  await checkpoint(
    "deny-all-origins",
    "仅选择了尚未授权的 localhost 根。在控制页点击开始并在 Chrome 原生权限弹窗拒绝本次请求。",
  );
  await until(status, (s) => s.recording?.state === "FAILED", "全部失败会话");
  await until(
    () => ui.locator("#status-pill").textContent(),
    (t) => t === "启动失败 · 可导出",
    "失败 UI",
  );
  const failed = await save("native-all-failed");
  check(
    ["T43"],
    "原生全拒绝保存 FAILED 诊断且没有业务证据",
    failed.recording.state === "FAILED" &&
      failed.network.length === 0 &&
      failed.chunks
        .flatMap((c) => c.events)
        .every((e) => e.channel === "control"),
  );
  await ui.click("#new");
  await configure([rootId], ["http://127.0.0.1:4477"]);
  await ui.click("#start");
  await until(
    status,
    (s) =>
      s.recording?.state === "RECORDING" &&
      s.targets[0]?.channels.network.state === "ACTIVE",
    "F12 前",
  );
  await root.bringToFront();
  await checkpoint(
    "open-devtools",
    "在根页面按实际 F12（macOS 可使用 Fn+F12 或 Chrome 菜单打开开发者工具），保持 DevTools 打开并记录截图。",
  );
  await verifyDebuggerLoss("实际打开 DevTools", rootId);
  s = await status();
  platform.push({ name: "F12", status: s });
  await checkpoint(
    "close-devtools",
    "在 Chrome 原生界面关闭刚打开的 DevTools。",
  );
  await verifyDebuggerLoss("关闭 DevTools", rootId);
  await save("native-devtools");
  await writeAcceptance(
    output,
    extension,
    context.browser()!.version(),
    checks,
    { permissionMode: "未经修改的生产 manifest，原生权限请求/拒绝", platform },
  );
} catch (e) {
  console.error(e);
  await writeFile(
    resolve(output, "failure.json"),
    JSON.stringify({ error: String(e), checks, platform }, null, 2),
  );
  process.exitCode = 1;
} finally {
  try {
    await context?.close();
  } finally {
    try {
      await fixture.close();
    } finally {
      await rm(profile, { recursive: true, force: true });
    }
  }
}
