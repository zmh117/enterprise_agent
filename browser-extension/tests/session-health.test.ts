import 'fake-indexeddb/auto';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SessionManager } from '../extension/background/session/manager';
import { DEFAULT_POLICY, parsePolicy, revokedHostMatches } from '../shared/policy';
import { captureHealth } from '../shared/capture-health';
import { createPackage, validatePackage } from '../extension/export/package';
import { recording } from './helpers';

async function setup(options: { denied?: number[]; missing?: number[]; networkFailure?: boolean } = {}) {
  const previous = (globalThis as any).chrome;
  const state: Record<string, unknown> = {};
  const tab = (id: number) => { if (options.missing?.includes(id)) throw new Error('closed'); return { id, windowId: 1, url: `http://host${id}.test/`, title: `T${id}` }; };
  (globalThis as any).chrome = {
    storage: { local: { get: async (k: string) => ({ [k]: state[k] }), set: async (v: object) => Object.assign(state, v), remove: async (k: string) => { delete state[k]; } }, session: { setAccessLevel: async () => {}, get: async (k: string) => ({ [k]: state[k] }), set: async (v: object) => Object.assign(state, v) } },
    permissions: { getAll: async () => ({}), contains: async ({ origins }: any) => !options.denied?.some(id => origins[0].includes(`host${id}.test`)) },
    tabs: { get: async (id: number) => tab(id), sendMessage: async () => ({}) },
    webNavigation: { getAllFrames: async () => [], getFrame: async ({ tabId, frameId }: any) => ({ documentId: `doc-${tabId}-${frameId}`, parentFrameId: frameId ? 0 : -1, url: tab(tabId).url }) },
    scripting: { executeScript: async () => [] },
    debugger: { attach: async () => {}, detach: async () => {}, sendCommand: async (_s: any, method: string) => { if (method === 'Network.enable' && options.networkFailure) throw new Error('denied'); return {}; } },
    runtime: { id: 'collector', getURL: (path: string) => `chrome-extension://collector/${path}`, getManifest: () => ({ version: 'test' }) },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
  };
  const manager = new SessionManager(); await manager.ready;
  const command = (ids: number[]) => ({ recordingId: crypto.randomUUID(), commandId: crypto.randomUUID(), browserRunId: manager.browserRunId, rootBrowserTabIds: ids,
    policy: parsePolicy({ ...structuredClone(DEFAULT_POLICY), pageOrigins: ids.map(i => `http://host${i}.test`), apiRules: [] }) });
  const settled = async () => { for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r)); };
  return { manager, command, settled, async close() { if (manager.recording) { await manager.stop(); await manager.journal.flush(); await manager.db.deleteRecording(manager.recording.recordingId); } (globalThis as any).chrome = previous; } };
}

test('部分根权限失败保留有效根，全根失效保存 FAILED 诊断，格式错误不创建会话', async () => {
  const h = await setup({ denied: [2], missing: [3] });
  try {
    await assert.rejects(h.manager.start({ ...h.command([1]), rootBrowserTabIds: [] }), /有效的根标签/);
    assert.equal(h.manager.status().recording, null);
    await h.manager.start(h.command([1,2,3])); await h.settled();
    assert.equal(h.manager.targets.get(1)!.channels.network.state, 'ACTIVE');
    assert.equal(h.manager.targets.get(2)!.channels.network.state, 'BLOCKED');
    assert.equal(h.manager.targets.get(3)!.captureState, 'BLOCKED');
    assert.equal(h.manager.status().readyTargets, 0); // No page baseline yet.
    await h.manager.stop(); await h.manager.db.deleteRecording(h.manager.recording.recordingId);
    await h.manager.start(h.command([3])); await h.settled(); await h.manager.journal.flush();
    assert.equal(h.manager.recording.state, 'FAILED');
    assert.equal((await h.manager.db.bundle(h.manager.recording.recordingId)).targets.length, 1);
  } finally { await h.close(); }
});

