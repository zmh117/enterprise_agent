import test from 'node:test';
import assert from 'node:assert/strict';
import 'fake-indexeddb/auto';
import { LiveNetwork } from '../extension/background/live-network';
import { EvidenceDB } from '../extension/storage/database';
import { LiveDB, saveLiveEvidence, recoverLiveRequests } from '../extension/storage/live-evidence';
import { DEFAULT_POLICY } from '../shared/policy';

const original = { tab_id: 'tab-c', document_id: 'doc-a', binding_id: 'mix', revision: 1 };
test('公共接口按已验证文档冻结归属，延迟响应、正文和超限结果均沿用原请求', async () => {
  const max = 32 * 1024 * 1024,
    url = 'https://mes.invalid/C',
    frame = { id: 'top', loaderId: 'loader', url };
  const policy = {
    ...DEFAULT_POLICY,
    apiRules: [{ origin: 'https://api.invalid', pathPrefix: '/common' }],
    budgets: { ...DEFAULT_POLICY.budgets, bodyBytes: max, queueBytes: 96 * 1024 * 1024 },
  };
  let reads = 0,
    scope: typeof original | undefined = original;
  const events: { source: typeof original; event: Record<string, unknown> }[] = [];
  let config: Record<string, unknown> | undefined;
  const stub = {
    runtime: { id: 'extension' },
    debugger: {
      attach: async () => {},
      detach: async () => {},
      sendCommand: async (_: unknown, method: string, params: Record<string, unknown>) => {
        if (method === 'Page.getFrameTree') return { frameTree: { frame } };
        if (method === 'Runtime.evaluate') return { result: { value: 'ticket' } };
        if (method === 'Network.enable') config = params;
        if (method === 'Network.getResponseBody') {
          reads++;
          return { body: '{"workOrder":"W-SYN","batch":"B-SYN"}', base64Encoded: false };
        }
      },
    },
  };
  Object.assign(globalThis, { chrome: stub });
  const n = new LiveNetwork(
    policy,
    (_id, ticket, docUrl) => (ticket === 'ticket' && docUrl === url ? scope : undefined),
    (_id, source, event) => events.push({ source, event }),
    () => {},
  );
  await n.attach(1);
  const send = (name: string, p: Record<string, unknown>) => n.event({ tabId: 1 }, name, p);
  send('Runtime.executionContextCreated', {
    context: {
      id: 7,
      origin: 'chrome-extension://extension',
      auxData: { isDefault: false, frameId: 'top' },
    },
  });
  await n.verify(1);
  assert.ok(n.status(1).mapped);
  assert.equal(config?.maxTotalBufferSize, max);
  function request(id: string, frameId = 'top') {
    send('Network.requestWillBeSent', {
      requestId: id,
      type: 'Fetch',
      frameId,
      loaderId: 'loader',
      documentURL: url,
      request: { url: 'https://api.invalid/common', method: 'GET' },
    });
  }
  request('one');
  request('two');
  request('unproven', 'other-frame');
  scope = undefined;
  request('after-pause');
  for (const id of ['one', 'two', 'unproven', 'after-pause']) {
    send('Network.responseReceived', {
      requestId: id,
      response: { status: 200, mimeType: 'application/json', headers: {} },
    });
    send('Network.dataReceived', { requestId: id, dataLength: id === 'two' ? max + 1 : 32 });
    send('Network.loadingFinished', { requestId: id });
  }
  await new Promise<void>((r) => setImmediate(r));
  assert.equal(reads, 1);
  assert.equal(events.filter((e) => e.event.kind === 'request').length, 2);
  assert.ok(events.every((e) => e.source.binding_id === 'mix' && e.source.document_id === 'doc-a'));
  assert.deepEqual(
    events
      .filter((e) => e.event.kind === 'body')
      .map((e) => e.event.status)
      .sort(),
    ['captured', 'over_limit'],
  );
  await n.stop(1);
});
test('Worker 重启按原标签标记中断，仅持续队列保存原值，配额失败整批回滚', async () => {
  const db = new LiveDB(),
    rid = crypto.randomUUID();
  const d = {
    origin: 'https://example.invalid',
    account: 'synthetic',
    app: 'test',
    scopeRef: 'test',
  };
  const event = { kind: 'request', request_key: 'fixed' };
  await saveLiveEvidence(db, rid, d, original, event, 4096);
  await assert.rejects(
    saveLiveEvidence(db, rid, { ...d, account: 'second' }, original, event, 4096),
  );
  await assert.rejects(
    saveLiveEvidence(db, rid, d, original, { kind: 'body', value: 'x'.repeat(4096) }, 4096),
  );
  await recoverLiveRequests(db, rid, d, 4096);
  await recoverLiveRequests(db, rid, d, 4096);
  const conn = await db.open();
  const rows = await new Promise<any[]>((ok, fail) => {
    const q = conn
      .transaction('liveEvidence')
      .objectStore('liveEvidence')
      .index('recordingId')
      .getAll(rid);
    q.onsuccess = () => ok(q.result);
    q.onerror = () => fail(q.error);
  });
  assert.equal(rows.length, 2);
  assert.ok(
    rows.every(
      (e) =>
        e.source.binding_id === 'mix' &&
        e.delivery === 'pending' &&
        e.event.request_key === 'fixed',
    ),
  );
  assert.ok(rows.some((e) => e.event.outcome === 'worker_restarted'));
  assert.equal(await new EvidenceDB().getRecording(rid), undefined);
});
