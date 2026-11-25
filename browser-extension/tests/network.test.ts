import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ExtraInfoChain, NetworkCollector, type CaptureHost } from '../extension/background/cdp/network';
import { CaptureGate, newTarget } from '../extension/background/session/gate';
import { recording } from './helpers';
import { cleanHeaders, cleanRrweb, cleanText, cleanUrl, sanitizeBody } from '../shared/redaction';
import type { BlobRecord, NetworkRecord } from '../shared/contracts';
import { parsePolicy } from '../shared/policy';

test('仅保护密码，URL、认证头、令牌与业务精度默认保留', () => {
  const p = recording().policy;
  assert.equal(cleanUrl('https://a.test/?token=secret&x=value#token=secret'), 'https://a.test/?token=secret&x=value#token=secret');
  assert.ok(!cleanUrl('https://user:LOGIN_PASSWORD@a.test/?password=URL_PASSWORD#/login?pwd=HASH_PASSWORD').includes('PASSWORD'));
  assert.equal(cleanHeaders({ Authorization: 'Bearer secret', Cookie: 'sid=secret', 'Set-Cookie': 'secret', 'x-request-id': 'real-id' })['x-request-id'], 'real-id');
  assert.equal(cleanHeaders({ Authorization: 'Bearer secret', Cookie: 'sid=secret' }).authorization, 'Bearer secret');
  assert.equal(cleanHeaders({ Cookie: 'sid=secret' }).cookie, 'sid=secret');
  assert.equal(atob(cleanHeaders({ Authorization: `Basic ${btoa('user:LOGIN_PASSWORD')}` }).authorization!.slice(6)), 'user:[REDACTED]');
  assert.equal(cleanText('token=secret https://a.test/?token=another password="one two"'), 'token=secret https://a.test/?token=another password=[REDACTED]');
  const result = sanitizeBody('{"code":"OK","precision":"3.00","token":"secret","nested":{"password":"other"}}', 'application/json', p);
  assert.ok(result.content?.includes('3.00')); assert.ok(result.content?.includes('secret')); assert.ok(!result.content?.includes('other'));
  assert.equal(sanitizeBody('{"token":bad}', 'application/json', p).fields.bodyCaptureStatus, 'excluded_by_policy');
  const large = JSON.stringify({ token: 'secret', value: 'x'.repeat(p.budgets.bodyBytes) });
  assert.equal(sanitizeBody(large, 'application/json', p).fields.bodyCaptureStatus, 'excluded_by_policy');
  const rr = cleanRrweb({ type: 2, data: { node: { id: 42, attributes: { name: 'password', value: 'secret', href: 'https://a.test/?token=other' }, childNodes: [{ id: 43, textContent: 'token=abc' }] } } }, p);
  assert.equal(rr.data.node.id, 42); assert.equal(rr.data.node.childNodes[0].id, 43); assert.ok(!JSON.stringify(rr).includes('secret'));
});
test('unsafe policy is rejected at runtime', () => {
  const p = recording().policy; assert.deepEqual(parsePolicy(p), p);
  assert.throws(() => parsePolicy({ ...p, pageOrigins: ['https://example.com/path'] }));
  assert.throws(() => parsePolicy({ ...p, budgets: { ...p.budgets, hardBytes: Infinity } }));
  assert.throws(() => parsePolicy({ ...p, apiRules: [{ origin: 'http://mes.test', pathPrefix: '' }] }));
});
test('ExtraInfo early/late queues honor redirect flags and unknown barriers', () => {
  const chain = new ExtraInfoChain();
  chain.extra('r', 'response', { headers: { 'x-hop': 'first', 'Set-Cookie': 'secret' }, statusCode: 302 });
  const first = chain.addHop('r'); first.record = { request: { headers: {} }, response: { headers: {} } } as NetworkRecord;
  const second = chain.addHop('r'); second.record = { request: { headers: {} }, response: { headers: {} } } as NetworkRecord;
  second.expectsExtra = true;
  assert.deepEqual(chain.resolve('r'), []);
  first.expectsExtra = true; chain.resolve('r');
  assert.equal(first.record.response.headers['x-hop'], 'first'); assert.equal(second.record.response.headers['x-hop'], undefined);
  chain.extra('r', 'response', { headers: { 'x-hop': 'second' }, statusCode: 200 }); chain.resolve('r');
  assert.equal(second.record.response.headers['x-hop'], 'second'); assert.equal(first.record.response.headers['set-cookie'], 'secret');
});

