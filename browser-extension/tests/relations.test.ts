import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPackage, validateFiles } from '../extension/export/package';
import { sha256 } from '../extension/storage/database';
import { recording } from './helpers';
import { newTarget } from '../extension/background/session/gate';
import { now, SCHEMA_VERSION, type BundleData, type EvidenceEvent } from '../shared/contracts';
import { emptyBody } from '../shared/redaction';
import { unzipSync, strToU8, strFromU8 } from 'fflate';

async function fixture(): Promise<BundleData> {
  const r = recording(); r.state = 'READY';
  const targets = [newTarget(r,{id:1,windowId:1},1,'start','root'),newTarget(r,{id:2,windowId:1},1,'start','root')];
  const data: BundleData = { recording:r, targets, chunks:[], network:[], blobs:[] };
  for (let i=0;i<2;i++) {
    const t = targets[i]!; const stream = `recorder-${i}`; const ctx = {documentId:`doc-${i}`,chromeFrameId:0};
    t.documents.push({...ctx,parentFrameId:-1,url:'http://mes.test',observedAt:now(),recorderStreamId:stream,status:'baseline_received',subjectMapping:'registered_document_baseline',baselineRef:{eventId:`${stream}-page:2`,recorderStreamId:stream,nodeId:1}});
    const event = (channel: 'page'|'semantic', seq:number, kind:string, payload:any): EvidenceEvent => ({schemaVersion:SCHEMA_VERSION,recordingId:r.recordingId,browserRunId:r.browserRunId,tabInstanceId:t.tabInstanceId,browserTabId:t.browserTabId,windowId:1,eventId:`${stream}-${channel}:${seq}`,streamId:`${stream}-${channel}`,recorderStreamId:stream,source:channel,sourceSeq:seq,kind,channel,payload,emitterContext:ctx,subjectContext:ctx,sourceTime:seq,sourceClock:'document_performance_ms',observedAt:now(),normalizedAt:null,captureGeneration:1,channelGeneration:1,quality:{redacted:true,truncated:false,limitations:[]}});
    const groups = [
      [event('page',1,'rrweb.event',{rrwebEvent:{type:4,timestamp:1,data:{}}}),event('page',2,'rrweb.event',{rrwebEvent:{type:2,timestamp:2,data:{node:{id:1,type:0,childNodes:[{id:42,type:2,tagName:'input',childNodes:[]}]}}},nodeContexts:[{nodeId:1,documentRoot:true,recorderStreamId:stream,context:ctx}]})],
      [event('semantic',1,'ui.state_snapshot',{target:{elementRef:{recorderStreamId:stream,nodeId:42}}}),event('semantic',2,'ui.action',{action:'input',target:{elementRef:{recorderStreamId:stream,nodeId:42}},evidenceRefs:[`${stream}-semantic:1`]})],
    ];
    for(const events of groups) data.chunks.push({id:`chunk-${data.chunks.length}`,recordingId:r.recordingId,browserRunId:r.browserRunId,streamId:events[0]!.streamId,chunkSeq:data.chunks.length+1,firstSeq:1,lastSeq:2,sha256:await sha256(JSON.stringify(events)),events});
  }
  r.eventsPersisted=8; return data;
}
async function rehash(data:BundleData) { for(const c of data.chunks) c.sha256=await sha256(JSON.stringify(c.events)); }

test('两个录制流都包含 nodeId=42，合法引用独立通过；跨流、文档、基线篡改在 hash 正确时仍拒绝',async()=>{
  const base=await fixture(); base.chunks[1]!.events[0]!.payload.documentContext=null; await rehash(base); await createPackage(base);
  const cases: [string,(b:BundleData)=>void,RegExp][] = [
    ['跨标签快照',b=>{b.chunks[1]!.events[1]!.payload.evidenceRefs=['recorder-1-semantic:1'];},/跨目标或文档/],
    ['跨流节点',b=>{b.chunks[1]!.events[0]!.payload.target.elementRef.recorderStreamId='recorder-1';},/元素引用/],
    ['同号但不存在',b=>{b.chunks[1]!.events[0]!.payload.target.elementRef.nodeId=43;},/元素引用/],
    ['发送文档矛盾',b=>{b.chunks[1]!.events[0]!.emitterContext={chromeFrameId:0,documentId:'doc-1'};},/上下文文档/],
    ['缺基线',b=>{delete b.targets[0]!.documents[0]!.baselineRef;},/缺少基线/],
    ['基线串位',b=>{b.targets[0]!.documents[0]!.baselineRef!.eventId='recorder-1-page:2';},/基线引用/],
    ['主体矛盾',b=>{b.chunks[0]!.events[1]!.payload.nodeContexts[0].context.documentId='absent';},/上下文文档/],
    ['错误观测文档串位',b=>{b.chunks[1]!.events[0]!.payload.documentContext={chromeFrameId:0,documentId:'doc-1'};},/上下文文档/],
    ['状态数组冒充对象',b=>{b.chunks[1]!.events[0]!.payload.after=[];},/schema/],
  ];
  for(const [label,mutate,pattern] of cases){const b=structuredClone(base);mutate(b);await rehash(b);await assert.rejects(createPackage(b),pattern,label);}
  // A new recorder in the same Chrome document is still isolated by recorderStreamId.
  const restarted=structuredClone(base); const one=restarted.targets[0]!; const two=restarted.targets[1]!;
  two.documents[0]!.documentId=one.documents[0]!.documentId; one.documents.push(two.documents[0]!);
  for(const chunk of restarted.chunks.slice(2)) for(const e of chunk.events){e.tabInstanceId=one.tabInstanceId;e.browserTabId=one.browserTabId;e.emitterContext!.documentId='doc-0';e.subjectContext!.documentId='doc-0';for(const n of e.payload.nodeContexts??[])n.context.documentId='doc-0';}
  restarted.targets.pop();await rehash(restarted);await createPackage(restarted);
});

