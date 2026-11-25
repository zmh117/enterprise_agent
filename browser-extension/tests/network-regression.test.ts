import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BodyQueue, NetworkCollector, type CaptureHost } from '../extension/background/cdp/network';
import { spawnSync } from 'node:child_process';
import { DebuggerManager, type DebugHost } from '../extension/background/cdp/manager';
import { CaptureGate, newTarget } from '../extension/background/session/gate';
import { sanitizeBody } from '../shared/redaction';
import type { BlobRecord, NetworkRecord } from '../shared/contracts';
import { recording } from './helpers';

const tick = () => new Promise<void>(resolve => setImmediate(resolve));
function capture(send: (method: string, params?: any) => Promise<any> = async () => ({ body: '{"code":"OK"}' })) {
  const r = recording(); const target = newTarget(r, { id: 42, windowId: 1 }, 1, 'start', 'root');
  const gate = new CaptureGate(r, new Map([[42, target]]));
  const saved = new Map<string, NetworkRecord>(); const blobs: BlobRecord[] = []; const gaps: { code: string; detail: string }[] = [];
  const host: CaptureHost = {
    recording: r, valid: token => gate.allows(token),
    write(token, _kind, _payload, _meta, record, b) {
      if (!gate.allows(token)) return null;
      if (record) saved.set(record.requestKey, structuredClone(record));
      blobs.push(...(b ?? [])); return 'accepted';
    },
    diagnostic(code, detail) { gaps.push({ code, detail }); },
    finalizeNetwork(_t, record) { saved.set(record.requestKey, structuredClone(record)); }, late() {},
  };
  return { r, target, gate, host, saved, blobs, gaps, n: new NetworkCollector(host, target, gate.token(target, 'network'), 'debug', send) };
}
function request(id = '1', extra: any = {}) {
  return { requestId: id, frameId: 'frame', loaderId: 'loader', documentURL: 'http://mes.test/page', type: 'Fetch', request: { method: 'GET', url: 'http://mes.test/api/test', headers: {} }, ...extra };
}
function response(id = '1', hasExtraInfo: boolean | undefined = false, extra: any = {}) {
  return { requestId: id, hasExtraInfo, response: { status: 200, mimeType: 'application/json', headers: {}, ...extra } };
}

test('9.1/9.5 text/plain 双侧保留原值，仅密码掩码；超限仍排除', async () => {
  const raw = JSON.stringify([{ precision: '3.00', token: 'OPAQUE_REQUEST_SENTINEL', nested: { password: 'OTHER_SENTINEL' } }]);
  const h = capture(async () => ({ body: raw }));
  h.n.event('Network.requestWillBeSent', request('1', { request: { method: 'POST', url: 'http://mes.test/api/test', headers: { 'Content-Type': 'text/plain;charset=UTF-8' }, postData: raw, hasPostData: true } }));
  h.n.event('Network.responseReceived', response('1', false, { mimeType: 'text/plain' }));
  h.n.event('Network.loadingFinished', { requestId: '1' }); await tick();
  const record = [...h.saved.values()][0]!;
  assert.equal(record.request.headers['content-type'], 'text/plain;charset=UTF-8');
  assert.equal(record.request.bodyCaptureStatus, 'captured'); assert.equal(record.response.bodyCaptureStatus, 'captured');
  assert.equal(h.blobs.length, 2);
  for (const b of h.blobs) { assert.match(b.path, /\.json$/); assert.equal(b.mime, 'application/json'); assert.equal(JSON.parse(String(b.data))[0].precision, '3.00'); }
  assert.ok(JSON.stringify(h.blobs).includes('OPAQUE_REQUEST_SENTINEL')); assert.ok(!JSON.stringify(h.blobs).includes('OTHER_SENTINEL'));
  for (const raw of ['free private text', '"private scalar"', 'null', '42', 'true', '{"token":', '[1] trailing']) {
    const result = sanitizeBody(raw, 'text/plain', h.r.policy);
    assert.equal(result.fields.bodyCaptureStatus, 'captured'); assert.equal(result.content, raw);
  }
  assert.equal(sanitizeBody(JSON.stringify({ value: 'x'.repeat(h.r.policy.budgets.bodyBytes) }), 'text/plain', h.r.policy).fields.bodyCaptureReason, 'body_size_limit_no_partial_json');
});

