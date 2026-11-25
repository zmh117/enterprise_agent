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

const output = resolve(process.env.MES_TEST_OUTPUT ?? `output/playwright/capacity-${Date.now()}`);
await mkdir(output, { recursive: true });
const profile = await mkdtemp('/private/tmp/mes-evidence-capacity-');
const extension = resolve(output, 'test-extension');
await cp(resolve('dist'), extension, { recursive: true });
const manifest = JSON.parse(await readFile(resolve(extension, 'manifest.json'), 'utf8'));
manifest.host_permissions = ['http://127.0.0.1/*', 'http://localhost/*'];
await writeFile(resolve(extension, 'manifest.json'), JSON.stringify(manifest));
const fixture = await startFixtures({ port: 4417, crossPort: 4418, logFile: resolve(output, 'backend.ndjson') });
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
const policy = { ...structuredClone(DEFAULT_POLICY), pageOrigins: ['http://127.0.0.1:4417','http://localhost:4418'], apiRules: [{ origin: 'http://127.0.0.1:4417', pathPrefix: '/' }, { origin: 'http://localhost:4418', pathPrefix: '/' }], captureStreaming: true };
async function readBundle(id: string): Promise<BundleData> {
  return ui.evaluate(async id => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => { const r = indexedDB.open('mes-evidence-v1', 1); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const get = (store: string, one = false) => new Promise<any>((resolve, reject) => { const s = db.transaction(store).objectStore(store); const r = one ? s.get(id) : s.index('recordingId').getAll(id); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const [recording, targets, chunks, blobs, network] = await Promise.all([get('recordings', true),get('targets'),get('chunks'),get('blobs'),get('network')]); db.close(); chunks.sort((a: any,b: any) => a.chunkSeq-b.chunkSeq); return { recording, targets, chunks, blobs, network };
  }, id);
}
let browserVersion = '';
try {
  context = await chromium.launchPersistentContext(profile, { channel: 'chromium', ...(process.env.MES_TEST_CHROME ? { executablePath: process.env.MES_TEST_CHROME } : {}), headless: true, ignoreDefaultArgs: ['--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows'], args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`] });
  const worker = await collectorWorker(context); browserVersion = context.browser()!.version();
  ui = await context.newPage(); await ui.goto(`chrome-extension://${new URL(worker.url()).host}/control.html`); await ui.evaluate('globalThis.__name = fn => fn');
  const os = await import('node:os'); const { execFileSync } = await import('node:child_process'); const { appendFile } = await import('node:fs/promises');
  await writeFile(resolve(output,'environment.json'),JSON.stringify({startedAt:new Date().toISOString(),browserVersion,cpus:os.cpus(),totalMemory:os.totalmem(),platform:os.platform(),release:os.release(),arch:os.arch(),build:JSON.parse(await readFile('dist/build-info.json','utf8')),policy,permissionMode:'fixture pregranted;headless;independent profile',load:'每 15 秒由测试驱动对每页程序赋值并请求 1 次 /api/token；每页采样 100ms 定时延迟；未禁用后台节流',metricLayers:'Chrome 本任务进程树 CPU/RSS 求和（RSS 可能重复统计共享页）；页面 performance.memory；Node 导出进程 memoryUsage；扩展显式队列计数'},null,2));
  const processMetrics=()=>{
    const rows=execFileSync('/bin/ps',['-axo','pid=,ppid=,%cpu=,rss=,command='],{encoding:'utf8'}).trim().split('\n').map(line=>{const m=line.trim().match(/^(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(.+)$/)!;return m?{pid:+m[1]!,ppid:+m[2]!,cpu:+m[3]!,rssKiB:+m[4]!,command:m[5]!}:null;}).filter(Boolean) as any[];
    const owned=new Set(rows.filter(r=>r.command.includes('--user-data-dir='+profile)).map(r=>r.pid));for(let i=0;i<5;i++)for(const r of rows)if(owned.has(r.ppid))owned.add(r.pid);
    const selected=rows.filter(r=>owned.has(r.pid));return {processes:selected.length,cpuPercentSum:selected.reduce((n,r)=>n+r.cpu,0),rssKiBSum:selected.reduce((n,r)=>n+r.rssKiB,0),node:process.memoryUsage()};
  };
  for(const [count,durationSeconds] of [[1,60],[10,120],[30,1800]]) {
    const pages:Page[]=[];
    for(let i=0;i<count!;i++) {
      const p=await context.newPage();await p.goto(`http://127.0.0.1:4417/frame?id=capacity-${count}-${i}`);await p.evaluate(()=>{
        (window as any).__perf={ticks:0,maxDelayMs:0,totalDelayMs:0,longTasks:0,longTaskMs:0};
        let previous=performance.now();setInterval(()=>{const n=performance.now(),d=Math.max(0,n-previous-100);previous=n;const s=(window as any).__perf;s.ticks++;s.maxDelayMs=Math.max(s.maxDelayMs,d);s.totalDelayMs+=d;},100);
        new PerformanceObserver(list=>{for(const e of list.getEntries()){(window as any).__perf.longTasks++;(window as any).__perf.longTaskMs+=e.duration;}}).observe({type:'longtask',buffered:true});
      });pages.push(p);
    }
    const directory=await rpc('scope.list');const ids=await ui.evaluate(async n=>(await chrome.tabs.query({})).filter(t=>t.url?.includes('capacity-'+n+'-')).map(t=>t.id!),count!);
    const initial=await rpc('session.start',{recordingId:crypto.randomUUID(),commandId:crypto.randomUUID(),browserRunId:directory.browserRunId,rootBrowserTabIds:ids,policy});const rid=initial.recording.recordingId;
    await until(status,s=>s.readyTargets===count,'capacity all channels ready',30000);
    const start=Date.now();let iterations=0;let earlyStop=false;let last:any;
    while(Date.now()-start<durationSeconds!*1000) {
      const tick=Date.now();const latencies=await Promise.all(pages.map(p=>p.evaluate(async()=>{const t=performance.now();document.querySelector<HTMLInputElement>('input')!.value='3.00';await fetch('/api/token').then(r=>r.text());return performance.now()-t;})));
      const sample=await status();last=sample;iterations++;
      const pageMetrics=await Promise.all(pages.map(p=>p.evaluate(()=>({...((window as any).__perf),memory:(performance as any).memory?{used:(performance as any).memory.usedJSHeapSize,total:(performance as any).memory.totalJSHeapSize}:null}))));
      await appendFile(resolve(output,'samples.ndjson'),JSON.stringify({at:new Date().toISOString(),count,elapsedMs:Date.now()-start,iterations,latencies,pageMetrics,process:processMetrics(),resources:sample.resources,bytesAccepted:sample.recording.bytesAccepted,bytesPersisted:sample.recording.bytesPersisted,eventsPersisted:sample.recording.eventsPersisted,gaps:sample.recording.gaps,state:sample.recording.state})+'\n');
      if(sample.recording.state!=='RECORDING'){earlyStop=true;break;}
      if(iterations%6===0)console.log(`CAPACITY tabs=${count} seconds=${Math.round((Date.now()-start)/1000)} acceptedMiB=${(sample.recording.bytesAccepted/1048576).toFixed(1)}`);
      await new Promise(r=>setTimeout(r,Math.max(1,15000-(Date.now()-tick))));
    }
    await rpc('session.stop',{recordingId:rid,commandId:crypto.randomUUID()});
    const data=await readBundle(rid);const exportStart=Date.now();const before=process.memoryUsage();const result=await createPackage(data);const after=process.memoryUsage();await writeFile(resolve(output,`tabs-${count}.zip`),result.zip);const validation=await validatePackage(result.zip);
    await writeFile(resolve(output,`tabs-${count}.json`),JSON.stringify({count,requestedSeconds:durationSeconds,actualSeconds:(Date.now()-start)/1000,iterations,earlyStop,recording:data.recording,networkRecords:data.network.length,zipBytes:result.zip.length,exportMs:Date.now()-exportStart,exportNodeMemoryBefore:before,exportNodeMemoryAfter:after,lastResources:last.resources,validation},null,2));
    check(`6.5 ${count} 标签持续 ${durationSeconds} 秒且完整导出`,!earlyStop&&validation.valid);
    for(const p of pages)await p.close();
  }
} finally {
  await writeFile(resolve(output, 'acceptance.json'), JSON.stringify({ at: new Date().toISOString(), browserVersion, checks }, null, 2));
  await context?.close(); await fixture.close(); await rm(profile, { recursive: true, force: true });
  console.log(`Evidence: ${output}`);
}