test('必要文件、请求所属调试会话和动作候选闭包校验',async()=>{
  const b=await fixture();const t=b.targets[0]!;const requestKey=`${b.recording.recordingId}:${t.tabInstanceId}:debug:req:0`;
  b.network.push({schemaVersion:SCHEMA_VERSION,requestKey,recordingId:b.recording.recordingId,browserRunId:b.recording.browserRunId,tabInstanceId:t.tabInstanceId,debuggerSessionKey:'debug',cdpRequestId:'req',redirectOrdinal:0,chromeFrameId:0,documentId:'doc-0',request:{...emptyBody('empty',null),method:'GET',url:'http://mes.test/api',headers:{},type:'Fetch'},response:{...emptyBody('empty',null),httpStatus:204,headers:{}},networkOutcome:'finished',businessOutcome:'unknown',serverCorrelation:{requestId:null,requestIdSource:null,traceId:null,traceIdSource:null},startedAt:now(),sourceClock:'cdp_monotonic_seconds',evidenceRefs:[],actionCandidates:[{actionId:'recorder-0-semantic:2',basis:'test',confirmed:false}],extraInfoStatus:'none'});
  const pkg=await createPackage(b);const files=unzipSync(pkg.zip); const manifest=JSON.parse(strFromU8(files['manifest.json']!));
  delete files['README.md'];manifest.files=manifest.files.filter((f:any)=>f.path!=='README.md');files['manifest.json']=strToU8(JSON.stringify(manifest));
  await assert.rejects(validateFiles(files),/缺少必要文件/);
  b.network[0]!.actionCandidates[0]!.actionId='recorder-1-semantic:2';await assert.rejects(createPackage(b),/动作候选引用/);
  b.network[0]!.actionCandidates=[];
  b.chunks[1]!.events[0]!.payload.requestKey=requestKey;b.network[0]!.evidenceRefs=['recorder-0-semantic:1'];await rehash(b);
  await assert.rejects(createPackage(b),/请求证据跨目标或调试会话/);
  b.network[0]!.evidenceRefs=[];
  b.blobs.push({id:'body',recordingId:b.recording.recordingId,path:'bodies/body.json',mime:'application/json',encoding:'utf8',data:'{}'});
  Object.assign(b.network[0]!.response,{bodyCaptureStatus:'captured',bodyRef:'bodies/body.json',savedBytes:2,originalBytes:2});
  await createPackage(b);
  b.network[0]!.response.savedBytes=20;await assert.rejects(createPackage(b),/字节信息/);
});

test('4.1 before 引用已保存先前快照；篡改观察时间/跨文档或指向未来均拒绝',async()=>{
 const b=await fixture();const previous=b.chunks[1]!.events[0]!;const action=b.chunks[1]!.events[1]!;
 action.payload.before={status:'observed',snapshotRef:previous.eventId,observedAt:previous.observedAt,sourceTime:previous.sourceTime};await rehash(b);await createPackage(b);
 action.payload.before.sourceTime=999;await rehash(b);await assert.rejects(createPackage(b),/before 观测/);
 action.payload.before.sourceTime=previous.sourceTime;action.payload.before.snapshotRef='recorder-1-semantic:1';await rehash(b);await assert.rejects(createPackage(b),/before 观测/);
 action.payload.before.snapshotRef=action.eventId;await rehash(b);await assert.rejects(createPackage(b),/before 观测/);
});