test('late response body is discarded after close; a completed queued observation remains', async () => {
  const r = recording(); const t = newTarget(r, { id: 1, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[1, t]]));
  const saved: NetworkRecord[] = []; const blobs: BlobRecord[] = []; let late = 0; let resolveBody!: (v: any) => void;
  const body = new Promise(resolve => { resolveBody = resolve; });
  const host: CaptureHost = { recording: r, valid: token => gate.allows(token), write: (token, _kind, _payload, _meta, record, b) => {
    if (!gate.allows(token)) return null; if (record) saved.push(structuredClone(record)); blobs.push(...(b ?? [])); return `event-${saved.length}`;
  }, diagnostic() {}, finalizeNetwork: (_t, n) => saved.push(structuredClone(n)), late: () => late++ };
  const n = new NetworkCollector(host, t, gate.token(t, 'network'), 'debug-session', async () => body);
  n.event('Network.requestWillBeSent', { requestId: '123', request: { method: 'GET', url: 'http://mes.test/api/save', headers: {} }, type: 'Fetch', timestamp: 1 });
  n.event('Network.responseReceived', { requestId: '123', response: { status: 200, mimeType: 'application/json', headers: {} }, hasExtraInfo: false });
  n.event('Network.loadingFinished', { requestId: '123', timestamp: 2 });
  gate.stopTarget(t, 'tab_closed', 3); n.stop('tab_closed');
  resolveBody({ body: '{"lateSecret":"NEVER_ACCEPT"}', base64Encoded: false }); await new Promise(r => setTimeout(r, 0));
  assert.equal(late, 1); assert.equal(blobs.length, 0); assert.ok(saved.some(x => x.response.httpStatus === 200));
  assert.equal(saved.at(-1)!.response.bodyCaptureStatus, 'incomplete_target_closed'); assert.ok(!JSON.stringify(saved).includes('NEVER_ACCEPT'));
});

test('6.1 iframe/worker 共用标签并发和预留预算，子会话独立取消', async()=>{
  const {BodyQueue}=await import('../extension/background/cdp/network');
  const r=recording();const t=newTarget(r,{id:1,windowId:1},1,'start','root');const gate=new CaptureGate(r,new Map([[1,t]]));const q=new BodyQueue(2,4*r.policy.budgets.bodyBytes);
  const resolvers:(()=>void)[]=[];const calls:string[]=[];let inFlight=0,peak=0;const bodies:any[]=[];
  const host:CaptureHost={recording:r,valid:x=>gate.allows(x),write:(_t,_k,_p,_m,n,b)=>{bodies.push(...(b??[]));return 'e';},diagnostic(){},finalizeNetwork(){},late(){}};
  const collectors=['root','iframe','worker'].map(key=>new NetworkCollector(host,t,gate.token(t,'network'),key,async()=>{calls.push(key);peak=Math.max(peak,++inFlight);await new Promise<void>(resolve=>resolvers.push(resolve));inFlight--;return {body:'{"code":"OK"}'};},()=>null,q));
  for(let round=0;round<3;round++)for(const n of collectors){n.event('Network.requestWillBeSent',{requestId:String(round),request:{method:'GET',url:'http://mes.test/api/x',headers:{}},type:'Fetch'});n.event('Network.responseReceived',{requestId:String(round),response:{status:200,mimeType:'application/json',headers:{}},hasExtraInfo:false});n.event('Network.loadingFinished',{requestId:String(round)});}
  assert.equal(peak,2);assert.equal(q.stats().waiting,2);assert.equal(q.stats().reservedBytes,4*r.policy.budgets.bodyBytes);
  collectors[2]!.stop('child_target_detached');resolvers.shift()!();await new Promise(r=>setImmediate(r));assert.ok(!calls.includes('worker'));
  gate.stopAll('session_stopped',5);collectors.forEach(n=>n.stop('session_stopped'));const count=calls.length;resolvers.splice(0).forEach(r=>r());await new Promise(r=>setImmediate(r));assert.equal(calls.length,count);assert.equal(q.stats().waiting,0);assert.equal(q.stats().running,0);assert.equal(q.stats().reservedBytes,0);assert.equal(peak,2);
});

test('6.5 固定 5000 链阈值明确记录缺口，不继续无限保留新请求链',()=>{
  const r=recording();const t=newTarget(r,{id:1,windowId:1},1,'start','root');const gate=new CaptureGate(r,new Map([[1,t]]));const gaps:string[]=[];
  const host:CaptureHost={recording:r,valid:x=>gate.allows(x),write:()=> 'e',diagnostic:c=>{gaps.push(c);},finalizeNetwork(){},late(){}};
  const n=new NetworkCollector(host,t,gate.token(t,'network'),'s',async()=>({}));
  for(let i=0;i<5100;i++)n.event('Network.requestWillBeSent',{requestId:String(i),request:{method:'GET',url:'http://mes.test/api/x',headers:{}},type:'Fetch'});
  assert.equal(n.records.size,5000);assert.ok(gaps.includes('network_metadata_limit'));assert.ok(n.chains.chains.size<=5000);
});

