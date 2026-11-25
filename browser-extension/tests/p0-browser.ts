import { collectorWorker } from './extension-worker';
import { chromium, type BrowserContext, type Page } from 'playwright';
import { mkdir, readFile, writeFile, cp, rm, mkdtemp } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
// @ts-expect-error JavaScript fixture module
import { startFixtures } from '../fixtures/server.mjs';
import { createPackage, validatePackage } from '../extension/export/package';
import { DEFAULT_POLICY } from '../shared/policy';
import type { BundleData } from '../shared/contracts';
import { unzipSync, strFromU8 } from 'fflate';
import { writeAcceptance } from './acceptance-report';

const output = resolve(process.env.MES_TEST_OUTPUT ?? `output/playwright/p0-${Date.now()}`);
await mkdir(output, { recursive: true });
const profile = await mkdtemp('/private/tmp/mes-evidence-p0-');
const extension = resolve(output, 'test-extension');
await cp(resolve('dist'), extension, { recursive: true });
const manifest = JSON.parse(await readFile(resolve(extension, 'manifest.json'), 'utf8'));
manifest.host_permissions = ['http://127.0.0.1/*', 'http://localhost/*'];
await writeFile(resolve(extension, 'manifest.json'), JSON.stringify(manifest));
const fixture = await startFixtures({ logFile: resolve(output, 'backend.ndjson') });
let context: BrowserContext | undefined; let ui: Page;
const checks: { name: string; passed: boolean }[] = [];
const check = (name: string, condition: unknown) => { checks.push({ name, passed: !!condition }); assert.ok(condition, name); console.log(`PASS ${name}`); };
async function until<T>(read: () => Promise<T>, test: (v: T) => boolean, label: string, timeout = 15000) {
  const start = Date.now(); let value: T;
  do { value = await read(); if (test(value)) return value; await new Promise(r => setTimeout(r, 100)); } while (Date.now() - start < timeout);
  throw new Error(`${label}: ${JSON.stringify(value!).slice(0, 8000)}`);
}
const rpc = (type: string, data: any = {}) => ui.evaluate(async ({ type, data }) => {
  const r = await chrome.runtime.sendMessage({ type, ...data }); if (!r?.ok) throw new Error(r.error); return r;
}, { type, data });
const status = () => rpc('session.status');
const policy = { ...structuredClone(DEFAULT_POLICY), sensitiveSelectors: ['[data-sensitive]'], pageOrigins: ['http://127.0.0.1:4317','http://localhost:4318'], apiRules: [{ origin: 'http://127.0.0.1:4317', pathPrefix: '/' }, { origin: 'http://localhost:4318', pathPrefix: '/' }], captureStreaming: true };
async function readBundle(id: string): Promise<BundleData> {
  return ui.evaluate(async id => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open('mes-evidence-v1', 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const get = (store: string, one = false) => new Promise<any>((resolve, reject) => { const s = db.transaction(store).objectStore(store); const r = one ? s.get(id) : s.index('recordingId').getAll(id); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const [recording, targets, chunks, blobs, network] = await Promise.all([get('recordings', true),get('targets'),get('chunks'),get('blobs'),get('network')]); db.close(); chunks.sort((a: any,b: any) => a.chunkSeq-b.chunkSeq); return { recording, targets, chunks, blobs, network };
  }, id);
}
let browserVersion = '';
try {
  context = await chromium.launchPersistentContext(profile, { channel: 'chromium', ...(process.env.MES_TEST_CHROME ? { executablePath: process.env.MES_TEST_CHROME } : {}), headless: process.env.HEADED !== '1' && process.env.MES_TEST_HEADLESS_NEW !== '1', args: [...(process.env.MES_TEST_HEADLESS_NEW === '1' ? ['--headless=new'] : []), `--disable-extensions-except=${extension}`, `--load-extension=${extension}`] });
  const worker = await collectorWorker(context);
  browserVersion = context.browser()!.version();
  await writeFile(resolve(output, 'runtime-environment.json'), JSON.stringify(await worker.evaluate(() => ({ url: location.href, chromeKeys: Object.keys(chrome), manifest: chrome.runtime?.getManifest() })), null, 2));
  await worker.evaluate(() => {
    (globalThis as any).__contexts = []; (globalThis as any).__calls = [];
    chrome.debugger.onEvent.addListener((source, method, p: any) => { if (method === 'Runtime.executionContextCreated' || method === 'Target.attachedToTarget') (globalThis as any).__contexts.push({ source, method, params: p }); });
    const original = chrome.debugger.sendCommand.bind(chrome.debugger);
    (chrome.debugger as any).sendCommand = (source: any, method: string, params: any) => { (globalThis as any).__calls.push({ source, method }); return original(source, method, params); };
  });
  ui = await context.newPage(); await ui.goto(`chrome-extension://${new URL(worker.url()).host}/control.html`); await ui.evaluate('globalThis.__name = fn => fn');
  const page = await context.newPage();
  await page.addInitScript(() => { (window as any).__packets = []; window.addEventListener('message', e => { if (e.data?.type === 'packet' && e.data?.channel === 'mes-evidence-v1') (window as any).__packets.push(e.data.json); }); });
  await page.goto('http://127.0.0.1:4317/?id=P0');
  const id = await ui.evaluate(async () => (await chrome.tabs.query({})).find(t => t.url?.includes('?id=P0'))!.id!);
  await ui.click('#refresh'); await ui.locator(`input[data-tab-id="${id}"]`).check(); await ui.locator('#policy-details summary').click();
  await ui.fill('#policy', JSON.stringify({ ...policy, sensitiveSelectors: ['['] })); await ui.click('#start');
  await until(() => ui.locator('#notice').textContent(), x => !!x?.includes('敏感选择器'), 'invalid selector notice');
  check('1.2 无效选择器在控制页拒绝，未创建会话', !(await status()).recording);
  await ui.fill('#policy', JSON.stringify(policy)); await ui.click('#start');
  let s = await until(status, s => s.targets?.[0]?.captureState === 'ACTIVE', 'all four channels ready');
  const rid = s.recording.recordingId;
  check('2.1/2.2 四个必要通道就绪，截图独立停用', s.targets[0].channels.semantic.state === 'ACTIVE' && s.targets[0].channels.screenshot.state === 'BLOCKED');
  await page.evaluate(() => {
    const form = document.createElement('form'); form.name = 'outer';
    form.innerHTML = '<div data-sensitive><button type="button" id="Q7v8L2n6" data-value="R6m4D8k2" aria-label="W2p9H3z7">Y9c5V8b1</button><input name="precision" value="N8j3B7r4"></div>';
    document.body.append(form); (form.querySelector('button') as HTMLButtonElement).click();
    form.dispatchEvent(new Event('submit', { bubbles: true }));
    document.querySelector<HTMLInputElement>('[name=precision]')!.value = '3.00';
  });
  // This synthetic endpoint stands in for platform traffic while the same host's MES is recorded.
  const platformMarker = 'SYNTHETIC_PLATFORM_CREDENTIAL_7B';
  await rpc('agent.exclude_origin', { origin: 'http://127.0.0.1:4317' });
  await page.route('**/api/browser-extension/auth/token', route =>
    route.fulfill({ json: { access_token: platformMarker } }));
  assert.equal(await page.evaluate(async () => (await fetch('/api/browser-extension/auth/token', {method: 'POST'})).status), 200);
  await page.click('#secret'); await page.click('#console'); await page.click('#exception'); await page.click('#stream');
  await page.evaluate(() => { const link = document.createElement('a'); link.href = '/?token=H8c2J9m6'; document.body.append(link); });
  await ui.selectOption('#mark-target', String(id)); await ui.click('#mark');
  await page.click('#frames');
  await page.evaluate(() => { const f = document.createElement('iframe'); f.title = '相同 URL'; f.src = '/frame?id=same'; document.querySelector('#frame-area')!.append(f); });
  await until(status, x => x.targets[0].documents.filter((d: any) => d.chromeFrameId !== 0 && d.baselineRef).length === 3, 'each child has baseline');
  await page.frameLocator('iframe[title="同源"]').locator('#frame-program').click();
  await page.frameLocator('iframe[title="跨源"]').locator('#frame-program').click();
  await page.frameLocator('iframe[title="相同 URL"]').locator('#frame-program').click();
  for (const frame of page.frames()) await frame.evaluate(() => fetch('/api/token').then(r => r.text()));
  await new Promise(r => setTimeout(r, 1500));
  const initial = await status();
  const initialTop = initial.targets[0].documents.find((d: any) => d.chromeFrameId === 0);
  const sameFrame = page.frames().find(f => f.url().endsWith('/frame?id=same'))!;
  await sameFrame.evaluate(() => { const f = document.createElement('iframe'); f.src = '/frame?id=nested'; document.body.append(f); });
  s = await until(status, x => x.targets[0].documents.filter((d: any) => !d.endedAt && d.baselineRef).length === 5, 'nested child baseline');
  check('3.3 嵌套同源文档由父统一流承载，无重复完整流', s.targets[0].documents.filter((d: any) => !d.endedAt && d.baselineRef).every((d: any) => d.baselineRef.recorderStreamId === initialTop.recorderStreamId));
  await page.frames().find(f => f.url().endsWith('id=nested'))!.locator('#frame-program').click();
  await page.evaluate(() => { history.pushState({}, '', '/?id=P0-route'); location.hash = '/detail'; });
  await new Promise(r => setTimeout(r, 150));
  s = await status(); check('3.4 history/hash 不更换实际文档和录制流', s.targets[0].documents.find((d: any) => d.chromeFrameId === 0 && !d.endedAt)?.recorderStreamId === initialTop.recorderStreamId);
  const beforeRemoved = s.targets[0].documents.filter((d: any) => d.endedAt).length;
  await page.locator('iframe[title="相同 URL"]').evaluate(el => el.remove());
  s = await until(status, x => x.targets[0].documents.filter((d: any) => d.endedAt).length > beforeRemoved, 'removed frame interval closed');
  check('3.3 移除子 frame 关闭旧文档区间', s.targets[0].documents.some((d: any) => d.chromeFrameId !== 0 && d.endedAt));
  await page.evaluate(() => { const f = document.createElement('iframe'); f.src = 'http://localhost:4317/frame?id=denied'; document.body.append(f); });
  const forbidden = await until(async () => page.frames().find(f => f.url().includes('id=denied')), Boolean, 'forbidden frame');
  check('3.3 未授权子文档无采集器', await forbidden!.evaluate(() => !(window as any).__mesEvidenceRecorder));
  const packetsBeforeNavigation = await page.evaluate(() => (window as any).__packets.join('\n'));
  await page.goto('http://127.0.0.1:4317/?id=P0-new-document');
  s = await until(status, x => x.targets[0].documents.some((d: any) => d.chromeFrameId === 0 && d.documentId !== initialTop.documentId && d.baselineRef), 'navigation new baseline');
  const newTop = s.targets[0].documents.find((d: any) => d.chromeFrameId === 0 && !d.endedAt);
  await new Promise(r => setTimeout(r, 200)); await page.evaluate(() => fetch('/api/token').then(r => r.text()));
  check('3.1/3.4 完整导航关闭旧映射并建立新流与基线', newTop.recorderStreamId !== initialTop.recorderStreamId && s.targets[0].documents.find((d: any) => d.documentId === initialTop.documentId).endedAt);
  await new Promise(r => setTimeout(r, 300));
  await rpc('session.stop', { recordingId: rid, commandId: crypto.randomUUID() });
  const data = await readBundle(rid); const events = data.chunks.flatMap(c => c.events); const serialized = JSON.stringify(data);
  await writeFile(resolve(output, 'bundle.json'), JSON.stringify(data));
  await writeFile(resolve(output, 'cdp-contexts.json'), JSON.stringify(await worker.evaluate(() => (globalThis as any).__contexts), null, 2));
  const secrets = ['Q7v8L2n6','R6m4D8k2','W2p9H3z7','Y9c5V8b1','N8j3B7r4','NESTED_SECRET_283','CONSOLE_OBJECT_SECRET_812'];
  const packets = packetsBeforeNavigation + await page.evaluate(() => (window as any).__packets.join('\n'));
  check('1.1 显式配置的额外敏感区域在跨桥前屏蔽（非默认策略）', secrets.slice(0,5).every(x => !packets.includes(x)));
  check('1.1/1.3 密码和显式敏感区域保护，普通令牌及业务精度保留', secrets.every(x => !serialized.includes(x)) && ['3.00','H8c2J9m6','RESPONSE_SECRET_829','CONSOLE_SECRET_917','ERROR_SECRET_229'].every(x => serialized.includes(x)));
  check('1.3 console/exception/流消息实际发生', ['browser.console','browser.exception','network.stream_message'].every(k => events.some(e => e.kind === k)));
  check('1.3 停用截图无截图读取', !(await worker.evaluate(() => (globalThis as any).__calls)).some((c: any) => /captureScreenshot|captureVisibleTab/.test(c.method)));
  const target = data.targets[0]!;
  check('3.3 所有覆盖文档引用已接受基线', target.documents.length >= 6 && target.documents.every(d => d.baselineRef && events.some(e => e.eventId === d.baselineRef!.eventId)));
  check('3.2 已知顶层及同源子文档准确映射', target.documents.filter(d => d.url.startsWith('http://127.0.0.1')).every(d => events.some(e => e.kind.startsWith('rrweb.') && (e.subjectContext?.documentId === d.documentId || e.payload.nodeContexts?.some((n: any) => n.context.documentId === d.documentId)))));
  check('3.1 同 URL 与跨源请求有独立 Chrome 文档映射', initial.targets[0].documents.every((d: any) => data.network.some(n => n.request.url.includes('/api/token') && n.chromeFrameId === d.chromeFrameId && n.documentId === d.documentId)));
  check('3.1 导航后请求不复用旧文档映射', data.network.some(n => n.documentId === newTop.documentId && n.request.url.includes('/api/token')));
  check('3.1 未确认映射保留具体原因', data.network.filter(n => n.chromeFrameId === null).every(n => !!n.frameMappingReason));
  const storedSettings = await ui.evaluate(async () => JSON.stringify(await chrome.storage.local.get(null)));
  check('平台凭据未进入录制、日志、页面消息或扩展设置', [serialized, packets, storedSettings].every(x => !x.includes(platformMarker)));
  check('平台认证请求已排除，普通业务请求仍保存', !data.network.some(n => n.request.url.includes('/api/browser-extension/')) && data.network.some(n => n.request.url.includes('/api/token')));
  const result = await createPackage(data); await writeFile(resolve(output,'evidence.zip'), result.zip);
  check('1.1/5.2 ZIP 脱敏且引用校验通过', (await validatePackage(result.zip)).valid && Object.values(unzipSync(result.zip)).every(b => secrets.every(x => !strFromU8(b).includes(x))));
  check('平台凭据未进入离线 ZIP', Object.values(unzipSync(result.zip)).every(b => !strFromU8(b).includes(platformMarker)));
  // RPC bypass of UI validation must still fail closed inside each page.
  const bad = await rpc('session.start', { recordingId: crypto.randomUUID(), commandId: crypto.randomUUID(), browserRunId: s.recording.browserRunId, rootBrowserTabIds: [id], policy: { ...policy, sensitiveSelectors: ['['] } });
  s = await until(status, x => ['LOST','BLOCKED'].includes(x.targets[0].channels.page.state), 'page rejects invalid selector');
  check('1.2 页面再次验证选择器，不报告页面就绪', s.targets[0].channels.page.state !== 'ACTIVE' && s.targets[0].channels.semantic.state !== 'ACTIVE');
  await until(() => ui.locator('#status-pill').textContent(), text => text === '部分采集', 'partial status visible');
  check('2.2 有通道失效时控制页显示部分采集', await ui.locator('#status-pill').textContent() === '部分采集');
  await rpc('session.stop', { recordingId: bad.recording.recordingId, commandId: crypto.randomUUID() });
  await until(() => ui.locator('#new').isVisible(), Boolean, 'new session button'); await ui.click('#new');
  await ui.fill('#policy', JSON.stringify(policy));
  // A deterministic denied request with an already-granted root, not native dialog acceptance.
  await ui.evaluate(() => { chrome.permissions.request = async () => false; });
  await ui.click('#start');
  s = await until(status, x => x.recording.recordingId !== bad.recording.recordingId && x.targets[0].channels.page.state === 'ACTIVE', 'existing granted root after request denied');
  check('2.3 权限请求返回 false 后已有授权根仍由正常开始入口采集', s.targets[0].browserTabId === id && s.recording.state === 'RECORDING');
  await rpc('session.stop', { recordingId: s.recording.recordingId, commandId: crypto.randomUUID() });
} finally {
  await writeAcceptance(output, extension, browserVersion, checks.map(c => ({ ...c, tIds: c.name.includes('截图') ? ['T35'] : c.name.includes('ZIP') ? ['T38','T48'] : c.name.startsWith('1.') ? ['T38'] : c.name.startsWith('2.') ? ['T36','T43'] : c.name.includes('history/hash') ? ['T23'] : c.name.includes('导航') ? ['T22','T26'] : ['T26','T29'] })), { permissionMode: 'fixture hosts 预授权；权限返回 false 为测试桩，不计原生弹窗验收' });
  await context?.close(); await fixture.close(); await rm(profile, { recursive: true, force: true });
  console.log(`Evidence: ${output}`);
}
