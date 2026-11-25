import {
  chromium,
  type BrowserContext,
  type Page,
  type Worker,
} from "playwright";
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
  appendFile,
} from "node:fs/promises";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
// @ts-expect-error standalone fixture
import { startFixtures } from "../fixtures/server.mjs";
import { collectorWorker } from "./extension-worker";
import { writeAcceptance, type AcceptanceCheck } from "./acceptance-report";
import { DEFAULT_POLICY } from "../shared/policy";
import { uuid, type BundleData, type Target } from "../shared/contracts";
import { createPackage, validatePackage } from "../extension/export/package";

const output = resolve(
  process.env.MES_TEST_OUTPUT ?? `output/playwright/permissions-${Date.now()}`,
);
await mkdir(output, { recursive: true });
const extension = resolve(output, "test-extension");
await cp(resolve("dist"), extension, { recursive: true });
const productionManifest = await readFile(
  resolve(extension, "manifest.json"),
  "utf8",
);
const profile = await mkdtemp("/private/tmp/mes-evidence-permissions-");
const origin = "http://127.0.0.1:4507",
  cross = "http://localhost:4508";
const fixture = await startFixtures({
  port: 4507,
  crossPort: 4508,
  logFile: resolve(output, "fixture-backend.ndjson"),
});
let context: BrowserContext | undefined, ui: Page, rid: string;
let worker!: Worker;
let browserVersion = "";
const checks: AcceptanceCheck[] = [];
const policy = {
  ...structuredClone(DEFAULT_POLICY),
  pageOrigins: [origin, cross],
  apiRules: [origin, cross].map((origin) => ({ origin, pathPrefix: "/api/" })),
};
const launch = () =>
  chromium.launchPersistentContext(profile, {
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
  const start = Date.now();
  let last: T;
  do {
    last = await read();
    if (pred(last)) return last;
    await new Promise((r) => setTimeout(r, 100));
  } while (Date.now() - start < 20_000);
  throw Error(label + ": " + JSON.stringify(last!).slice(0, 6000));
}
function check(
  tIds: string[],
  name: string,
  condition: unknown,
  detail?: unknown,
) {
  checks.push({ tIds, name, passed: !!condition, detail });
  assert.ok(condition, name + ": " + JSON.stringify(detail));
  console.log("PASS " + name);
}
const tabId = (p: Page) =>
  ui.evaluate(
    async (url) =>
      (await chrome.tabs.query({})).find((t) => t.url === url)!.id!,
    p.url(),
  );
async function bundle(): Promise<BundleData> {
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
  }, rid);
}
function business(b: BundleData) {
  return JSON.stringify({
    events: b.chunks
      .flatMap((c) => c.events)
      .filter((e) => e.channel !== "control"),
    blobs: b.blobs,
    network: b.network,
  });
}
async function start(ids: number[], title: string) {
  rid = uuid();
  return rpc("session.start", {
    recordingId: rid,
    commandId: uuid(),
    browserRunId: (await rpc("scope.list")).browserRunId,
    rootBrowserTabIds: ids,
    title,
    policy,
  });
}
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
    "目标就绪 " + id,
  );
  return s.targets.find((t: Target) => t.browserTabId === id) as Target;
}
async function save(name: string) {
  if ((await status()).recording.state !== "FAILED") {
    await rpc("session.stop", { recordingId: rid, commandId: uuid() });
    await until(status, (s) => s.recording.state === "READY", "停止保存");
  }
  const b = await bundle(),
    result = await createPackage(b),
    validation = await validatePackage(result.zip);
  await writeFile(resolve(output, name + ".zip"), result.zip);
  await writeFile(resolve(output, name + ".json"), JSON.stringify(b));
  await writeFile(
    resolve(output, name + "-validation.json"),
    JSON.stringify(validation, null, 2),
  );
  check(
    ["T48"],
    name + " 问题包结构、身份与引用校验通过",
    validation.valid,
    validation,
  );
  return b;
}
async function permission(originPattern: string) {
  const before = await ui.evaluate(() => chrome.permissions.getAll());
  const result = await ui.evaluate(
    (origin) => chrome.permissions.remove({ origins: [origin] }),
    originPattern,
  );
  const after = await ui.evaluate(() => chrome.permissions.getAll());
  await appendFile(
    resolve(output, "permission-actions.ndjson"),
    JSON.stringify({
      kind: "remove",
      originPattern,
      result,
      before,
      after,
      at: new Date().toISOString(),
      method: "真实 Chrome permissions.remove；不计原生撤权界面",
    }) + "\n",
  );
  assert.equal(result, true);
}
async function seededContext() {
  // Each reset happens only between stopped scenarios. It is never represented
  // as permission restoration within a recording.
  await context?.close();
  context = undefined;
  const seeded = JSON.parse(productionManifest);
  seeded.host_permissions = ["http://127.0.0.1/*", "http://localhost/*"];
  await writeFile(resolve(extension, "manifest.json"), JSON.stringify(seeded));
  context = await launch();
  worker = await collectorWorker(context);
  const seedPermissions = await worker.evaluate(() =>
    chrome.permissions.getAll(),
  );
  await context.close();
  context = undefined;
  await writeFile(resolve(extension, "manifest.json"), productionManifest);
  context = await launch();
  worker = await collectorWorker(context);
  browserVersion = context.browser()!.version();
  const actualManifest = await readFile(
    resolve(extension, "manifest.json"),
    "utf8",
  );
  assert.equal(actualManifest, productionManifest);
  await appendFile(
    resolve(output, "permission-setup.ndjson"),
    JSON.stringify({
      at: new Date().toISOString(),
      seedPermissions,
      productionPermissions: await worker.evaluate(() =>
        chrome.permissions.getAll(),
      ),
      manifestUnchanged: true,
      manifestSha256: createHash("sha256").update(actualManifest).digest("hex"),
      method:
        "场景间在独立 profile 预授权 fixture，关闭后恢复原始 manifest；不是会话内重新授权或原生许可验收",
    }) + "\n",
  );
  ui = await context.newPage();
  await ui.goto(
    `chrome-extension://${new URL(worker.url()).host}/control.html`,
  );
  await ui.evaluate("globalThis.__name=fn=>fn");
}
async function act(page: Page, marker: string) {
  await page.evaluate(async (marker) => {
    document.querySelector<HTMLInputElement>("[name=precision]")!.value =
      marker;
    await fetch("/api/echo?id=" + marker).then((r) => r.text());
  }, marker);
}
async function restartWorker() {
  const scriptURL = worker.url(),
    cdp = await context!.newCDPSession(ui),
    versions: any[] = [];
  cdp.on("ServiceWorker.workerVersionUpdated", (event) =>
    versions.push(...event.versions),
  );
  await cdp.send("ServiceWorker.enable");
  await until(
    async () => versions,
    (v) => v.some((x) => x.scriptURL === scriptURL),
    "后台版本",
  );
  await cdp.send("ServiceWorker.stopWorker", {
    versionId: versions.filter((v) => v.scriptURL === scriptURL).at(-1)
      .versionId,
  });
  await until(
    status,
    (s) =>
      s.recording.gaps.some((g: any) => g.code === "service_worker_restarted"),
    "后台重新对账",
  );
  worker = await collectorWorker(context!);
  await cdp.detach();
}
try {
  await seededContext();
  let root = await context!.newPage(),
    healthy = await context!.newPage(),
    other = await context!.newPage();
  await root.goto(origin + "/?id=ROOT");
  await healthy.goto(origin + "/?id=HEALTHY");
  await other.goto(cross + "/?id=OTHER");
  let rootId = await tabId(root),
    healthyId = await tabId(healthy),
    otherId = await tabId(other);
  await start([rootId, healthyId], "子 frame 撤权");
  await ready(rootId);
  const healthyBefore = await ready(healthyId);
  await root.evaluate((url) => {
    const f = document.createElement("iframe");
    f.id = "permission-frame";
    f.src = url;
    document.body.append(f);
  }, cross + "/frame?id=permission");
  const initial = await until(
    status,
    (s) =>
      s.targets
        .find((t: Target) => t.browserTabId === rootId)
        .documents.some(
          (d: any) => d.chromeFrameId !== 0 && !d.endedAt && d.baselineRef,
        ),
    "授权子文档基线",
  );
  const rootBefore: Target = initial.targets.find(
    (t: Target) => t.browserTabId === rootId,
  );
  const child = root
    .frames()
    .find((f) => f.url().includes("/frame?id=permission"))!;
  await child.locator("#frame-program").click();
  await until(
    bundle,
    (b) =>
      b.network.some(
        (n) =>
          n.tabInstanceId === rootBefore.tabInstanceId &&
          n.chromeFrameId !== 0 &&
          n.request.url.includes("/api/token") &&
          n.response.bodyRef,
      ),
    "撤权前子文档业务采集",
  );
  check(["T43"], "实际授权子文档有基线及可引用业务请求", true);
  await worker.evaluate(() => {
    (globalThis as any).__heldBodies = [];
    const original = chrome.debugger.sendCommand.bind(chrome.debugger);
    (chrome.debugger as any).sendCommand = async (
      source: any,
      method: string,
      params: any,
    ) => {
      const result: any = await original(source, method, params);
      if (
        method === "Network.getResponseBody" &&
        result?.body?.includes("BEFORE-CHILD-REVOKE")
      )
        await new Promise((r) => (globalThis as any).__heldBodies.push(r));
      return result;
    };
  });
  await child.evaluate(() =>
    fetch("/api/echo?id=BEFORE-CHILD-REVOKE").then((r) => r.text()),
  );
  await until(
    () => worker.evaluate(() => (globalThis as any).__heldBodies.length),
    (n) => n === 1,
    "已实际读取但暂挂的子文档正文",
  );
  await permission("http://localhost/*");
  const parentAfter = await until(
    status,
    (s) => {
      const t = s.targets.find((t: Target) => t.browserTabId === rootId);
      return (
        t.captureGeneration > rootBefore.captureGeneration &&
        t.channels.page.state === "ACTIVE" &&
        t.channels.network.state === "ACTIVE"
      );
    },
    "撤权后父基线与网络重建",
  );
  await worker.evaluate(() => {
    for (const release of (globalThis as any).__heldBodies) release();
  });
  await child.evaluate(async () => {
    document.querySelector<HTMLInputElement>("input")!.value =
      "AFTER-CHILD-REVOKE";
    await fetch("http://127.0.0.1:4507/api/echo?id=AFTER-CHILD-REVOKE").then(
      (r) => r.text(),
    );
  });
  await act(root, "PARENT-STILL-ACTIVE");
  await act(healthy, "HEALTHY-STILL-ACTIVE");
  await until(
    bundle,
    (b) =>
      business(b).includes("PARENT-STILL-ACTIVE") &&
      business(b).includes("HEALTHY-STILL-ACTIVE"),
    "仍授权页面的后续证据",
  );
  const childSaved = await save("child-revoked");
  const childTarget = childSaved.targets.find(
    (t) => t.browserTabId === rootId,
  )!;
  check(
    ["T43"],
    "子 frame 撤权后旧统一流/正文截止，父页新基线可用",
    !business(childSaved).includes("AFTER-CHILD-REVOKE") &&
      !childSaved.blobs.some((b) => b.data.includes("BEFORE-CHILD-REVOKE")) &&
      childTarget.lateResults > 0 &&
      childTarget.documents.some((d) => d.chromeFrameId !== 0 && d.endedAt) &&
      childTarget.documents.filter((d) => d.chromeFrameId === 0).length >= 2,
    { lateResults: childTarget.lateResults, documents: childTarget.documents },
  );
  const healthyAfter = parentAfter.targets.find(
    (t: Target) => t.browserTabId === healthyId,
  );
  check(
    ["T43"],
    "无关根保留原 generation 和文档流并继续业务",
    healthyAfter.captureGeneration === healthyBefore.captureGeneration &&
      healthyAfter.documents.at(-1).recorderStreamId ===
        healthyBefore.documents.at(-1)!.recorderStreamId,
  );

  await root.reload();
  await start([rootId], "未授权导航与返回");
  const topBefore = await ready(rootId);
  await root.goto(cross + "/?id=UNAUTHORIZED-NAVIGATION");
  await until(
    status,
    (s) =>
      s.targets.find((t: Target) => t.browserTabId === rootId)?.captureState ===
      "BLOCKED",
    "未授权导航截止",
  );
  await act(root, "UNAUTHORIZED-NAVIGATION-ACTION");
  await root.goto(origin + "/?id=RETURNED");
  const returned = await ready(rootId);
  await act(root, "ROOT-RETURNED");
  await until(
    bundle,
    (b) => business(b).includes("ROOT-RETURNED"),
    "返回后的业务",
  );
  check(
    ["T37"],
    "导航到真实未授权域名后返回，保持成员并新建文档与基线",
    returned.tabInstanceId === topBefore.tabInstanceId &&
      returned.documents.at(-1)!.documentId !==
        topBefore.documents.at(-1)!.documentId &&
      !!returned.documents.at(-1)!.baselineRef &&
      !business(await bundle()).includes("UNAUTHORIZED-NAVIGATION-ACTION"),
  );
  await save("navigation-returned");

  await seededContext();
  root = await context!.newPage();
  other = await context!.newPage();
  await root.goto(origin + "/?id=ROOT-REVOKE");
  await other.goto(cross + "/?id=OTHER-REVOKE");
  rootId = await tabId(root);
  otherId = await tabId(other);
  await start([rootId, otherId], "根撤权与后台恢复");
  await ready(rootId);
  await ready(otherId);
  await permission("http://127.0.0.1/*");
  await until(
    status,
    (s) =>
      s.targets.find((t: Target) => t.browserTabId === rootId)?.captureState ===
      "BLOCKED",
    "根撤权截止",
  );
  await act(root, "AFTER-ROOT-REVOKE");
  await act(other, "OTHER-REMAINS-ACTIVE");
  await until(
    bundle,
    (b) => business(b).includes("OTHER-REMAINS-ACTIVE"),
    "其他根仍采集",
  );
  await restartWorker();
  await ready(otherId);
  const afterWake = await status();
  check(
    ["T37", "T43"],
    "根撤权后后台重启保持未授权截止，其他根可恢复",
    afterWake.targets.find((t: Target) => t.browserTabId === rootId)
      .captureState === "BLOCKED" &&
      !business(await bundle()).includes("AFTER-ROOT-REVOKE"),
  );
  await save("root-revoked");
  await start([rootId, otherId], "实际权限混合根");
  await ready(otherId);
  await until(
    status,
    (s) =>
      s.targets.find((t: Target) => t.browserTabId === rootId).captureState ===
      "BLOCKED",
    "未授权根",
  );
  await act(root, "MIXED-DENIED");
  await act(other, "MIXED-ALLOWED");
  await until(
    bundle,
    (b) => business(b).includes("MIXED-ALLOWED"),
    "混合根有效证据",
  );
  const mixed = await save("mixed-roots"),
    denied = mixed.targets.find((t) => t.browserTabId === rootId)!;
  check(
    ["T43"],
    "真实权限状态下混合 START 仅保存有效根业务",
    !business(mixed).includes("MIXED-DENIED") &&
      !mixed.chunks
        .flatMap((c) => c.events)
        .some(
          (e) =>
            e.tabInstanceId === denied.tabInstanceId && e.channel !== "control",
        ) &&
      !mixed.network.some((n) => n.tabInstanceId === denied.tabInstanceId),
  );
  await permission("http://localhost/*");
  await start([rootId, otherId], "真实权限全部失败");
  await until(
    status,
    (s) => s.recording.state === "FAILED",
    "全部失败诊断会话",
  );
  await until(
    () => ui.locator("#status-pill").textContent(),
    (t) => t === "启动失败 · 可导出",
    "失败 UI",
  );
  const failed = await save("all-failed");
  check(
    ["T43"],
    "全部未授权保存 FAILED 诊断、无业务证据且界面不虚报采集",
    failed.targets.length === 2 &&
      failed.network.length === 0 &&
      failed.chunks
        .flatMap((c) => c.events)
        .every((e) => e.channel === "control") &&
      failed.recording.gaps.some((g) => g.code === "all_channels_failed"),
  );
} catch (error) {
  await writeFile(
    resolve(output, "failure.json"),
    JSON.stringify(
      { error: String(error), status: await status().catch(() => null) },
      null,
      2,
    ),
  );
  throw error;
} finally {
  await writeAcceptance(output, extension, browserVersion, checks, {
    permissionMode:
      "原始生产 manifest；独立 profile 先预授权 fixture，撤回为真实 Chrome API；会话内原生重新授权未验证；混合/全失败从控制 RPC 启动，不计原生弹窗、F12 或用户取消",
  });
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
