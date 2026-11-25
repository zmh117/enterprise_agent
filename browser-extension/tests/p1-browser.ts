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

const output = resolve(process.env.MES_TEST_OUTPUT ?? `output/playwright/p1-${Date.now()}`);
await mkdir(output, { recursive: true });
const profile = await mkdtemp('/private/tmp/mes-evidence-p1-');
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
const policy = { ...structuredClone(DEFAULT_POLICY), pageOrigins: ['http://127.0.0.1:4317','http://localhost:4318'], apiRules: [{ origin: 'http://127.0.0.1:4317', pathPrefix: '/' }, { origin: 'http://localhost:4318', pathPrefix: '/' }], captureStreaming: true, correlationSources: [...DEFAULT_POLICY.correlationSources, { field: 'frontendBuildId' as const, source: 'page_meta' as const, key: 'meta[name="app-build"]', component: 'frontend' }, { field: 'backendBuildId' as const, source: 'response_header' as const, key: 'x-deploy', component: 'api' }, { field: 'requestId' as const, source: 'response_header' as const, key: 'x-log-id', component: 'api' }, { field: 'backendBuildId' as const, source: 'response_json' as const, key: '/metadata/build', component: 'api' }, { field: 'requestId' as const, source: 'response_json' as const, key: '/metadata/requestId', component: 'api' }], sourceMappings: [{ environmentId: 'fixture', component: 'api', buildId: 'v1', codeSnapshot: 'fixture@v1' }] };
async function readBundle(id: string): Promise<BundleData> {
  return ui.evaluate(async id => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open('mes-evidence-v1', 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const get = (store: string, one = false) => new Promise<any>((resolve, reject) => { const s = db.transaction(store).objectStore(store); const r = one ? s.get(id) : s.index('recordingId').getAll(id); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const [recording, targets, chunks, blobs, network] = await Promise.all([get('recordings', true),get('targets'),get('chunks'),get('blobs'),get('network')]); db.close(); chunks.sort((a: any,b: any) => a.chunkSeq-b.chunkSeq); return { recording, targets, chunks, blobs, network };
  }, id);
}
let browserVersion = '';
try {
  context = await chromium.launchPersistentContext(profile, { channel: 'chromium', ...(process.env.MES_TEST_CHROME ? { executablePath: process.env.MES_TEST_CHROME } : {}), headless: true, args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`] });
  const worker = await collectorWorker(context);
  browserVersion = context.browser()!.version();
  ui = await context.newPage(); await ui.goto(`chrome-extension://${new URL(worker.url()).host}/control.html`); await ui.evaluate('globalThis.__name = fn => fn');
  const page = await context.newPage();
  await page.addInitScript(() => {
    (window as any).__originalSetters = [HTMLInputElement, HTMLSelectElement].map(c => Object.getOwnPropertyDescriptor(c.prototype, 'value')!.set);
    (window as any).__packets = []; window.addEventListener('message', e => { if (e.data?.type === 'packet') (window as any).__packets.push(e.data.json); });
  });
  await page.goto('http://127.0.0.1:4317/?id=P1');
  await page.evaluate(() => {
    const meta=document.createElement('meta');meta.name='app-build';meta.content='frontend-meta-v1';document.head.append(meta);
    document.body.innerHTML = `<form name="relevant"><input name="precision" value="3.00"><input name="quantity" type="checkbox"><select name="version"><option>A</option><option>B</option></select><button type="button" id="go">操作</button><div role="alert" id="notice"></div></form><form name="unrelated"><input name="workOrderId" value="UNRELATED_VALUE"></form><dialog id="native">原生</dialog><div hidden id="wrapper"><div role="dialog" id="role">角色</div></div>`;
  });
  const id = await ui.evaluate(async () => (await chrome.tabs.query({})).find(t => t.url?.includes('?id=P1'))!.id!);
  const initial = await rpc('session.start', { recordingId: crypto.randomUUID(), commandId: crypto.randomUUID(), browserRunId: (await rpc('scope.list')).browserRunId, rootBrowserTabIds: [id], environmentId: 'fixture', policy });
  const rid = initial.recording.recordingId;
  await until(status, s => s.targets?.[0]?.captureState === 'ACTIVE', 'channels ready');
  await page.evaluate(() => {
    // A new button is deliberately unobserved before its first action.
    const fresh = document.createElement('button'); fresh.id = 'first'; fresh.type = 'button'; fresh.textContent = '首次'; document.querySelector('form')!.append(fresh); fresh.click();
    const field = document.querySelector<HTMLInputElement>('[name=precision]')!; field.value = '4.00'; field.value = '5.00';
    document.querySelector<HTMLInputElement>('[name=quantity]')!.checked = true;
    document.querySelector<HTMLSelectElement>('[name=version]')!.selectedIndex = 1;
    const button = document.querySelector<HTMLButtonElement>('#go')!; button.click(); button.disabled = true; button.setAttribute('aria-busy', 'true');
    field.required = true; field.value = ''; field.checkValidity();
    setTimeout(() => { document.querySelector('#notice')!.textContent = '异步提示'; }, 100);
    document.querySelector<HTMLDialogElement>('#native')!.showModal();
    document.querySelector<HTMLElement>('#wrapper')!.hidden = false;
  });
  await page.waitForTimeout(250);
  await page.evaluate(() => { document.querySelector<HTMLDialogElement>('#native')!.close(); document.querySelector<HTMLElement>('#wrapper')!.hidden = true; });
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    const form = document.querySelector('form')!;
    for (let i=0;i<180;i++) { const f=document.createElement('input');f.name='batchId';f.value='B'+i;form.append(f); }
    const button=document.querySelector<HTMLButtonElement>('#go')!;button.disabled=false;
    for(let i=0;i<30;i++)button.setAttribute('data-field'+i,'value');
    document.querySelector('#notice')!.textContent='长'.repeat(6000);
    button.click();
  });
  await rpc('session.mark', { recordingId: rid, commandId: crypto.randomUUID(), browserTabId: id, note: 'P1 语义预算标记' });
  await page.waitForTimeout(300);
  await page.evaluate(async()=>{await fetch('/api/correlation?version=v1').then(r=>r.text());await fetch('/api/correlation?version=v2').then(r=>r.text());console.error('P1 same observable error');setTimeout(()=>{throw new Error('P1 same observable error');},0);});
  await page.waitForTimeout(500);
  await worker.evaluate(()=>{
    const original=IDBDatabase.prototype.transaction;let delayed=false;
    const descriptor=Object.getOwnPropertyDescriptor(IDBTransaction.prototype,'oncomplete')!;
    IDBDatabase.prototype.transaction=function(...args:any[]){const tx=(original as any).apply(this,args);if(!delayed&&args[1]==='readwrite'){delayed=true;Object.defineProperty(tx,'oncomplete',{configurable:true,set(handler){descriptor.set!.call(tx,(event:Event)=>setTimeout(()=>handler.call(tx,event),6500));}});}return tx;};
  });
  const stopping=rpc('session.stop', { recordingId: rid, commandId: crypto.randomUUID() });
  await until(()=>ui.locator('#session-message').textContent(),v=>!!v?.includes('超过 5 秒'),'slow stop UI',10000);
  const during=await status();
  check('6.2 慢写超过 5 秒时 UI 显示排空未完成、采集已截止', during.recording.stopProgress.drain==='pending'&&during.recording.stopProgress.cutoff==='complete'&&during.targets.every((t:any)=>!t.accepting)&&await ui.locator('#status-pill').textContent()==='已停止 · 保存未完成');
  await stopping;
  check('6.2 原事务确认后才显示保存成功', (await status()).recording.saveState==='saved');

  const data = await readBundle(rid); const events = data.chunks.flatMap(c=>c.events); const states=events.filter(e=>e.kind==='ui.state_snapshot');
  await writeFile(resolve(output,'bundle.json'),JSON.stringify(data));
  const find=(id:string, action:string)=>states.filter(e=>e.payload.target?.id===id&&e.payload.action===action);
  check('4.1 首次动作 before unavailable', find('first','click')[0]?.payload.before.status==='unavailable');
  check('4.1 动作上下文只读相关区域', find('go','click').every(e=>!JSON.stringify(e.payload.context).includes('UNRELATED_VALUE')));
  const changes=states.filter(e=>e.payload.action==='programmatic_change'&&e.payload.target?.name==='precision');
  check('4.1 重复赋值引用此前已保存快照和观察时间', ['4.00','5.00'].every(v=>changes.some(e=>e.payload.after.value.value===v&&events.some(p=>p.eventId===e.payload.before.snapshotRef&&p.sourceSeq<e.sourceSeq&&p.payload.observation.sourceTime===e.payload.before.sourceTime))));
  check('4.1 异步提示另记真实观察时间', find('notice','notice_change').some(e=>e.payload.after.text==='异步提示'&&e.payload.phase==='mutation_observation'));
  check('4.2 原生弹框明确打开及关闭', find('native','dialog_open').some(e=>e.payload.after.open===true)&&find('native','dialog_close').some(e=>e.payload.after.open===false));
  check('4.2 角色弹框祖先显隐被观察', find('role','dialog_open').some(e=>e.payload.after.visible)&&find('role','dialog_close').some(e=>!e.payload.after.visible));
  check('4.2 disabled/loading 与原生校验提示', find('go','state_change').some(e=>e.payload.after.disabled&&e.payload.after.loading==='true')&&states.some(e=>e.payload.action==='invalid'&&e.payload.after.validationMessage));
  check('4.2 无 input/change 的 checked/selectedIndex', states.some(e=>e.payload.action==='programmatic_change'&&e.payload.target?.name==='quantity'&&e.payload.after.checked.value===true)&&states.some(e=>e.payload.action==='programmatic_change'&&e.payload.target?.name==='version'&&e.payload.after.selectedIndex===1));
  check('4.3 字段/属性/文本超限带计数和 quality', ['region_fields','target_attributes','text_or_dom_nodes','snapshot_fields'].every(scope=>states.some(e=>e.quality.truncated&&e.payload.omissions.some((o:any)=>o.scope===scope&&o.count>0))));
  check('4.3 合法业务精度 3.00 保留', states.some(e=>e.payload.after.value?.value==='3.00'));
  check('4.2 STOP 恢复属性包装', await page.evaluate(()=>[HTMLInputElement,HTMLSelectElement].every((c,i)=>Object.getOwnPropertyDescriptor(c.prototype,'value')!.set===(window as any).__originalSetters[i])));
  const count=await page.evaluate(()=>(window as any).__packets.length);
  await page.evaluate(()=>{document.querySelector<HTMLInputElement>('[name=precision]')!.value='AFTER_STOP';document.querySelector('#notice')!.textContent='AFTER_STOP';});await page.waitForTimeout(150);
  check('4.2 STOP 后观察器与桥不再发包', count===await page.evaluate(()=>(window as any).__packets.length));
  const result=await createPackage(data);await writeFile(resolve(output,'evidence.zip'),result.zip);await writeFile(resolve(output,'bundle.json'),JSON.stringify(data));
  check('5.3 页面元数据/自定义头/已观察 JSON 字段均有来源', states.some(e=>e.payload.action==='build_metadata'&&e.payload.after.metadataFacts.some((f:any)=>f.value==='frontend-meta-v1'))&&data.network.filter(n=>n.request.url.includes('/api/correlation')).every(n=>n.correlationFacts?.some(f=>f.source==='response_header:x-deploy')&&n.correlationFacts?.some(f=>f.source==='response_json:/metadata/build')&&n.serverCorrelation.requestId));
  check('5.3 混合版本保留全部观测且未配置业务协议为 unknown', data.recording.versions.backendBuildId==='mixed_deployment'&&['v1','v2'].every(v=>data.network.some(n=>n.correlationFacts?.some(f=>f.value===v)))&&data.network.every(n=>n.businessOutcome==='unknown'));
  check('4.1 动作/快照/before 引用闭包通过', (await validatePackage(result.zip)).valid);
  // Real root + OOPIF + dedicated-worker sessions, with deliberately slow body commands.
  await page.goto('http://127.0.0.1:4317/frame?id=queue');
  await page.evaluate(()=>{const f=document.createElement('iframe');f.src='http://localhost:4318/frame?id=queue-child';document.body.append(f);});
  await until(async()=>page.frames().some(f=>f.url().includes('queue-child')),Boolean,'OOPIF loaded');
  await worker.evaluate(()=>{
    const original=chrome.debugger.sendCommand.bind(chrome.debugger);(globalThis as any).__bodyProbe={running:0,peak:0,calls:[]};
    (chrome.debugger as any).sendCommand=async(s:any,m:string,p:any)=>{if(m!=='Network.getResponseBody')return original(s,m,p);const probe=(globalThis as any).__bodyProbe;probe.peak=Math.max(probe.peak,++probe.running);probe.calls.push(s.sessionId??'root');try{await new Promise(r=>setTimeout(r,200));return await original(s,m,p);}finally{probe.running--;}};
  });
  const second=await rpc('session.start',{recordingId:crypto.randomUUID(),commandId:crypto.randomUUID(),browserRunId:(await rpc('scope.list')).browserRunId,rootBrowserTabIds:[id],policy});
  await until(status,s=>s.readyTargets===1&&s.targets[0].documents.filter((d:any)=>d.baselineRef).length===2,'queue baselines');
  await page.evaluate(()=>{(window as any).__worker=new Worker('/worker.js');});await page.waitForTimeout(700);
  await Promise.all(page.frames().map(f=>f.evaluate(()=>{for(let i=0;i<5;i++)void fetch('/api/token').then(r=>r.text());})));
  await page.evaluate(()=>{for(let i=0;i<5;i++)(window as any).__worker.postMessage('go');});
  await until(async()=>worker.evaluate(()=>(globalThis as any).__bodyProbe),p=>p.calls.length>=15&&p.running===0,'body queue drained');
  const probe=await worker.evaluate(()=>(globalThis as any).__bodyProbe);const queueStatus=await status();
  check('6.1 真实 root/OOPIF/worker 至少三 session 共享总并发 2', new Set(probe.calls).size>=3&&probe.peak===2&&queueStatus.resources.bodyQueues[0].peakRunning===2);
  await rpc('session.stop',{recordingId:second.recording.recordingId,commandId:crypto.randomUUID()});
  const queueData=await readBundle(second.recording.recordingId);
  check('5.4 worker 错误缺少文档映射时以 unknown 保留原始观测',queueData.chunks.flatMap(c=>c.events).some(e=>e.kind==='browser.console'&&e.payload.documentContext===null&&JSON.stringify(e.payload.args).includes('dedicated worker diagnostic')));
  const queued=await createPackage(queueData);await writeFile(resolve(output,'body-queue.zip'),queued.zip);
  check('6.1 多 session 证据与正文引用完整导出',(await validatePackage(queued.zip)).valid);
  const third=await rpc('session.start',{recordingId:crypto.randomUUID(),commandId:crypto.randomUUID(),browserRunId:(await rpc('scope.list')).browserRunId,rootBrowserTabIds:[id],policy});
  await until(status,s=>s.readyTargets===1,'quota session ready');await page.waitForTimeout(1500);
  const failWrites=()=>{(globalThis as any).__originalPut=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(){throw new DOMException('injected quota failure','QuotaExceededError');};};
  await worker.evaluate(failWrites);await ui.evaluate(failWrites);
  await page.evaluate(()=>{document.querySelector<HTMLInputElement>('input')!.value='QUOTA_UNCOMMITTED';});
  await until(status,s=>s.recording.saveState==='error','quota failure visible');
  await until(()=>ui.locator('#export').textContent(),s=>s==='导出已保存部分','saved-prefix button');
  const downloaded=ui.waitForEvent('download');await ui.click('#export');const download=await downloaded;await download.saveAs(resolve(output,'saved-prefix.zip'));
  const prefixValidation=await validatePackage(new Uint8Array(await readFile(resolve(output,'saved-prefix.zip'))));
  const prefixFiles=unzipSync(new Uint8Array(await readFile(resolve(output,'saved-prefix.zip'))));const prefixManifest=JSON.parse(strFromU8(prefixFiles['manifest.json']!));
  check('6.3 持续配额失败时按钮可下载已提交部分，包明确缺口且不含未提交批次',prefixValidation.valid&&prefixManifest.recording.state==='INTERRUPTED'&&prefixManifest.gaps.some((g:any)=>g.code==='saved_prefix_only')&&!Object.values(prefixFiles).some(b=>strFromU8(b).includes('QUOTA_UNCOMMITTED')));
  await worker.evaluate(()=>{IDBObjectStore.prototype.put=(globalThis as any).__originalPut;});await ui.evaluate(()=>{IDBObjectStore.prototype.put=(globalThis as any).__originalPut;});
  await rpc('storage.retry');const retried=await readBundle(third.recording.recordingId);const retriedPackage=await createPackage(retried);await writeFile(resolve(output,'retried.zip'),retriedPackage.zip);
  check('6.3 释放配额后重试保留原失败批次且完成终结保存',retried.recording.state==='READY'&&JSON.stringify(retried).includes('QUOTA_UNCOMMITTED')&&(await validatePackage(retriedPackage.zip)).valid);
  const fourth=await rpc('session.start',{recordingId:crypto.randomUUID(),commandId:crypto.randomUUID(),browserRunId:(await rpc('scope.list')).browserRunId,rootBrowserTabIds:[id],policy});
  await until(status,s=>s.readyTargets===1,'interrupt session ready');await page.waitForTimeout(1500);
  const cdp=await context.newCDPSession(ui);const versions:any[]=[];cdp.on('ServiceWorker.workerVersionUpdated',(event:any)=>versions.push(...event.versions));await cdp.send('ServiceWorker.enable');
  await until(async()=>versions,v=>v.some(x=>x.scriptURL===worker.url()),'worker version before STOP');
  await worker.evaluate('globalThis.__name = fn => fn');
  await worker.evaluate(()=>{
    const original=IDBDatabase.prototype.transaction;let held=false;
    IDBDatabase.prototype.transaction=function(...args:any[]){const tx=(original as any).apply(this,args);if(!held&&args[1]==='readwrite'){held=true;const store=tx.objectStore('recordings');const pump=()=>{try{const request=store.get('__test_keep_transaction_alive__');request.onsuccess=pump;}catch{}};pump();}return tx;};
  });
  const interruptedStop=rpc('session.stop',{recordingId:fourth.recording.recordingId,commandId:crypto.randomUUID()}).catch(e=>String(e));
  await until(status,s=>s.recording.stopProgress?.marker==='complete'&&s.recording.stopProgress.drain==='pending','durable intent before worker termination');
  await cdp.send('ServiceWorker.stopWorker',{versionId:versions.filter(x=>x.scriptURL===worker.url()).at(-1).versionId});
  const recovered=await until(status,s=>s.recording?.recordingId===fourth.recording.recordingId&&s.recording.state==='READY','stopping worker recovery',20000);
  check('6.3 未提交写事务挂起后真实停止 worker，持久化 STOP 意图阻止恢复采集',recovered.targets.every((t:any)=>!t.accepting)&&recovered.recording.gaps.some((g:any)=>g.code==='interrupted_finalization'));
  const recoveredData=await readBundle(fourth.recording.recordingId);const interruptedPackage=await createPackage(recoveredData);await writeFile(resolve(output,'interrupted-stop.zip'),interruptedPackage.zip);
  check('6.3 停止整理中断后既有数据可导出且缺口明确',(await validatePackage(interruptedPackage.zip)).valid);
  await cdp.detach();await interruptedStop;
} finally {
  await writeAcceptance(output, extension, browserVersion, checks.map(c => ({ ...c, tIds: c.name.startsWith('6.3') ? ['T19','T40','T41','T48'] : c.name.startsWith('6.2') ? ['T19','T20'] : c.name.startsWith('6.1') ? ['T44','T48'] : c.name.startsWith('5.3') ? ['T47'] : c.name.startsWith('5.4') ? ['T44'] : c.name.includes('STOP') ? ['T20'] : c.name.includes('引用闭包') ? ['T48'] : ['T27','T28'] })));
  await context?.close(); await fixture.close(); await rm(profile, { recursive: true, force: true });
  console.log(`Evidence: ${output}`);
}