test('9.1 压缩响应按解码后字节排除，跳过正文读取且保留真实字节数', async () => {
  let calls = 0; const h = capture(async () => { calls++; throw Error('should not read'); });
  h.n.event('Network.requestWillBeSent', request());
  h.n.event('Network.responseReceived', response('1', false, { headers: { 'content-encoding': 'gzip', 'content-length': '342232' } }));
  for (const dataLength of [700000, 718112]) h.n.event('Network.dataReceived', { requestId: '1', dataLength });
  h.n.event('Network.loadingFinished', { requestId: '1', encodedDataLength: 342232 }); await tick();
  const r = [...h.saved.values()][0]!;
  assert.equal(calls, 0); assert.equal(r.response.bodyCaptureStatus, 'excluded_by_policy');
  assert.equal(r.response.bodyCaptureReason, 'decoded_body_size_limit'); assert.equal(r.response.originalBytes, 1418112);
  assert.equal(r.response.savedBytes, 0); assert.equal(r.response.bodyRef, null); assert.equal(h.blobs.length, 0);
});

test('9.1/9.5 精确识别 XSSI JSON 前缀、保留普通字段并保护密码，不执行脚本包装', () => {
  const p = recording().policy;
  for (const prefix of [")]}'\n", ")]}'\r\n"]) {
    const raw = prefix + JSON.stringify([{ token: 'KEEP_TOKEN', pass: 'HIDE_PASSWORD', precision: '3.00' }]);
    const result = sanitizeBody(raw, 'application/json', p);
    assert.equal(result.fields.bodyCaptureStatus, 'captured');
    assert.deepEqual(JSON.parse(result.content!), [{ token: 'KEEP_TOKEN', pass: '[REDACTED]', precision: '3.00' }]);
    assert.equal(result.fields.originalBytes, Buffer.byteLength(raw));
  }
  assert.equal(sanitizeBody('while(1);{"token":"x"}', 'application/json', p).fields.bodyCaptureStatus, 'excluded_by_policy');
  const form = 'token=KEEP%2Bvalue&tag=one&tag=two&password=HIDE_PASSWORD';
  const body = new URLSearchParams(sanitizeBody(form, 'application/x-www-form-urlencoded', p).content);
  assert.deepEqual(body.getAll('tag'), ['one', 'two']); assert.equal(body.get('token'), 'KEEP+value'); assert.equal(body.get('password'), '[REDACTED]');
});

test('9.1 读取、缓存淘汰、资源消失、结果类型和编码错误分别可诊断，不保存原始异常秘密', async () => {
  const cases = [
    { error: 'Request content was evicted from inspector cache SECRET', reason: 'inspector_cache_evicted' },
    { error: 'No resource with given identifier found SECRET', reason: 'response_resource_unavailable' },
    { error: 'other SECRET', reason: 'getResponseBody_failed' },
    { value: { body: '/w==', base64Encoded: true }, reason: 'invalid_response_body_encoding' },
    { value: { body: '*invalid*', base64Encoded: true }, reason: 'invalid_response_body_encoding' },
    { value: { body: null }, reason: 'invalid_response_body_result' },
  ];
  for (const c of cases) {
    let calls = 0; const h = capture(async () => { calls++; if (c.error) throw Error(c.error); return c.value; });
    h.n.event('Network.requestWillBeSent', request()); h.n.event('Network.responseReceived', response());
    h.n.event('Network.loadingFinished', { requestId: '1' }); await tick();
    const r = [...h.saved.values()][0]!;
    assert.equal(r.response.bodyCaptureReason, c.reason); assert.equal(r.response.bodyRef, null);
    assert.equal(calls, 1); assert.equal(h.blobs.length, 0); assert.ok(!JSON.stringify(r).includes('SECRET'));
  }
});

