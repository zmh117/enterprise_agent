import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DebuggerManager, type DebugHost } from '../extension/background/cdp/manager';
import { CaptureGate, newTarget } from '../extension/background/session/gate';
import { recording } from './helpers';

test('a late successful attach after STOP immediately detaches and never enables domains', async () => {
  const r = recording(); const t = newTarget(r, { id: 42, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[42, t]]));
  let finish!: () => void; let detaches = 0; let commands = 0;
  const previous = (globalThis as any).chrome;
  (globalThis as any).chrome = { debugger: { attach: () => new Promise<void>(resolve => { finish = resolve; }), detach: async () => { detaches++; }, sendCommand: async () => { commands++; } } };
  const host: DebugHost = { recording: r, token: (t, c) => gate.token(t, c), valid: token => gate.allows(token), write: () => null, diagnostic() {}, finalizeNetwork() {}, late() {}, channelReady() {}, channelLost() {}, permitted: async () => true, permittedKnown: () => true };
  try {
    const manager = new DebuggerManager(host); const pending = manager.attach(t);
    gate.stopAll('session_stopped', 2); finish(); await pending;
    assert.equal(detaches, 1); assert.equal(commands, 0); assert.equal(t.accepting, false);
  } finally { (globalThis as any).chrome = previous; }
});

test('a persisted debugger denial does not retry after manager recreation', async () => {
  const r = recording(); const t = newTarget(r, { id: 42, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[42, t]])); t.debuggerBlocked = true;
  const previous = (globalThis as any).chrome; let attached = 0;
  (globalThis as any).chrome = { debugger: { attach: async () => { attached++; } } };
  const host: DebugHost = { recording: r, token: (t, c) => gate.token(t, c), valid: token => gate.allows(token), write: () => null, diagnostic() {}, finalizeNetwork() {}, late() {}, channelReady() {}, channelLost() {}, permitted: async () => true, permittedKnown: () => true };
  try { await new DebuggerManager(host).attach(t); assert.equal(attached, 0); assert.equal(gate.allows(gate.token(t, 'page')), true); }
  finally { (globalThis as any).chrome = previous; }
});

test('专属子 session 启用失败仅记录子范围缺口，父通道 token 仍有效', async () => {
  const r = recording(); const t = newTarget(r, { id: 42, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[42,t]]));
  const previous = (globalThis as any).chrome; const gaps: string[] = []; const lost: string[] = [];
  (globalThis as any).chrome = { debugger: { attach: async () => {}, detach: async () => {}, sendCommand: async (s: any,m: string) => { if (s.sessionId && m === 'Network.enable') throw new Error('child unavailable'); return {}; } } };
  const host: DebugHost = { recording:r, token: (t,c) => gate.token(t,c), valid: x => gate.allows(x), write: () => null, diagnostic: c => { gaps.push(c); }, finalizeNetwork() {}, late() {}, channelReady(t,c) { t.channels[c].state='ACTIVE'; }, channelLost(t,c,reason) { lost.push(c); gate.loseChannel(t,c,reason); }, permitted: async () => true, permittedKnown: () => true };
  try {
    const manager = new DebuggerManager(host); await manager.attach(t); const token = gate.token(t,'network');
    manager.event({ tabId:42 },'Target.attachedToTarget',{ sessionId:'child',targetInfo:{type:'iframe',url:'http://mes.test/frame'} });
    for(let i=0;i<5;i++) await new Promise(r => setImmediate(r));
    assert.equal(gate.allows(token),true); assert.equal(t.channels.network.state,'ACTIVE'); assert.deepEqual(lost,[]);
    assert.ok(gaps.some(c => c.startsWith('network_enable_failed:')));
  } finally { (globalThis as any).chrome=previous; }
});

test('5.4 稳定 exceptionId 只去除同 session/context 的重复传输，保留独立多源观测',async()=>{
 const r=recording();const t=newTarget(r,{id:42,windowId:1},1,'start','root');const gate=new CaptureGate(r,new Map([[42,t]]));const writes:any[]=[];const previous=(globalThis as any).chrome;
 (globalThis as any).chrome={debugger:{attach:async()=>{},detach:async()=>{},sendCommand:async()=>({})},runtime:{id:'collector'}};
 const host:DebugHost={recording:r,token:(t,c)=>gate.token(t,c),valid:x=>gate.allows(x),write:(_t,k,p)=>{writes.push({k,p});return 'e';},diagnostic(){},finalizeNetwork(){},late(){},channelReady(){},channelLost(){},permitted:async()=>true,permittedKnown:()=>true};
 try {const m=new DebuggerManager(host);await m.attach(t);m.event({tabId:42},'Runtime.executionContextCreated',{context:{id:1,auxData:{frameId:'f',isDefault:true}}});const payload={timestamp:1,exceptionDetails:{exceptionId:7,executionContextId:1,text:'Error',exception:{description:'failure'}}};m.event({tabId:42},'Runtime.exceptionThrown',payload);m.event({tabId:42},'Runtime.exceptionThrown',payload);m.event({tabId:42},'Runtime.consoleAPICalled',{type:'error',executionContextId:1,timestamp:1,args:[{value:'failure'}]});assert.equal(writes.length,2);assert.equal(r.capabilities.duplicateErrorTransports,1);m.event({tabId:42},'Runtime.exceptionThrown',{...payload,exceptionDetails:{...payload.exceptionDetails,exceptionId:8}});assert.equal(writes.length,3);}finally{(globalThis as any).chrome=previous;}
});
