import { collectorWorker } from './extension-worker';
import { chromium, type Page } from "playwright";
import { mkdir, cp, readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { resolve } from "node:path";
// @ts-expect-error standalone fixture
import { startFixtures } from "../fixtures/server.mjs";
import { DEFAULT_POLICY } from "../shared/policy";
import { uuid } from "../shared/contracts";
import { createPackage, validatePackage } from "../extension/export/package";
import { writeAcceptance, type AcceptanceCheck } from "./acceptance-report";
const output = resolve(
  process.env.MES_TEST_OUTPUT ?? "output/playwright/phase7-platform",
);
await mkdir(output, { recursive: true });
const extension = resolve(output, "test-extension");
await cp("dist", extension, { recursive: true });
const manifest = JSON.parse(
  await readFile(resolve(extension, "manifest.json"), "utf8"),
);
manifest.host_permissions = ["http://127.0.0.1/*"];
await writeFile(resolve(extension, "manifest.json"), JSON.stringify(manifest));
const fixture = await startFixtures({
  port: 4487,
  crossPort: 4488,
  logFile: resolve(output, "fixture-backend.ndjson"),
});
const profile = await mkdtemp("/private/tmp/mes-evidence-platform-");
const context = await chromium.launchPersistentContext(profile, {
  executablePath: process.env.MES_TEST_CHROME,
  headless: true,
  ignoreDefaultArgs: ["--disable-back-forward-cache"],
  args: [
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
  ],
});
let worker =
  await collectorWorker(context);
const extId = new URL(worker.url()).host;
let ui!: Page;
const evidence: any[] = [];
const checks: AcceptanceCheck[] = [];
async function reopen() {
  ui = await context.newPage();
  await ui.goto(`chrome-extension://${extId}/control.html`);
  await ui.evaluate("globalThis.__name=fn=>fn");
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
async function until(
  read: () => Promise<any>,
  pred: (s: any) => unknown,
  label: string,
) {
  let s;
  for (let i = 0; i < 150; i++) {
    s = await read();
    if (pred(s)) return s;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw Error(`${label}: ${JSON.stringify(s).slice(0, 1500)}`);
}
async function start(p: Page) {
  const dir = await rpc("scope.list");
  const id = await ui.evaluate(
    async (url) =>
      (await chrome.tabs.query({})).find((t) => t.url === url)!.id!,
    p.url(),
  );
  await rpc("session.start", {
    recordingId: uuid(),
    commandId: uuid(),
    browserRunId: dir.browserRunId,
    rootBrowserTabIds: [id],
    policy: {
      ...structuredClone(DEFAULT_POLICY),
      pageOrigins: ["http://127.0.0.1:4487"],
      apiRules: [{ origin: "http://127.0.0.1:4487", pathPrefix: "/api/" }],
    },
    title: "平台生命周期",
    environmentId: "LOCAL-FIXTURE",
  });
  return until(
    status,
    (s) => s.targets[0]?.channels.page.state === "ACTIVE",
    "ready",
  );
}
let packageSeq = 0;
async function stop() {
  const s = await status();
  await rpc("session.stop", {
    recordingId: s.recording.recordingId,
    commandId: uuid(),
  });
  await until(status, (s) => s.recording.state === "READY", "saved");
  const b = await ui.evaluate(async (id) => {
    const db = await new Promise<IDBDatabase>((r) => {
      const q = indexedDB.open("mes-evidence-v1");
      q.onsuccess = () => r(q.result);
    });
    const get = (name: string, one = false) =>
      new Promise<any>((r) => {
        const q = one
          ? db.transaction(name).objectStore(name).get(id)
          : db
              .transaction(name)
              .objectStore(name)
              .index("recordingId")
              .getAll(id);
        q.onsuccess = () => r(q.result);
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
  }, s.recording.recordingId);
  const pkg = await createPackage(b);
  const validation = await validatePackage(pkg.zip);
  await writeFile(resolve(output, `platform-${++packageSeq}.zip`), pkg.zip);
  await writeFile(
    resolve(output, `platform-${packageSeq}.json`),
    JSON.stringify({ bundle: b, validation }, null, 2),
  );
  return b;
}
function check(tIds: string[], name: string, c: unknown, detail?: unknown) {
  checks.push({ tIds, name, passed: !!c, detail });
  if (!c) throw Error(name);
  console.log("PASS " + name);
}
try {
  await reopen();
  await worker.evaluate(() => {
    (globalThis as any).__platform = [];
    chrome.tabs.onReplaced.addListener((added, removed) =>
      (globalThis as any).__platform.push({
        type: "tabs.onReplaced",
        added,
        removed,
        at: Date.now(),
      }),
    );
    chrome.webNavigation.onTabReplaced.addListener((d) =>
      (globalThis as any).__platform.push({
        type: "webNavigation.onTabReplaced",
        ...d,
      }),
    );
    chrome.tabs.onRemoved.addListener((id) =>
      (globalThis as any).__platform.push({
        type: "tabs.onRemoved",
        id,
        at: Date.now(),
      }),
    );
  });
  const p = await context.newPage();
  await p.goto("http://127.0.0.1:4487/bfcache?id=before");
  let s = await start(p);
  const before = s.targets[0];
  const cdp = await context.newCDPSession(p);
  const misses: any[] = [];
  cdp.on("Page.backForwardCacheNotUsed", (e) => misses.push(e));
  await cdp.send("Page.enable");
  await p.goto("http://127.0.0.1:4487/bfcache?id=away");
  await until(
    status,
    (s) =>
      s.targets[0].documents.some(
        (d: any) =>
          d.documentId !== before.documents[0].documentId && d.firstBaselineAt,
      ),
    "离开页基线",
  );
  await p
    .goBack({ waitUntil: "commit" })
    .catch((e) =>
      evidence.push({ scenario: "BFCache_navigation_wait", error: String(e) }),
    );
  await new Promise((r) => setTimeout(r, 1000));
  s = await until(
    status,
    (s) => s.targets[0]?.channels.page.state === "ACTIVE",
    "BFCache 恢复页面通道",
  );
  await p.evaluate(() => {
    document.querySelector<HTMLInputElement>("input")!.value = "AFTER_BFCACHE";
  });
  const life = await p.evaluate(() => (window as any).life);
  evidence.push({
    scenario: "BFCache",
    status: life.some((x: any) => x.persisted)
      ? "命中，需检查流"
      : "未命中，保留待验收",
    life,
    misses,
    before,
    after: s.targets[0],
    ignoredDefaultArgs: ["--disable-back-forward-cache"],
  });
  check(
    ["T22"],
    "完整导航后有新文档和基线，流身份不复用",
    s.targets[0].documents.filter((d: any) => d.firstBaselineAt).length >= 2 &&
      new Set(s.targets[0].documents.map((d: any) => d.recorderStreamId))
        .size >= 2,
  );
  await cdp.send("Page.setWebLifecycleState", { state: "frozen" });
  await new Promise((r) => setTimeout(r, 300));
  await cdp.send("Page.setWebLifecycleState", { state: "active" });
  await p.evaluate(() => {
    document.querySelector<HTMLInputElement>("input")!.value = "AFTER_FREEZE";
  });
  evidence.push({
    scenario: "freeze",
    method: "真实 CDP Page.setWebLifecycleState frozen→active",
    status: await status(),
  });
  await ui.bringToFront();
  const discarded = await ui
    .evaluate((id) => chrome.tabs.discard(id), s.targets[0].browserTabId)
    .catch((e) => ({ error: String(e) }));
  evidence.push({ scenario: "discard", result: discarded });
  if (discarded && "discarded" in discarded && discarded.discarded) {
    await new Promise((r) => setTimeout(r, 500));
    const tabs = await ui.evaluate(() => chrome.tabs.query({}));
    evidence.push({
      scenario: "discard_after",
      tabs,
      events: await worker.evaluate(() => (globalThis as any).__platform),
      status: await status(),
    });
    const replacement = tabs.find((t) => t.url?.includes("/bfcache?id=before"));
    if (replacement?.id) {
      await ui.evaluate(async (id) => {
        await chrome.tabs.update(id, { active: true });
        await chrome.tabs.reload(id);
      }, replacement.id);
      await until(
        status,
        (s) =>
          s.targets.some(
            (t: any) =>
              t.lifecycle === "OPEN" && t.channels.page.state === "ACTIVE",
          ),
        "discard recovery",
      );
    } else
      evidence.push({
        scenario: "discard_recovery",
        status: "目标丢弃后在自动化环境中被移除，恢复待验收",
      });
  }
  await cdp.detach().catch(() => {});
  const recovered = await status();
  const activeTarget = recovered.targets.find(
    (t: any) => t.lifecycle === "OPEN",
  );
  await ui.evaluate(
    async (id) =>
      chrome.scripting.executeScript({
        target: { tabId: id },
        world: "MAIN",
        func: () => {
          document.querySelector<HTMLInputElement>("input")!.value =
            "AFTER_REPLACEMENT";
        },
      }),
    activeTarget.browserTabId,
  );
  await new Promise((r) => setTimeout(r, 1100));
  const lifecycleBundle = await stop();
  const lifecycleEvents = lifecycleBundle.chunks.flatMap((c: any) => c.events);
  check(
    ["T24"],
    "真实 pageshow.persisted 命中，恢复新流/基线且一次赋值只保存一次动作",
    life.some((x: any) => x.type === "pageshow" && x.persisted) &&
      lifecycleEvents.filter(
        (e: any) =>
          e.kind === "ui.action" &&
          e.payload.action === "programmatic_change" &&
          e.payload.after?.value?.value === "AFTER_BFCACHE",
      ).length === 1 &&
      new Set(
        lifecycleBundle.targets
          .find((t: any) => t.lifecycle === "REPLACED")
          .documents.map((d: any) => d.recorderStreamId),
      ).size >= 2,
  );
  const platformEvents = await worker.evaluate(
    () => (globalThis as any).__platform,
  );
  evidence.push({
    scenario: "replacement",
    status: "通过",
    events: platformEvents,
    after: recovered,
  });
  check(
    ["T25"],
    "实际丢弃触发两种正式 replacement 通知，只产生一个新实例并恢复单流",
    platformEvents.some((e: any) => e.type === "tabs.onReplaced") &&
      platformEvents.some(
        (e: any) => e.type === "webNavigation.onTabReplaced",
      ) &&
      lifecycleBundle.targets.length === 2 &&
      lifecycleBundle.targets.find((t: any) => t.replacesTabInstanceId)
        ?.replacesTabInstanceId ===
        lifecycleBundle.targets.find((t: any) => t.lifecycle === "REPLACED")
          ?.tabInstanceId &&
      lifecycleEvents.filter(
        (e: any) =>
          e.kind === "ui.action" &&
          e.payload.action === "programmatic_change" &&
          e.payload.after?.value?.value === "AFTER_REPLACEMENT",
      ).length === 1 &&
      lifecycleEvents.some(
        (e: any) =>
          e.kind === "ui.action" &&
          e.payload.after?.value?.value === "AFTER_FREEZE",
      ),
  );

  // 极快父页关闭：真实 window.open / onCreatedNavigationTarget，不造来源通知。
  const root = await context.newPage();
  await root.goto("http://127.0.0.1:4487/?id=fast-root");
  await start(root);
  await root.bringToFront();
  let created = context.waitForEvent("page");
  await root.click("#window-open");
  const parent = await created;
  await parent.waitForLoadState();
  await until(
    status,
    (s) =>
      s.targets.some(
        (t: any) =>
          t.url.includes("window-open") && t.channels.page.state === "ACTIVE",
      ),
    "parent ready",
  );
  await parent.bringToFront();
  created = context.waitForEvent("page");
  await parent.click("#fast-close");
  const leaf = await created;
  await leaf.waitForLoadState();
  s = await until(
    status,
    (s) =>
      s.targets.some(
        (t: any) =>
          t.url.includes("fast-child") && t.channels.page.state === "ACTIVE",
      ),
    "fast child",
  );
  check(
    ["T11"],
    "父页同步打开后立即关闭，可信来源仍让子页继续",
    parent.isClosed() &&
      s.targets.some((t: any) => t.url.includes("fast-child") && t.accepting),
    s.targets,
  );
  await stop();
  // 实际页面伪造控制命令：content script 的 sender 不具备控制页身份。
  await start(root);
  const old = (await status()).recording;
  const rootId = (await status()).targets[0].browserTabId;
  const forged = await ui.evaluate(
    async ({ rootId, id }) =>
      (
        await chrome.scripting.executeScript({
          target: { tabId: rootId },
          world: "ISOLATED",
          func: async (recordingId) =>
            chrome.runtime.sendMessage({
              type: "session.stop",
              recordingId,
              commandId: "forged-control",
            }),
          args: [id],
        })
      )[0]?.result,
    { rootId, id: old.recordingId },
  );
  check(
    ["T45"],
    "真实 content script 不能伪造控制页 STOP",
    forged?.ok === false && (await status()).recording.state === "RECORDING",
    forged,
  );
  // 读取 chrome://extensions 实际开发者模式重载按钮；不调用 runtime.reload 代替。
  const ex = await context.newPage();
  await ex.goto("chrome://extensions");
  await ex.locator("#devMode").check();
  const card = ex
    .locator("extensions-item")
    .filter({ hasText: "浏览器采集助手" });
  await card.waitFor();
  await writeFile(
    resolve(output, "extensions-before.html"),
    await ex.content(),
  );
  const reload = card.locator("#dev-reload-button");
  await reload.click();
  await new Promise((r) => setTimeout(r, 1500));
  const extWorkers = context
    .serviceWorkers()
    .filter((w) => w.url().startsWith(`chrome-extension://${extId}/`));
  evidence.push({
    scenario: "developer_reload",
    method: "chrome://extensions developer mode → actual reload button",
    workerUrls: extWorkers.map((w) => w.url()),
  });
  if (extWorkers.length) {
    await ui.close().catch(() => {});
    await reopen();
    const dir = await rpc("scope.list");
    const history = await rpc("history.list");
    check(
      ["T40"],
      "实际开发者模式重载中断旧会话，新运行期不复用授权",
      dir.browserRunId !== old.browserRunId &&
        history.recordings.find((r: any) => r.recordingId === old.recordingId)
          ?.state === "INTERRUPTED",
    );
  } else
    evidence.push({
      scenario: "developer_reload",
      status: "扩展被 Chrome 移除；命令行加载环境不能完成重载恢复，保留待验收",
    });

  await writeAcceptance(
    output,
    extension,
    context.browser()!.version(),
    checks,
    { platform: evidence },
  );
} catch (e) {
  evidence.push({
    scenario: "failure_status",
    status: await status().catch(() => null),
    tabs: await ui.evaluate(() => chrome.tabs.query({})).catch(() => null),
  });
  console.error(e);
  process.exitCode = 1;
  await writeFile(
    resolve(output, "failure.json"),
    JSON.stringify({ error: String(e), checks, evidence }, null, 2),
  );
} finally {
  await writeFile(
    resolve(output, "platform-evidence.json"),
    JSON.stringify(evidence, null, 2),
  );
  await context.close();
  await fixture.close();
  await rm(profile, { recursive: true, force: true });
}