test('6.4 正文接受触发硬截止时整理只能引用此前已接受字段，不产生悬空 bodyRef',async()=>{
 const r=recording();const t=newTarget(r,{id:1,windowId:1},1,'start','root');const gate=new CaptureGate(r,new Map([[1,t]]));const finalized:NetworkRecord[]=[];let n:NetworkCollector;
 const host:CaptureHost={recording:r,valid:x=>gate.allows(x),write:(_token,kind)=>{if(kind==='network.request_finalized'){gate.stopAll('quota_exceeded',3);n.stop('quota_exceeded');return null;}return 'accepted';},diagnostic(){},finalizeNetwork:(_t,record)=>{finalized.push(structuredClone(record));},late(){}};
 n=new NetworkCollector(host,t,gate.token(t,'network'),'s',async()=>({body:'{"precision":"3.00"}'}));n.event('Network.requestWillBeSent',{requestId:'1',request:{method:'GET',url:'http://mes.test/api/x',headers:{}},type:'Fetch'});n.event('Network.responseReceived',{requestId:'1',response:{status:200,mimeType:'application/json',headers:{}},hasExtraInfo:false});n.event('Network.loadingFinished',{requestId:'1'});await new Promise(r=>setImmediate(r));
 assert.ok(finalized.length);assert.ok(finalized.every(n=>n.response.bodyRef===null));assert.equal(finalized.at(-1)?.response.bodyCaptureStatus,'incomplete_session_stopped');
});

test('7.8 双侧读取失败、base64 解码和空/超限正文保持状态及引用闭包', async () => {
  const cases = [
    { name: 'base64_json', value: { body: Buffer.from('{"quantity":"3.00"}').toString('base64'), base64Encoded: true }, status: 'captured', content: '3.00' },
    { name: 'base64_invalid_utf8', value: { body: '/w==', base64Encoded: true }, status: 'unavailable' },
    { name: 'base64_oversize', value: { body: 'eA=='.repeat(400000), base64Encoded: true }, status: 'excluded_by_policy' },
    { name: 'empty_json', value: { body: '', base64Encoded: false }, status: 'empty' },
    { name: 'read_failure', value: null, status: 'unavailable' },
  ];
  for (const c of cases) {
    const r = recording(); const t = newTarget(r, { id: 1, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[1, t]]));
    const saved = new Map<string, NetworkRecord>(); const blobs: BlobRecord[] = [];
    const host: CaptureHost = { recording: r, valid: token => gate.allows(token), write: (_token, _kind, _payload, _meta, record, b) => { if (record) saved.set(record.requestKey, structuredClone(record)); blobs.push(...(b ?? [])); return 'accepted'; }, diagnostic() {}, finalizeNetwork() {}, late() { assert.fail('没有 STOP，不应计迟到'); } };
    const n = new NetworkCollector(host, t, gate.token(t, 'network'), c.name, async method => { if (method === 'Network.getRequestPostData' || c.value === null) throw Error('injected protocol read failure'); return c.value; });
    n.event('Network.requestWillBeSent', { requestId: '1', request: { method: 'POST', url: 'http://mes.test/api/x', hasPostData: true, headers: { 'content-type': 'application/json' } }, type: 'Fetch' });
    n.event('Network.responseReceived', { requestId: '1', response: { status: 200, mimeType: 'application/json', headers: {} }, hasExtraInfo: false });
    n.event('Network.loadingFinished', { requestId: '1' }); await new Promise(r => setImmediate(r));
    const record = [...saved.values()][0]!;
    assert.equal(record.request.bodyCaptureStatus, 'unavailable', c.name); assert.equal(record.request.bodyCaptureReason, 'getRequestPostData_failed'); assert.equal(record.request.bodyRef, null);
    assert.equal(record.response.bodyCaptureStatus, c.status, c.name);
    if (c.content) { assert.equal(blobs.length, 1); assert.equal(record.response.bodyRef, blobs[0]!.path); assert.ok(String(blobs[0]!.data).includes(c.content)); assert.equal(record.response.savedBytes, Buffer.byteLength(String(blobs[0]!.data))); }
    else { assert.equal(record.response.bodyRef, null); assert.equal(blobs.length, 0); }
  }
});