test('7.5 撤权通知同步截止受影响根，权限查询等待期间旧 token 不得写入', async () => {
  const denied: number[] = []; const h = await setup({ denied });
  let release: (() => void) | undefined; let pending: Promise<void> | undefined;
  try {
    await h.manager.start(h.command([1, 3])); await h.settled();
    const root = h.manager.targets.get(1)!, unaffected = h.manager.targets.get(3)!;
    const old = h.manager.token(root, 'network'), healthy = h.manager.token(unaffected, 'network');
    denied.push(1);
    chrome.permissions.getAll = (() => new Promise<chrome.permissions.Permissions>(r => { release = () => r({ origins: [] }); })) as typeof chrome.permissions.getAll;
    pending = h.manager.permissionsRemoved({ origins: ['http://host1.test/*'] });
    assert.equal(h.manager.valid(old), false, '收到撤权后必须先关 gate 再 await');
    assert.equal(h.manager.write(old, 'browser.console', { args: ['REVOKED-LATE'] }), null);
    assert.equal(h.manager.valid(healthy), true, '无关根不应被连带截止');
    release!(); await pending;
    assert.equal(root.channels.page.state, 'BLOCKED');
  } finally { release?.(); await pending?.catch(() => {}); await h.close(); }
});

test('7.5 子文档撤权使父统一流和旧 CDP token 失效，保留其他根与有效父页', async () => {
  const denied: number[] = []; const h = await setup({ denied });
  try {
    const command = h.command([1, 3]); command.policy.pageOrigins.push('http://host2.test');
    await h.manager.start(command); await h.settled();
    const original = chrome.webNavigation.getFrame;
    chrome.webNavigation.getFrame = ((d: any) => d.frameId === 2 ? Promise.resolve({ documentId: 'child-2', parentFrameId: 0, url: 'http://host2.test/' }) : original(d)) as typeof chrome.webNavigation.getFrame;
    const sender = { tab: { id: 1 }, frameId: 2, documentId: 'child-2', url: 'http://host2.test/' } as chrome.runtime.MessageSender;
    assert.ok(await h.manager.handshake(sender));
    const root = h.manager.targets.get(1)!, other = h.manager.targets.get(3)!;
    const old = h.manager.token(root, 'network'), healthy = h.manager.token(other, 'network');
    denied.push(2);
    await h.manager.permissionsRemoved({ origins: ['http://host2.test/*'] }); await h.settled();
    assert.equal(h.manager.valid(old), false, '子文档旧正文读取不得借父标签 token 越过撤权');
    assert.equal(h.manager.valid(healthy), true);
    assert.equal(root.channels.network.state, 'ACTIVE');
    assert.equal(await h.manager.handshake(sender), null);
    assert.ok(root.documents.find(d => d.documentId === 'child-2')?.endedAt);
  } finally { await h.close(); }
});

test('7.5 子 frame 已启用网络但尚未取得页面票据时撤权也截止旧 token', async () => {
  const denied: number[] = []; const h = await setup({ denied });
  try {
    const command = h.command([1]); command.policy.pageOrigins.push('http://host2.test');
    await h.manager.start(command); await h.settled();
    const root = h.manager.targets.get(1)!, old = h.manager.token(root, 'network');
    h.manager.debugger.event({ tabId: 1 }, 'Page.frameNavigated', { frame: { id: 'child-before-handshake', url: 'http://host2.test/frame' } });
    assert.equal(root.documents.length, 0);
    denied.push(2); await h.manager.permissionsRemoved({ origins: ['http://host2.test/*'] });
    assert.equal(h.manager.valid(old), false, '不能仅凭已登记文档判断撤权影响范围');
  } finally { await h.close(); }
});

test('7.5 权限快照原子替换，晚到的旧查询不得重新授予已撤回 origin', async () => {
  const h = await setup(); let release: ((v: boolean) => void) | undefined;
  let pending: Promise<unknown> | undefined;
  try {
    await h.manager.start(h.command([1])); await h.settled();
    chrome.permissions.contains = (() => new Promise<boolean>(r => { release = r; })) as typeof chrome.permissions.contains;
    pending = h.manager.refreshPermissions(); await h.settled();
    assert.equal(h.manager.permittedKnown('http://host1.test/'), true, '读取过程中不暴露半成品快照');
    chrome.permissions.contains = (async () => false) as typeof chrome.permissions.contains;
    await h.manager.refreshPermissions();
    release!(true); await pending;
    assert.equal(h.manager.permittedKnown('http://host1.test/'), false);
  } finally { release?.(false); await pending?.catch(() => {}); await h.close(); }
});

