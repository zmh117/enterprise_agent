import test from 'node:test';
import assert from 'node:assert/strict';
import 'fake-indexeddb/auto';
import {
  LiveDB,
  result,
  saveLiveEvidence,
  committed,
  type LiveEntry,
  partBytes,
} from '../extension/storage/live-evidence';
import { LiveDelivery } from '../extension/background/live-delivery';
import { sha256 } from '../extension/storage/database';

test('持续采集分片的离线恢复、调度、已转发和已核对均保留文档来源及可恢复原文', async () => {
  const db = new LiveDB(),
    connection = await db.open();
  const d = {
    origin: 'https://example.invalid',
    account: 'qa-' + crypto.randomUUID(),
    app: 'app',
    scopeRef: 'scope',
  };
  const source = { tab_id: 'tab-C', document_id: 'doc-A', binding_id: 'mix', revision: 1 };
  const rec = crypto.randomUUID();
  const big = {
    kind: 'body',
    side: 'response',
    request_key: 'fixed',
    status: 'captured',
    value: { order: '合成批次'.repeat(35000) },
  };
  const baseline = {
    kind: 'baseline',
    nodes: Array.from({ length: 12000 }, (_, id) => ({ id, type: 3, textContent: '' })),
  };
  for (const event of [big, baseline, { kind: 'action', action: 'click', node_id: 7 }])
    await saveLiveEvidence(db, rec, d, source, event, 8 * 1024 * 1024);
  const rows = () =>
    result<LiveEntry[]>(
      connection
        .transaction('liveEvidence')
        .objectStore('liveEvidence')
        .index('recordingId')
        .getAll(rec),
    );
  const offline = new LiveDelivery(db, async () => {
    throw new Error('offline');
  });
  await offline.flush(d, 1);
  const failed = (await rows()).find((e) => e.failures > 0)!;
  assert.equal(failed.event.kind, 'action');
  assert.equal(failed.nextPart, 0);
  assert.equal(failed.delivery, 'pending');
  const release = async () => {
    const all = await rows();
    const tx = connection.transaction('liveEvidence', 'readwrite'),
      done = committed(tx);
    for (const e of all) tx.objectStore('liveEvidence').put({ ...e, nextTry: 0 });
    await done;
  };
  await release();
  const stored = new Map<string, Map<number, Uint8Array>>(),
    emitted: string[] = [];
  let allowRead = false,
    missingReturned = false;
  const worker = new LiveDelivery(new LiveDB(), async (dest, path, data: any) => {
    assert.deepEqual(dest, d);
    assert.equal(data.recording_id, rec);
    assert.deepEqual(data.source, source);
    if (path.endsWith('/verify')) {
      if (!allowRead) {
        missingReturned = true;
        return { next: data.first, digests: [], visible: false };
      }
      const chunks = stored.get(data.event_id)!;
      const slices = Array.from({ length: Math.min(8, chunks.size - data.first) }, (_, i) =>
        chunks.get(data.first + i)!,
      );
      return {
        visible: true,
        next: data.first + slices.length,
        digests: await Promise.all(slices.map((s) => sha256(s))),
      };
    }
    assert.ok(new TextEncoder().encode(JSON.stringify(data)).length <= 512 * 1024);
    for (const part of data.parts) {
      emitted.push(part.kind);
      assert.ok(new TextEncoder().encode(JSON.stringify(part)).length < 64 * 1024);
      const bytes = Uint8Array.from(atob(part.data), (c) => c.charCodeAt(0));
      assert.ok(bytes.length <= partBytes);
      const map = stored.get(part.event_id) ?? new Map();
      if (map.has(part.number)) assert.deepEqual(map.get(part.number), bytes);
      map.set(part.number, bytes);
      stored.set(part.event_id, map);
    }
    return { accepted: data.parts.length, delivery: 'forwarded' };
  });
  await worker.flush({ ...d, account: 'other' });
  assert.equal(emitted.length, 0);
  await worker.flush(d, 1);
  assert.equal(emitted[0], 'action');
  assert.ok((await rows()).some((e) => e.delivery === 'acknowledged'));
  await worker.flush(d, 15);
  assert.ok(missingReturned);
  allowRead = true;
  await release();
  await worker.flush(d, 32);
  for (const entry of await rows()) {
    assert.equal(entry.delivery, 'verified');
    const pieces = await result<{ data: Uint8Array }[]>(
      connection
        .transaction('liveParts')
        .objectStore('liveParts')
        .getAll(IDBKeyRange.bound([entry.id, 0], [entry.id, entry.count - 1])),
    );
    const logical = Buffer.concat(pieces.map((p) => p.data));
    assert.equal(logical.length, entry.length);
    assert.equal(await sha256(logical), entry.digest);
    if (entry.event.kind === 'body') assert.deepEqual(JSON.parse(logical.toString()), big);
  }
});

test('空间不足时仅回收本场已从 Loki 核对的对象，保留已转发待核对材料', async () => {
  const db = new LiveDB(),
    conn = await db.open(),
    rec = crypto.randomUUID();
  const source = { tab_id: 'c', document_id: 'doc', binding_id: 'mix', revision: 1 };
  const d = { origin: 'https://example.invalid', account: 'quota', app: 'app', scopeRef: 'scope' };
  const body = { kind: 'body', value: 'x'.repeat(5000) };
  await saveLiveEvidence(db, rec, d, source, body, 12000);
  await saveLiveEvidence(db, rec, d, source, body, 12000);
  const read = () =>
    result<LiveEntry[]>(
      conn.transaction('liveEvidence').objectStore('liveEvidence').index('recordingId').getAll(rec),
    );
  const [verified, ack] = await read();
  const tx = conn.transaction('liveEvidence', 'readwrite'),
    done = committed(tx);
  tx.objectStore('liveEvidence').put({ ...verified, delivery: 'verified' });
  tx.objectStore('liveEvidence').put({ ...ack, delivery: 'acknowledged' });
  await done;
  await saveLiveEvidence(db, rec, d, source, body, 12000);
  assert.equal((await read()).length, 2);
  assert.ok((await read()).some((r) => r.id === ack!.id));
  const parts = conn.transaction('liveParts').objectStore('liveParts');
  const [removed, retained] = await Promise.all(
    [verified, ack].map((e) => result(parts.get([e!.id, 0]))),
  );
  assert.equal(removed, undefined);
  assert.ok(retained);
  await assert.rejects(saveLiveEvidence(db, rec, d, source, body, 12000), /live_storage_full/);
});
