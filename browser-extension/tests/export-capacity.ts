import { randomBytes } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { recording } from './helpers';
import { newTarget } from '../extension/background/session/gate';
import { SCHEMA_VERSION, now, bytes, type BundleData, type EvidenceEvent, type NetworkRecord } from '../shared/contracts';
import { emptyBody } from '../shared/redaction';
import { createPackage, validatePackage } from '../extension/export/package';
import { sha256 } from '../extension/storage/database';
const output=resolve(process.env.MES_TEST_OUTPUT??'output/playwright/p1-export-capacity-v3');await mkdir(output,{recursive:true});
if(!process.argv.includes('--child')) {
 const child=spawn(process.execPath,['--import','tsx','tests/export-capacity.ts','--child'],{stdio:'inherit',env:process.env});const samples:any[]=[];
 const timer=setInterval(()=>{try{const [cpu,rss]=execFileSync('/bin/ps',['-p',String(child.pid),'-o','%cpu=,rss='],{encoding:'utf8'}).trim().split(/\s+/).map(Number);samples.push({at:new Date().toISOString(),cpuPercent:cpu,rssKiB:rss});}catch{}},250);
 const code=await new Promise<number|null>(resolve=>child.on('exit',resolve));clearInterval(timer);await writeFile(resolve(output,'process-metrics.json'),JSON.stringify({layer:'single Node exporter process;external 250ms samples;RSS excludes browser',samples,peakRssKiB:Math.max(...samples.map(s=>s.rssKiB)),peakCpuPercent:Math.max(...samples.map(s=>s.cpuPercent))},null,2));if(code!==0)throw new Error(`export benchmark failed: ${code}`);
} else {
 const r=recording();r.state='READY';r.stoppedAt=now();r.capabilities={syntheticExportMeasurement:true};
 const t=newTarget(r,{id:1,windowId:1},1,'synthetic','root');t.accepting=false;t.captureState='STOPPED';
 const data:BundleData={recording:r,targets:[t],chunks:[],network:[],blobs:[]};const events:EvidenceEvent[]=[];
 const count=205;const bodyChars=950*1024;
 for(let i=0;i<count;i++) {
  const body=JSON.stringify({precision:'3.00',measurement:randomBytes(bodyChars/2).toString('hex')});const id=`measurement-${i}`,path=`bodies/${id}.json`,requestKey=`${r.recordingId}:${t.tabInstanceId}:synthetic:${i}:0`;
  data.blobs.push({id,recordingId:r.recordingId,path,mime:'application/json',encoding:'utf8',data:body});
  events.push({schemaVersion:SCHEMA_VERSION,eventId:`synthetic:${i+1}`,recordingId:r.recordingId,browserRunId:r.browserRunId,tabInstanceId:t.tabInstanceId,browserTabId:1,windowId:1,emitterContext:null,subjectContext:null,streamId:'synthetic',source:'network',sourceSeq:i+1,kind:'network.request_finalized',sourceTime:null,sourceClock:'extension_observation',observedAt:now(),normalizedAt:null,captureGeneration:1,channel:'network',channelGeneration:1,payload:{requestKey,bodyRef:path},quality:{redacted:true,truncated:false,limitations:['synthetic_export_measurement']}});
  data.network.push({schemaVersion:SCHEMA_VERSION,requestKey,recordingId:r.recordingId,browserRunId:r.browserRunId,tabInstanceId:t.tabInstanceId,debuggerSessionKey:'synthetic',cdpRequestId:String(i),redirectOrdinal:0,chromeFrameId:null,documentId:null,frameMappingReason:'synthetic_no_browser_document',request:{...emptyBody('empty',null),method:'GET',url:'http://mes.test/api/measurement',headers:{},type:'Fetch'},response:{...emptyBody('captured',null),httpStatus:200,headers:{},bodyRef:path,originalBytes:bytes(body),savedBytes:bytes(body)},networkOutcome:'finished',businessOutcome:'unknown',serverCorrelation:{requestId:null,requestIdSource:null,traceId:null,traceIdSource:null},startedAt:now(),sourceClock:'extension_observation',evidenceRefs:[`synthetic:${i+1}`],actionCandidates:[],extraInfoStatus:'not_applicable'} satisfies NetworkRecord);
 }
 r.eventsPersisted=events.length;r.checkpoint=1;r.bytesAccepted=data.blobs.reduce((n,b)=>n+bytes(b),0)+bytes(events)+bytes(data.network);r.bytesPersisted=r.bytesAccepted;
 if(r.bytesAccepted>r.policy.budgets.hardBytes)throw new Error('fixture exceeds declared session budget');
 data.chunks.push({id:'measurement:1',recordingId:r.recordingId,browserRunId:r.browserRunId,streamId:'synthetic',chunkSeq:1,firstSeq:1,lastSeq:events.length,sha256:await sha256(JSON.stringify(events)),events});
 const started=performance.now();const result=await createPackage(data);const exportMs=performance.now()-started;const validateStarted=performance.now();const validation=await validatePackage(result.zip);const validateMs=performance.now()-validateStarted;
 await writeFile(resolve(output,'near-budget.zip'),result.zip);await writeFile(resolve(output,'measurement.json'),JSON.stringify({kind:'synthetic bounded export;not real browser capture',build:JSON.parse(await readFile('dist/build-info.json','utf8')),declaredSessionHardBytes:r.policy.budgets.hardBytes,inputBytes:r.bytesAccepted,ratio:r.bytesAccepted/r.policy.budgets.hardBytes,filesUncompressedBytes:result.manifest.files.reduce((n,f)=>n+f.bytes,0),zipBytes:result.zip.length,exportMs,validateMs,nodeMemoryAfter:process.memoryUsage(),validation,limits:'接近默认 200 MiB 会话预算；600 MiB ZIP / 700 MiB 解压是校验安全上限，不是已验收容量或可配置承诺'},null,2));console.log(`EXPORT near-budget ${(r.bytesAccepted/1048576).toFixed(1)} MiB zip=${(result.zip.length/1048576).toFixed(1)} MiB export=${Math.round(exportMs)}ms`);
}