test('7.5 撤权匹配限定 scheme、域名边界和显式端口，不把通配规则用作授权', () => {
  for (const [pattern, url, expected] of [
    ['http://host.test/*', 'http://host.test:4477/page', true],
    ['http://host.test/*', 'https://host.test/page', false],
    ['*://*.host.test/*', 'https://a.host.test:9443/page', true],
    ['*://*.host.test/*', 'http://host.test/page', true],
    ['*://*.host.test/*', 'https://evilhost.test/page', false],
    ['http://host.test:4477/*', 'http://host.test:4478/page', false],
    ['http://host.test:80/*', 'http://host.test/page', true],
    ['http://[::1]:4477/*', 'http://[::1]:4477/page', true],
    ['<all_urls>', 'chrome://extensions', false],
    ['<all_urls>', 'https://host.test/page', true],
  ] as const) assert.equal(revokedHostMatches(pattern, url), expected, pattern + ' ' + url);
});

test('7.5 撤权重核等待期间 STOP，不得在晚到查询后重新启动通道', async () => {
  const h = await setup(); let release: (() => void) | undefined; let pending: Promise<void> | undefined;
  try {
    await h.manager.start(h.command([1])); await h.settled();
    let attaches = 0; chrome.debugger.attach = (async () => { attaches++; }) as typeof chrome.debugger.attach;
    chrome.permissions.getAll = (() => new Promise<chrome.permissions.Permissions>(r => { release = () => r({}); })) as typeof chrome.permissions.getAll;
    pending = h.manager.permissionsRemoved({ origins: ['http://host1.test/*'] });
    await h.manager.stop(); release!(); await pending; await h.settled();
    assert.equal(attaches, 0); assert.equal(h.manager.recording.state, 'READY');
    assert.equal(h.manager.targets.get(1)!.channels.network.state, 'STOPPED');
  } finally { release?.(); await pending?.catch(() => {}); await h.close(); }
});

test('网络启用失败与页面就绪期限分别收敛，晚到基线不能恢复已失效通道', async context => {
  const h = await setup({ networkFailure: true });
  context.mock.timers.enable({ apis: ['setTimeout'] });
  try {
    await h.manager.start(h.command([1])); await h.settled();
    const target = h.manager.targets.get(1)!;
    assert.equal(target.channels.network.state, 'LOST');
    assert.equal(target.channels.runtime.state, 'ACTIVE');
    assert.equal(target.channels.page.state, 'PENDING');
    context.mock.timers.tick(10_001); await h.settled();
    assert.equal(target.channels.page.state, 'LOST'); assert.equal(target.channels.semantic.state, 'LOST');
    h.manager.channelReady(target, 'page'); assert.equal(target.channels.page.state, 'LOST');
    assert.equal(captureHealth(target), 'DEGRADED');
  } finally { context.mock.timers.reset(); await h.close(); }
});

test('页面失效不阻断仍有效语义流，重复命令与停止后的旧分片不能新增业务证据', async () => {
  const h = await setup();
  try {
    const command = h.command([1]); await h.manager.start(command); await h.settled();
    const sender = { tab: { id: 1 }, frameId: 0, documentId: 'doc-1-0', url: 'http://host1.test/' } as chrome.runtime.MessageSender;
    const ticket = (await h.manager.handshake(sender))!; assert.ok(ticket);
    const send = (seq: number, kind: string, payload: any) => h.manager.capture({ type: 'capture.batch', ticketId: ticket.id, packetId: seq, index: 0, total: 1, data: JSON.stringify({ seq, kind, sourceTime: seq, payload }) }, sender);
    send(1, 'capture.page_diagnostic', { code: 'rrweb_start_failed' });
    send(2, 'capture.page_diagnostic', { code: 'semantic_started' });
    assert.equal(h.manager.targets.get(1)!.channels.semantic.state, 'ACTIVE');
    assert.equal(send(3, 'ui.observation', { action: 'input', after: { value: '3.00' } }).ok, true);
    await h.manager.start(command); assert.equal(h.manager.targets.size, 1);
    await h.manager.stop(); const first = await h.manager.db.bundle(command.recordingId);
    assert.equal(send(4, 'ui.observation', { action: 'input', after: { value: 'late' } }).ok, false);
    await h.manager.stop(); await h.manager.journal.flush();
    const after = await h.manager.db.bundle(command.recordingId);
    assert.equal(after.chunks.flatMap(c => c.events).filter(e => e.channel !== 'control').length, first.chunks.flatMap(c => c.events).filter(e => e.channel !== 'control').length);
  } finally { await h.close(); }
});

