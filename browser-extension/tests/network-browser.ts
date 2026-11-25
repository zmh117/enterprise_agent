import { chromium, type BrowserContext, type Page } from 'playwright';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
// @ts-expect-error standalone fixture
import { startNetworkFixtures } from '../fixtures/network-server.mjs';
import { collectorWorker } from './extension-worker';
import { writeAcceptance, type AcceptanceCheck } from './acceptance-report';
import { DEFAULT_POLICY } from '../shared/policy';
import { uuid, type BundleData, type NetworkRecord } from '../shared/contracts';
import { createPackage, validatePackage } from '../extension/export/package';

const output = resolve(process.env.MES_TEST_OUTPUT ?? 'output/playwright/network-regression');
await mkdir(output, { recursive: true });
const extension = resolve(output, 'test-extension'); await cp(resolve('dist'), extension, { recursive: true });
const manifest = JSON.parse(await readFile(resolve(extension, 'manifest.json'), 'utf8'));
manifest.host_permissions = ['http://127.0.0.1/*'];
await writeFile(resolve(extension, 'manifest.json'), JSON.stringify(manifest));
const profile = await mkdtemp('/private/tmp/mes-network-regression-');
const fixture = await startNetworkFixtures();
const checks: AcceptanceCheck[] = []; let context: BrowserContext | undefined; let ui!: Page; let browserVersion = 'not_started'; let rid = '';
function check(tIds: string[], name: string, condition: unknown, detail?: unknown) {
  checks.push({ tIds, name, passed: !!condition, detail }); assert.ok(condition, `${name}: ${JSON.stringify(detail)}`); console.log(`PASS ${name}`);
}
const rpc = (type: string, data: any = {}) => ui.evaluate(async ({ type, data }) => {
  const r = await chrome.runtime.sendMessage({ type, ...data }); if (!r?.ok) throw Error(r?.error); return r;
}, { type, data });
async function until<T>(read: () => Promise<T>, predicate: (v: T) => unknown, label: string, timeout = 20000) {
  const start = Date.now(); let last: T;
  do { last = await read(); if (predicate(last)) return last; await new Promise(r => setTimeout(r, 100)); } while (Date.now() - start < timeout);
  throw Error(`等待超时 ${label}: ${JSON.stringify(last!).slice(0, 2000)}`);
}
async function bundle(): Promise<BundleData> {
  return ui.evaluate(async id => {
    const db = await new Promise<IDBDatabase>((r, j) => { const q = indexedDB.open('mes-evidence-v1'); q.onsuccess = () => r(q.result); q.onerror = () => j(q.error); });
    const get = (name: string, one = false) => new Promise<any>((r, j) => {
      const store = db.transaction(name).objectStore(name), q = one ? store.get(id) : store.index('recordingId').getAll(id);
      q.onsuccess = () => r(q.result); q.onerror = () => j(q.error);
    });
    const [recording, targets, chunks, blobs, network] = await Promise.all([get('recordings', true), get('targets'), get('chunks'), get('blobs'), get('network')]);
    db.close(); chunks.sort((a: any, b: any) => a.chunkSeq - b.chunkSeq); return { recording, targets, chunks, blobs, network };
  }, rid);
}
async function start(page: Page, bodyBytes: number) {
  rid = uuid(); const scope = await rpc('scope.list');
  const tab = await ui.evaluate(async url => (await chrome.tabs.query({})).find(t => t.url === url)?.id, page.url());
  const policy = { ...structuredClone(DEFAULT_POLICY), pageOrigins: ['http://127.0.0.1:4517'], apiRules: [{ origin: 'http://127.0.0.1:4517', pathPrefix: '/' }], budgets: { ...DEFAULT_POLICY.budgets, bodyBytes } };
  await rpc('session.start', { recordingId: rid, commandId: uuid(), browserRunId: scope.browserRunId, rootBrowserTabIds: [tab], title: '真实录制网络回归', environmentId: 'LOCAL-NETWORK', policy });
  await until(() => rpc('session.status'), s => s.recording?.recordingId === rid && s.targets.length === 1 && s.targets.every((t: any) => t.channels.page.state === 'ACTIVE' && t.channels.network.state === 'ACTIVE'), '采集就绪');
}
async function save(name: string) {
  await rpc('session.stop', { recordingId: rid, commandId: uuid() }); await until(() => rpc('session.status'), s => s.recording.state === 'READY', '保存');
  const b = await bundle(); const p = await createPackage(b); const validation = await validatePackage(p.zip);
  await writeFile(resolve(output, `${name}.zip`), p.zip); await writeFile(resolve(output, `${name}.json`), JSON.stringify(b));
  await writeFile(resolve(output, `${name}-validation.json`), JSON.stringify(validation, null, 2));
  check(['T48'], `${name} 导出包结构、散列及引用通过`, true, validation); return b;
}
function find(b: BundleData, path: string): NetworkRecord { const record = b.network.find(n => new URL(n.request.url).pathname === path); assert.ok(record, `缺少请求 ${path}`); return record; }

