import { test } from 'node:test';
import assert from 'node:assert/strict';
import { recording } from './helpers';
import { extractFacts, projectVersions, sourceMatch } from '../shared/correlation';
import { parsePolicy } from '../shared/policy';
import { errorGroups, summarize, SUMMARY_BUDGET } from '../extension/export/summary';
import type { BundleData, EvidenceEvent } from '../shared/contracts';
import { NetworkCollector, type CaptureHost } from '../extension/background/cdp/network';
import { CaptureGate, newTarget } from '../extension/background/session/gate';
import { cleanHeaders, cleanValue } from '../shared/redaction';

test('5.3 来源配置保留自定义头/JSON Pointer、混合构建、冲突和显式但未验证的源码映射', async () => {
  const r=recording();
  r.policy.correlationSources=[{field:'backendBuildId',source:'response_header',key:'x-release',component:'service-a'},{field:'requestId',source:'response_json',key:'/meta/request~1id',component:'service-a'},{field:'backendBuildId',source:'response_json',key:'/meta/build',component:'service-a'}];
  r.policy.sourceMappings=[{environmentId:'fixture',component:'service-a',buildId:'v1',codeSnapshot:'svn:123'}];
  assert.deepEqual(parsePolicy(r.policy),r.policy);
  assert.throws(()=>parsePolicy({...r.policy,correlationSources:[{field:'frontendBuildId',source:'page_meta',key:`meta[name="broken']`,component:'ui'}]}),/来源配置/);
  assert.throws(()=>parsePolicy({...r.policy,correlationSources:[{...r.policy.correlationSources[0],origin:0}]}),/来源配置/);
  assert.throws(()=>parsePolicy({...r.policy,correlationSources:[{...r.policy.correlationSources[0],source:'response_json',key:'/bad~3'}]}));
  const header=extractFacts(r.policy,'http://mes.test/api/save','response_header',cleanHeaders({'X-Release':'v1'}));
  const body=extractFacts(r.policy,'http://mes.test/api/save','response_json',cleanValue({meta:{'request/id':'real-server-id',build:'v2'}}));
  assert.equal(body[0]?.value,'real-server-id');
  assert.equal(sourceMatch(r,header[0]!,header).status,'configured_unverified');
  assert.equal(sourceMatch(r,header[0]!,[...header,...body]).status,'unresolved');
  r.policy.sourceMappings.push({...r.policy.sourceMappings[0]!,codeSnapshot:'git:abc'});
  assert.equal(sourceMatch(r,header[0]!,header).reason,'conflicting_manual_mappings');
  r.policy.sourceMappings=[]; assert.equal(sourceMatch(r,header[0]!,header).reason,'mapping_missing');
  projectVersions(r,header,'req:1');projectVersions(r,body,'req:2');assert.equal(r.versions.backendBuildId,'mixed_deployment');assert.match(r.versions.sources.backendBuildId!,/req:1/);
  assert.deepEqual(extractFacts(r.policy,'http://mes.test/api/save','response_header',{}),[]);
  const t=newTarget(r,{id:1,windowId:1},1,'start','root');const gate=new CaptureGate(r,new Map([[1,t]]));const saved:any[]=[];const commands:string[]=[];
  const host:CaptureHost={recording:r,valid:x=>gate.allows(x),write:(_t,_k,_p,_m,n)=>{saved.push(structuredClone(n));return 'e';},diagnostic(){},finalizeNetwork(){},late(){}};
  const n=new NetworkCollector(host,t,gate.token(t,'network'),'s',async method=>{commands.push(method);return {body:JSON.stringify({meta:{'request/id':'real-server-id',build:'v2'}})};});
  n.event('Network.requestWillBeSent',{requestId:'1',type:'Fetch',request:{method:'GET',url:'http://mes.test/api/save',headers:{}}});
  n.event('Network.responseReceived',{requestId:'1',response:{status:200,mimeType:'application/json',headers:{'x-release':'v1'}},hasExtraInfo:false});n.event('Network.loadingFinished',{requestId:'1'});
  await new Promise(r=>setImmediate(r));
  assert.deepEqual(commands,['Network.getResponseBody']);assert.equal(saved.at(-1).businessOutcome,'unknown');assert.equal(saved.at(-1).serverCorrelation.requestId,'real-server-id');assert.equal(saved.at(-1).correlationFacts.length,3);
});
function error(id:number,tab='tab-1',doc='doc-1',kind='browser.console'):EvidenceEvent {
  return {eventId:`s:${id}`,observedAt:'2026-11-16T01:00:00.000Z',kind,tabInstanceId:tab,subjectContext:{documentId:doc,chromeFrameId:0},payload:kind==='browser.console'?{args:['Error: failure'],stackTrace:{callFrames:[{functionName:'save'}]}}:{details:{exception:{description:'Error: failure'},stackTrace:{callFrames:[{functionName:'save'}]}}}} as unknown as EvidenceEvent;
}
test('5.4 候选错误组保留多源引用，不跨标签/文档合并，不声称确认故障',()=>{
  const events=[error(1),error(2,'tab-1','doc-1','browser.exception'),error(3,'tab-2'),error(4,'tab-1','doc-2')];
  const groups=errorGroups(events);assert.equal(groups.length,3);assert.deepEqual(groups[0]!.evidenceRefs,['s:1','s:2']);assert.ok(groups.every(g=>g.confirmed===false));
});
test('5.5 大规模目标/标记/错误的摘要有界，优先保留早期标记，列明省略范围和读取入口',()=>{
  const r=recording();r.environmentId='x'.repeat(8000);
  const events=Array.from({length:5000},(_,i)=>error(i));events.unshift({...error(9000),kind:'ui.issue_marker',payload:{note:'最初的时间标记'}});
  for(let i=0;i<1000;i++)events.push({...error(10000+i),kind:'ui.issue_marker',payload:{note:'later'.repeat(1000)}});
  const targets=Array.from({length:1000},(_,i)=>newTarget(r,{id:i,windowId:1,url:'http://mes.test'},i,'start','root'));
  const data={recording:r,targets,chunks:[{events}],network:[],blobs:[]} as unknown as BundleData;
  const summary=summarize(data);assert.ok(summary.length<=SUMMARY_BUDGET);assert.ok(summary.includes('最初的时间标记'));assert.match(summary,/省略=991/);assert.match(summary,/省略范围/);assert.match(summary,/errors\/groups/);assert.match(summary,/不是已确认故障数/);assert.ok(summary.indexOf('时间标记')<summary.indexOf('范围与关闭截止'));
});