test('9.3 无 ExtraInfo 请求在保存和停止后均为 not_expected；未知标志保持 unresolved', () => {
  const h = capture();
  for (const [id, flag] of [['sw', false], ['unknown', undefined], ['missing', true]] as const) {
    h.n.event('Network.requestWillBeSent', request(id));
    h.n.event('Network.responseReceived', { ...response(id), hasExtraInfo: flag });
  }
  assert.equal([...h.saved.values()].find(r => r.cdpRequestId === 'sw')!.extraInfoStatus, 'not_expected');
  h.gate.stopAll('session_stopped', 2); h.n.stop('session_stopped');
  for (const r of h.saved.values()) assert.equal(r.extraInfoStatus, r.cdpRequestId === 'sw' ? 'not_expected' : 'unresolved_at_cutoff');
});

test('9.1/9.5 长连续文本处理不阻塞后台，保留 token 并保护密码', () => {
  // Isolate the synchronous regex: a test-runner timeout cannot interrupt backtracking.
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    import { cleanText } from './shared/redaction.ts';
    for (const text of ['x'.repeat(2 * 1024 * 1024), '-'.repeat(2 * 1024 * 1024)]) {
      assert.equal(cleanText(text), text);
      assert.ok(cleanText(text + ' custom-access-token=PRIVATE_VALUE').includes('PRIVATE_VALUE'));
    }
    for (const key of ['password', 'loginPassword', 'passwd', 'pwd'])
      assert.ok(!cleanText(key + '=PRIVATE_VALUE').includes('PRIVATE_VALUE'));
  `], { cwd: process.cwd(), timeout: 5000, encoding: 'utf8' });
  assert.equal(result.error, undefined, '脱敏超过 5 秒或子进程启动失败');
  assert.equal(result.status, 0, result.stderr);
});

test('9.2 排队期间 requestId 被未授权重定向复用，不读取新 hop 的双侧正文', async () => {
  for (const side of ['request', 'response'] as const) {
    let calls = 0; let release!: () => void; const h = capture(); const queue = new BodyQueue(1);
    queue.add('blocker', () => true, () => new Promise<void>(r => { release = r; }), 1);
    const n = new NetworkCollector(h.host, h.target, h.gate.token(h.target, 'network'), 'queued', async () => { calls++; return {}; }, () => null, queue);
    n.event('Network.requestWillBeSent', request('1', { request: { method: 'POST', url: 'http://mes.test/api/test', hasPostData: side === 'request', headers: { 'content-type': 'application/json' } } }));
    if (side === 'response') { n.event('Network.responseReceived', response()); n.event('Network.loadingFinished', { requestId: '1' }); }
    n.event('Network.requestWillBeSent', request('1', { redirectResponse: { status: 307, headers: {} }, redirectHasExtraInfo: false }), false);
    release(); await tick();
    assert.equal(calls, 0); assert.equal(h.blobs.length, 0);
    assert.equal([...h.saved.values()][0]![side].bodyCaptureReason, 'redirect_reused_request_id');
  }
});

test('9.3 混合无额外头、排除 hop 及早晚 ExtraInfo 的重定向链双侧不串位', () => {
  const h = capture(); const emitExtra = (side: 'request' | 'response', hop: string) => h.n.event(side === 'request' ? 'Network.requestWillBeSentExtraInfo' : 'Network.responseReceivedExtraInfo', { requestId: '1', headers: { 'x-hop': hop, Cookie: 'SECRET' } });
  h.n.event('Network.requestWillBeSent', request());
  // Hop 0 served by SW, hop 1 excluded by frame policy, hop 2 authorized.
  h.n.event('Network.requestWillBeSent', request('1', { redirectResponse: { status: 302, headers: {} }, redirectHasExtraInfo: false }), false);
  emitExtra('request', 'excluded'); emitExtra('response', 'excluded');
  h.n.event('Network.requestWillBeSent', request('1', { redirectResponse: { status: 302, headers: {} }, redirectHasExtraInfo: true }));
  emitExtra('response', 'final'); emitExtra('request', 'final');
  h.n.event('Network.responseReceived', response('1', true));
  const records = [...h.saved.values()]; assert.equal(records.length, 2);
  assert.equal(records[0]!.extraInfoStatus, 'not_expected'); assert.equal(records[0]!.request.headers['x-hop'], undefined);
  assert.equal(records[1]!.redirectOrdinal, 2); assert.equal(records[1]!.extraInfoStatus, 'matched_by_protocol_order');
  assert.equal(records[1]!.request.headers['x-hop'], 'final'); assert.equal(records[1]!.response.headers['x-hop'], 'final');
  assert.ok(!JSON.stringify(records).includes('excluded')); assert.equal(records[1]!.request.headers.cookie, 'SECRET');
});

async function managerCase(run: (h: ReturnType<typeof capture> & { manager: DebuggerManager; commands: any[]; permit: { enabled: boolean } }) => Promise<void>) {
  const h = capture(); const previous = (globalThis as any).chrome; const commands: any[] = []; const permit = { enabled: true };
  const host: DebugHost = { ...h.host, token: (t, c) => h.gate.token(t, c), channelReady() {}, channelLost() {},
    permitted: async url => host.permittedKnown(url), permittedKnown: url => permit.enabled && /^http:\/\/mes\.test(?:\/|$)/.test(url),
    documentBinding: () => ({ documentId: 'old-document', chromeFrameId: 0 } as any),
  };
  (globalThis as any).chrome = { runtime: { id: 'collector' }, debugger: { attach: async () => {}, detach: async () => {}, sendCommand: async (_source: any, method: string, params: any) => {
    commands.push({ method, params });
    if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'frame', loaderId: 'old-loader', url: 'http://mes.test/old' } } };
    if (method === 'Runtime.evaluate') return { result: { value: 'valid-ticket' } };
    return {};
  } } };
  const manager = new DebuggerManager(host);
  try { await manager.attach(h.target); await run({ ...h, manager, commands, permit }); }
  finally { await manager.stop(h.target, 'session_stopped'); (globalThis as any).chrome = previous; }
}

test('9.2 新 frame 和导航早期请求按 CDP documentURL 授权，不能借用旧 loader 文档绑定', async () => managerCase(async h => {
  h.manager.event({ tabId: 42 }, 'Runtime.executionContextCreated', { context: { id: 1, origin: 'chrome-extension://collector', auxData: { frameId: 'frame', isDefault: false } } }); await tick();
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('old', { loaderId: 'old-loader' }));
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('navigate', { type: 'Document', loaderId: 'new-loader' }));
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('new-frame', { frameId: 'new-frame' }));
  const rows = [...h.saved.values()]; assert.equal(rows.length, 3);
  assert.equal(rows[0]!.documentId, 'old-document');
  for (const row of rows.slice(1)) { assert.equal(row.documentId, null); assert.equal(row.chromeFrameId, null); }
  assert.equal(h.gaps.length, 0);
}));

test('9.2 未授权文档、无 frame、未知 loader 不能因 API 或缓存 frame 被允许而保存', async () => managerCase(async h => {
  const cases = [
    request('denied', { documentURL: 'https://denied.test/page?token=SECRET' }),
    request('missing', { frameId: undefined }),
    request('unknown', { documentURL: '', loaderId: 'different' }),
  ];
  for (const p of cases) { p.request.postData = '{"token":"BODY_SECRET"}'; h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', p); }
  assert.equal(h.saved.size, 0); assert.equal(h.blobs.length, 0);
  assert.deepEqual(h.gaps.map(g => g.code), ['network_frame_not_authorized', 'network_frame_missing', 'network_frame_unknown']);
  assert.ok(!JSON.stringify(h.gaps).includes('SECRET'));
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('fallback', { documentURL: undefined, loaderId: 'old-loader' }));
  assert.equal(h.saved.size, 1);
  h.permit.enabled = false;
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('revoked'));
  assert.equal(h.saved.size, 1);
  h.gate.stopAll('session_stopped', 3);
  h.permit.enabled = true;
  h.manager.event({ tabId: 42 }, 'Network.requestWillBeSent', request('late'));
  assert.equal(h.saved.size, 1);
}));

test('9.1 Inspector 正文缓冲与配置预算一致', async () => {
  await managerCase(async h => {
    const enabled = h.commands.find(c => c.method === 'Network.enable').params;
    assert.equal(enabled.maxResourceBufferSize, 2 * h.r.policy.budgets.bodyBytes);
    assert.ok(enabled.maxTotalBufferSize >= 4 * h.r.policy.budgets.bodyBytes);
  });
});