test('启动尚未建立会话时 STOP 撤销启动资格，旧 recordingId 无法重新开始', async () => {
  const h = await setup();
  try {
    const command = h.command([1]);
    const pending = h.manager.start(command); const rejection = assert.rejects(pending, /取消/);
    await h.manager.stopCommand(command); await rejection;
    await assert.rejects(h.manager.start(command), /取消/);
    assert.equal(h.manager.recording, undefined);
  } finally { await h.close(); }
});

test('后台初始化清理不兼容旧开发记录，保留当前契约的已保存会话', async () => {
  const h=await setup(); const old=recording();old.schemaVersion='1.0.0';old.state='READY';const current=recording();current.state='READY';
  try {
    await h.manager.db.saveBatch(old,[],[],[],[]);await h.manager.db.saveBatch(current,[],[],[],[]);
    const reopened=new SessionManager();await reopened.ready;
    assert.equal(await reopened.db.getRecording(old.recordingId),undefined);
    assert.equal((await reopened.db.getRecording(current.recordingId))?.schemaVersion,current.schemaVersion);
  } finally { await h.manager.db.deleteRecording(old.recordingId);await h.manager.db.deleteRecording(current.recordingId);await h.close(); }
});

test('6.2 停止超过 5 秒分别报告截止/清理/排空/终结，不重新开放 gate',async context=>{
  const h=await setup();
  try {
    await h.manager.start(h.command([1]));await h.settled();await h.manager.journal.flush();
    context.mock.timers.enable({apis:['setTimeout']});
    let release!:()=>void;const original=h.manager.db.saveBatch.bind(h.manager.db);let writes=0;
    h.manager.db.saveBatch=async(...args)=>{writes++;if(writes===1)await new Promise<void>(resolve=>{release=resolve;});await original(...args);};
    const stopping=h.manager.stop();await h.settled();const retry=h.manager.retrySave();context.mock.timers.tick(5001);await h.settled();
    assert.equal(h.manager.recording.stopProgress?.deadlineExceeded,true);assert.equal(h.manager.recording.stopProgress?.cutoff,'complete');assert.equal(h.manager.recording.stopProgress?.cleanup,'complete');assert.equal(h.manager.recording.stopProgress?.drain,'pending');assert.equal(h.manager.recording.stopProgress?.terminal,'pending');assert.equal(writes,1);assert.equal(h.manager.targets.get(1)!.accepting,false);assert.equal(h.manager.recording.saveState,'pending');
    release();await Promise.all([stopping,retry]);assert.equal(h.manager.recording.state,'READY');assert.equal(h.manager.recording.saveState,'saved');assert.equal(h.manager.recording.stopProgress?.terminal,'complete');
  }finally{context.mock.timers.reset();await h.close();}
});

test('6.3 已持久化 STOP 意图在后台重建时只整理已提交数据，不恢复采集',async()=>{
  const h=await setup();
  try {
    await h.manager.start(h.command([1]));await h.settled();await h.manager.journal.flush();const rid=h.manager.recording.recordingId;
    await chrome.storage.local.set({stopIntent:{recordingId:rid,reason:'session_stopped',startedAt:new Date().toISOString(),finalState:'READY'}});
    // Recreate only after a committed batch; the lost volatile tail is explicitly a gap.
    const reopened=new SessionManager();await reopened.ready;assert.equal(reopened.recording.state,'READY');assert.ok([...reopened.targets.values()].every(t=>!t.accepting));assert.ok(reopened.recording.gaps.some(g=>g.code==='interrupted_finalization'));assert.equal((await reopened.db.bundle(rid)).recording.saveState,'saved');assert.equal((await chrome.storage.local.get('stopIntent')).stopIntent,undefined);
  }finally{await h.close();}
});