try {
  context = await chromium.launchPersistentContext(profile, { channel: 'chromium', ...(process.env.MES_TEST_CHROME ? { executablePath: process.env.MES_TEST_CHROME } : {}), headless: process.env.HEADED !== '1', args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`] });
  context.on('console', message => { if (message.text().includes('MES collector:')) console.log(message.text()); });
  browserVersion = context.browser()!.version(); const worker = await collectorWorker(context);
  ui = await context.newPage(); await ui.goto(`chrome-extension://${new URL(worker.url()).host}/control.html`); await ui.evaluate('globalThis.__name=fn=>fn');
  const page = await context.newPage(); await page.goto('http://127.0.0.1:4517/page'); await page.evaluate('globalThis.__name=fn=>fn');
  // SW is business-page behavior; no debugger attachment to shared worker internals.
  await page.evaluate(async () => { await navigator.serviceWorker.register('/network-sw.js'); await navigator.serviceWorker.ready; });
  await page.reload(); await page.evaluate('globalThis.__name=fn=>fn'); await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  await start(page, 1024 * 1024);
  await page.fill('input[name=ordinary]', 'UPDATED_INPUT_SENTINEL');
  await page.fill('#loginPassword', 'LOGIN_CHANGED_PASSWORD_SENTINEL');
  await page.evaluate(() => { const input = document.querySelector<HTMLInputElement>('#loginPassword')!; input.type = 'text'; input.setAttribute('value', 'LOGIN_ATTRIBUTE_PASSWORD_SENTINEL'); });
  await page.evaluate(async () => {
    await fetch('/api/post?token=QUERY_TOKEN_SENTINEL', { method: 'POST', headers: { Authorization: 'Bearer AUTH_TOKEN_SENTINEL' }, body: JSON.stringify([{ precision: '3.00', token: 'POST_PRIVATE_SENTINEL', password: 'POST_PASSWORD_SENTINEL' }]) }).then(r => r.text());
    await fetch('/api/sw-json').then(r => r.text());
    await fetch('/api/sw-redirect').then(r => r.text());
    await fetch('/api/gzip').then(r => r.text());
    for (const [id, src] of [['allowed', '/frame'], ['denied-same-process', 'http://127.0.0.1:4518/denied'], ['denied-oopif', 'http://localhost:4518/denied']]) { const frame = document.createElement('iframe'); frame.id = id!; frame.src = src!; document.body.append(frame); }
  });
  await until(async () => fixture.requests, rows => rows.filter((r: any) => r.path === '/api/denied-post').length === 2 && rows.some((r: any) => r.path === '/api/frame-first'), 'frame 请求实际到达服务端');
  await until(bundle, b => b.network.some(n => new URL(n.request.url).pathname === '/api/frame-first' && n.response.bodyCaptureStatus === 'captured') && b.network.some(n => new URL(n.request.url).pathname === '/api/gzip' && n.networkOutcome === 'finished'), '正文落盘');
  const b = await save('default-budget');
  const post = find(b, '/api/post'); const attachments = b.blobs.filter(blob => [post.request.bodyRef, post.response.bodyRef].includes(blob.path));
  check(['T32', 'T38'], 'text/plain JSON POST 双侧保留令牌、精度，仅掩码密码', post.request.bodyCaptureStatus === 'captured' && post.response.bodyCaptureStatus === 'captured' && attachments.length === 2 && attachments.every(blob => blob.mime === 'application/json' && blob.path.endsWith('.json') && String(blob.data).includes('3.00') && String(blob.data).includes('POST_PRIVATE_SENTINEL') && !String(blob.data).includes('POST_PASSWORD_SENTINEL')));
  const sw = find(b, '/api/sw-json'); check(['T30'], 'Service Worker 响应没有 ExtraInfo，停止后仍为 not_expected', sw.response.fromServiceWorker && sw.extraInfoStatus === 'not_expected', sw.extraInfoStatus);
  const redirect = find(b, '/api/sw-redirect'); const final = find(b, '/api/final');
  check(['T30'], 'SW 到网络重定向逐跳标志及额外头正确', redirect.cdpRequestId === final.cdpRequestId && redirect.redirectOrdinal === 0 && final.redirectOrdinal === 1 && redirect.extraInfoStatus === 'not_expected' && final.extraInfoStatus === 'matched_by_protocol_order' && final.response.headers['x-hop'] === 'network', { first: redirect.extraInfoStatus, last: final.extraInfoStatus });
  const large = find(b, '/api/gzip'); check(['T32'], 'gzip 传输虽小但解码后超限，明确排除并记录字节', large.response.bodyCaptureReason === 'decoded_body_size_limit' && large.response.originalBytes === fixture.decodedBytes && large.response.bodyRef === null, { encodedBytes: fixture.encodedBytes, decodedBytes: large.response.originalBytes });
  const frame = find(b, '/frame'), frameRequest = find(b, '/api/frame-first');
  check(['T26'], '新同源 iframe 首次 Document 及脚本请求均采集，导航不借用旧文档', frame.request.type === 'Document' && frame.cdpFrameId === frameRequest.cdpFrameId && frame.documentId === null && frameRequest.response.bodyCaptureStatus === 'captured');
  check(['T26', 'T38'], '未授权同进程和 OOPIF 请求实际执行但业务正文不入包', fixture.requests.filter((r: any) => r.path === '/api/denied-post').length === 2 && !b.network.some(n => n.request.url.includes('/api/denied-post')) && b.recording.gaps.some(g => g.code === 'network_frame_not_authorized') && b.recording.gaps.some(g => g.code === 'child_target_policy_excluded'));
  check(['T38'], '普通文本、输入、DOM 属性、URL 和认证头原样保留，密码输入和显示密码仍保护', ['PLAIN_INPUT_SENTINEL', 'UPDATED_INPUT_SENTINEL', 'PLAIN_TEXT_SENTINEL', 'DOM_TOKEN_SENTINEL', 'QUERY_TOKEN_SENTINEL', 'AUTH_TOKEN_SENTINEL', 'SW_PRIVATE_SENTINEL'].every(value => JSON.stringify(b).includes(value)) && ['LOGIN_PASSWORD_SENTINEL', 'LOGIN_CHANGED_PASSWORD_SENTINEL', 'LOGIN_ATTRIBUTE_PASSWORD_SENTINEL', 'DENIED_PRIVATE_SENTINEL'].every(value => !JSON.stringify(b).includes(value)));
  const count = b.network.length;
  await page.evaluate(async () => { await fetch('/api/after-stop').then(r => r.text()); });
  await new Promise(r => setTimeout(r, 400)); check(['T18', 'T20'], 'STOP 后业务请求继续但证据数量不增长', (await bundle()).network.length === count);
  await start(page, 2 * 1024 * 1024);
  await page.evaluate(async () => { await fetch('/api/gzip').then(r => r.text()); });
  await until(bundle, b => b.network.some(n => n.networkOutcome === 'finished' && n.response.bodyCaptureReason !== 'not_received' && n.request.url.includes('/api/gzip')), '2 MiB 配置正文');
  const b2 = await save('configured-budget'); const large2 = find(b2, '/api/gzip');
  check(['T32', 'T38'], '显式 2 MiB 预算保存同一大响应，令牌保留且密码仍保护', large2.response.bodyCaptureStatus === 'captured' && large2.response.originalBytes === fixture.decodedBytes && JSON.stringify(b2).includes('GZIP_PRIVATE_SENTINEL') && !JSON.stringify(b2).includes('GZIP_PASSWORD_SENTINEL'), { originalBytes: large2.response.originalBytes, savedBytes: large2.response.savedBytes });
} finally {
  if (ui && rid) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const observation = await Promise.race([
        Promise.all([rpc('session.status'), bundle()]).then(([status, bundle]) => ({ status, bundle })),
        new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(Error('后台诊断读取超时')), 3000); }),
      ]);
      await writeFile(resolve(output, 'last-observation.json'), JSON.stringify(observation));
    } catch (error) { await writeFile(resolve(output, 'last-observation-error.txt'), String(error)); }
    finally { clearTimeout(timer); }
  }
  await writeAcceptance(output, extension, browserVersion, checks, { fixture: { encodedBytes: fixture.encodedBytes, decodedBytes: fixture.decodedBytes }, permissionMode: '复制构建，仅 127.0.0.1 fixture host 预授权；localhost frame 未授权；非原生权限弹窗验收' });
  await writeFile(resolve(output, 'fixture-requests.json'), JSON.stringify(fixture.requests, null, 2));
  await context?.close(); await fixture.close(); await rm(profile, { recursive: true, force: true });
}