test('6.4 分片中 STOP、重组超限、Journal 队列及会话硬预算均截止并允许新会话新基线',async()=>{
  const h=await setup();
  const sender={tab:{id:1},frameId:0,documentId:'doc-1-0',url:'http://host1.test/'} as chrome.runtime.MessageSender;
  try {
    await h.manager.start(h.command([1]));await h.settled();const first=(await h.manager.handshake(sender))!;
    const fragment={type:'capture.batch' as const,ticketId:first.id,packetId:1,index:0,total:2,data:'{"seq":1'};
    h.manager.capture(fragment,sender);await h.manager.stop();assert.equal(h.manager.capture({...fragment,index:1,data:'}'},sender).ok,false);
    await h.manager.start(h.command([1]));await h.settled();const fresh=(await h.manager.handshake(sender))!;assert.notEqual(first.recorderStreamId,fresh.recorderStreamId);
    const send=(seq:number,kind:string,payload:any)=>h.manager.capture({type:'capture.batch',ticketId:fresh.id,packetId:seq,index:0,total:1,data:JSON.stringify({seq,kind,payload,sourceTime:seq})},sender);
    assert.equal(send(1,'rrweb.event',{rrwebEvent:{type:3,timestamp:1,data:{source:0,adds:[]}},nodeContexts:[]}).ok,false);assert.ok(h.manager.recording.gaps.some(g=>g.detail.includes('incremental_without_baseline')));await h.manager.stop();
    await h.manager.start(h.command([1]));await h.settled();const over=(await h.manager.handshake(sender))!;h.manager.recording.policy.budgets.baselineBytes=10;
    // The assembler uses the frozen constructor budget, so use enough fragments to exceed it.
    const frag='x'.repeat(128*1024);let result:any;for(let i=0;i<65;i++)result=h.manager.capture({type:'capture.batch',ticketId:over.id,packetId:1,index:i,total:66,data:frag},sender);
    assert.equal(result.ok,false);assert.ok(h.manager.recording.gaps.some(g=>g.detail.includes('reassembly_budget_exceeded')));await h.manager.stop();
    await h.manager.start(h.command([1]));await h.settled();await h.manager.journal.flush();const t=h.manager.targets.get(1)!;h.manager.recording.policy.budgets.hardBytes=h.manager.recording.bytesAccepted+10;
    assert.equal(h.manager.write(h.manager.token(t,'runtime'),'browser.console',{args:['budget']}),null);await h.manager.stop();assert.ok(h.manager.recording.gaps.some(g=>g.code==='hard_budget_reached'));assert.equal(t.accepting,false);
    await h.manager.start(h.command([1]));await h.settled();await h.manager.journal.flush();h.manager.recording.policy.budgets.queueBytes=10;const target=h.manager.targets.get(1)!;
    assert.equal(h.manager.write(h.manager.token(target,'runtime'),'browser.console',{args:['queue']}),null);h.manager.recording.policy.budgets.queueBytes=1024*1024;await h.manager.stop();assert.equal(target.accepting,false);assert.ok(h.manager.recording.gaps.some(g=>g.code==='acceptance_queue_failure'));
    assert.ok(h.manager.recording.gaps.some(g=>g.code==='control_queue_failure'));
    h.manager.control('capture.test_after_queue_failure', { reason: 'no_dropped_sequence_reuse' }); await h.manager.journal.flush();
    assert.equal((await validatePackage((await createPackage(await h.manager.db.bundle(h.manager.recording.recordingId))).zip)).valid,true);
  }finally{await h.close();}
});

test('6.3 启动失败的终结写入重试仍保留 FAILED，不改成成功就绪',async()=>{
 const h=await setup();try{await h.manager.start(h.command([1]));await h.settled();await h.manager.journal.flush();const original=h.manager.db.saveBatch.bind(h.manager.db);let fail=true;h.manager.db.saveBatch=async(...args)=>{if(fail){fail=false;throw new DOMException('quota','QuotaExceededError');}await original(...args);};await assert.rejects(h.manager.stop('all_channels_failed','FAILED'));await h.manager.retrySave();assert.equal(h.manager.recording.state,'FAILED');assert.equal((await h.manager.db.bundle(h.manager.recording.recordingId)).recording.state,'FAILED');}finally{await h.close();}
});

test('7.4 两种正式 replacement 通知并发只登记一个新实例，迟到旧移除不停止新实例', async () => {
  const h = await setup();
  try {
    await h.manager.start(h.command([1])); await h.settled(); const old = h.manager.targets.get(1)!;
    const original = chrome.tabs.get; let release!: (tab: chrome.tabs.Tab) => void; let reads = 0;
    chrome.tabs.get = ((id: number) => id === 2 ? (reads++, new Promise<chrome.tabs.Tab>(r => { release = r; })) : original(id)) as typeof chrome.tabs.get;
    const first = h.manager.replaced(2, 1); const duplicate = h.manager.replaced(2, 1);
    await h.settled(); assert.equal(reads, 1);
    release({ id: 2, windowId: 1, url: 'http://host1.test/' } as chrome.tabs.Tab); await Promise.all([first, duplicate]); await h.settled();
    h.manager.closed(1); const next = h.manager.targets.get(2)!;
    assert.equal(old.lifecycle, 'REPLACED'); assert.equal(next.replacesTabInstanceId, old.tabInstanceId); assert.equal(next.accepting, true);
    await h.manager.journal.flush(); const b = await h.manager.db.bundle(h.manager.recording.recordingId);
    assert.equal(b.targets.filter(t => t.browserTabId === 2).length, 1); assert.equal(b.chunks.flatMap(c => c.events).filter(e => e.kind === 'lifecycle.tab_replaced').length, 1);
  } finally { await h.close(); }
});

test('7.4 attach 等待期间导航完成仍会再次检查新文档，截止后不补注入', async () => {
  const h = await setup(); let release!: () => void; let frameReads = 0;
  try {
    chrome.debugger.attach = (() => new Promise<void>(r => { release = r; })) as typeof chrome.debugger.attach;
    chrome.webNavigation.getAllFrames = (async () => { frameReads++; return []; }) as typeof chrome.webNavigation.getAllFrames;
    await h.manager.start(h.command([1])); await h.settled(); assert.equal(frameReads, 1);
    await h.manager.updated(1, { status: 'complete' }); await h.manager.updated(1, { discarded: false });
    release(); await h.settled(); assert.equal(frameReads, 2);
    await h.settled(); assert.equal(frameReads, 2); // 合并为一次补查，不自行轮询。
    await h.manager.stop(); await h.manager.updated(1, { status: 'complete' }); await h.settled(); assert.equal(frameReads, 2);
  } finally { await h.close(); }
});

test('7.6 同一 browserTabId 重新纳入后旧 ticket/分片不能冒充新实例', async () => {
  const h = await setup();
  try {
    const cmd = h.command([1]); await h.manager.start(cmd); await h.settled();
    const sender = { tab: { id: 1 }, frameId: 0, documentId: 'doc-1-0', url: 'http://host1.test/' } as chrome.runtime.MessageSender;
    const oldTicket = (await h.manager.handshake(sender))!; const oldTarget = h.manager.targets.get(1)!;
    const fragment = (ticketId: string, seq: number, kind: string, payload: object) => ({ type: 'capture.batch' as const, ticketId, packetId: seq, index: 0, total: 1, data: JSON.stringify({ seq, kind, sourceTime: seq, payload }) });
    h.manager.capture(fragment(oldTicket.id, 1, 'capture.page_diagnostic', { code: 'semantic_started' }), sender);
    h.manager.closed(1); await h.settled();
    await h.manager.addRoot({ recordingId: cmd.recordingId, commandId: crypto.randomUUID(), browserTabId: 1, scopeVersion: h.manager.recording.scopeVersion }); await h.settled();
    const freshTicket = (await h.manager.handshake(sender))!; assert.notEqual(freshTicket.id, oldTicket.id); assert.notEqual(h.manager.targets.get(1)!.tabInstanceId, oldTarget.tabInstanceId);
    assert.equal(h.manager.capture(fragment(oldTicket.id, 2, 'ui.observation', { action: 'input', after: { value: 'REUSED_TAB_OLD_TICKET' } }), sender).ok, false);
    assert.equal(h.manager.capture(fragment(freshTicket.id, 1, 'capture.page_diagnostic', { code: 'semantic_started' }), sender).ok, true);
    await h.manager.stop(); assert.ok(!JSON.stringify(await h.manager.db.bundle(cmd.recordingId)).includes('REUSED_TAB_OLD_TICKET'));
  } finally { await h.close(); }
});

test('多站点共享环境，添加其他环境后分别保留采集范围', async () => {
  const h = await setup();
  try {
    const command = h.command([1, 2, 3]);
    const environments = {'http://host1.test': 'qa', 'http://host2.test': 'qa', 'http://host3.test': 'prod'};
    await h.manager.start({...command, rootBrowserTabIds: [1, 2], environments});
    assert.equal(h.manager.recording.environmentId, 'qa');
    await h.manager.addRoot({
      recordingId: command.recordingId, commandId: crypto.randomUUID(),
      scopeVersion: h.manager.recording.scopeVersion, browserTabId: 3, environments,
    });
    assert.equal(h.manager.recording.environmentId, '');
    assert.deepEqual(h.manager.recording.rootEnvironments, environments);
  } finally { await h.close(); }
});
