import 'fake-indexeddb/auto';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import test from 'node:test';
import { PlatformError } from '../extension/ui/agent-answer';
import { EvidenceDB } from '../extension/storage/database';
import {
  canonicalManifest,
  prepareRecording,
  uploadRecording,
} from '../extension/ui/recording-upload';
import type { BlobRecord, NetworkRecord } from '../shared/contracts';
import { recording } from './helpers';

const origin = 'http://agent.test:8080';

test('比较本地清单时忽略 Chrome 存储改变的对象键顺序，只重传缺片', async (t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'chrome');
  Object.defineProperty(globalThis, 'chrome', {
    configurable: true,
    value: {
      storage: {
        local: {
          get: async () => ({
            agentPlatformOrigins: ['https://prior-agent.test'],
          }),
        },
      },
    },
  });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'chrome', previous);
    else Reflect.deleteProperty(globalThis, 'chrome');
  });
  const db = new EvidenceDB(),
    rec = recording();
  rec.state = 'READY';
  const records: NetworkRecord[] = [],
    blobs: BlobRecord[] = [];
  for (let n = 0; n < 5; n++) {
    const key = 'net:' + n,
      id = 'synthetic-' + n,
      path = 'bodies/' + id + '.json';
    const requestUrl =
      n === 4
        ? 'https://prior-agent.test/api/browser-extension/applications'
        : 'http://mes.test/new/path';
    records.push({
      recordingId: rec.recordingId,
      requestKey: key,
      startedAt: rec.startedAt,
      actionCandidates: [],
      networkOutcome: 'finished',
      businessOutcome: 'failure',
      businessCode: 'DEMO_REJECTED',
      request: {
        url: requestUrl,
        method: 'POST',
        bodyCaptureStatus: 'empty',
        headers: { 'X-Arbitrary-Header': 'synthetic-private-marker' },
      },
      response: {
        httpStatus: 200,
        bodyCaptureStatus: n === 3 ? 'unavailable' : 'captured',
        bodyRef: path,
        headers: {},
      },
    } as unknown as NetworkRecord);
    blobs.push({
      id,
      recordingId: rec.recordingId,
      path,
      mime: 'application/json',
      encoding: 'utf8',
      data: JSON.stringify({
        newObject: { items: [{ count: 3 }] },
        sample: 'z'.repeat(350000),
        password: 'synthetic-private-marker',
        note: '{"private":"synthetic-private-marker"}',
      }),
    });
  }
  await db.saveBatch(rec, [], [], blobs, records);
  const signal = new AbortController().signal;
  const projection = await prepareRecording(db, rec, origin, signal);
  const { manifest } = projection;
  assert.equal(manifest.coverage.requests.saved, 5);
  assert.equal(manifest.coverage.requests.shareable, 4);
  assert.equal(manifest.coverage.requests.platform_excluded, 1);
  assert.equal(
    manifest.coverage.requests.ids_sha256,
    createHash('sha256').update('net:0\nnet:1\nnet:2\nnet:3\n').digest('hex'),
  );
  assert.equal(manifest.parts.length, 2);
  const stored = JSON.parse(canonicalManifest(manifest));
  assert.notEqual(JSON.stringify(stored), JSON.stringify(manifest));
  assert.equal(canonicalManifest(stored), canonicalManifest(manifest));
  const received = new Set<number>(),
    uploads: number[] = [];
  let ready = false,
    initCount = 0;
  const request = async (path: string, opts: RequestInit) => {
    if (path.endsWith('/recordings')) {
      initCount++;
      assert.equal(
        JSON.parse(String(opts.body)).upload_attempt_id,
        'same-attempt',
      );
      return Response.json({
        recording_id: 'r',
        state: ready ? 'ready' : 'uploading',
        missing_parts: [0, 1].filter((i) => !received.has(i)),
      });
    }
    if (path.endsWith('/complete')) {
      assert.equal(received.size, 2);
      ready = true;
      return Response.json({ recording_id: 'r', state: 'ready' });
    }
    const num = Number(path.split('/').at(-1));
    const raw = gunzipSync(Buffer.from(opts.body as ArrayBuffer));
    const digest = createHash('sha256').update(raw).digest('hex');
    assert.equal(digest, manifest.parts[num]!.sha256);
    assert.ok(!raw.includes('synthetic-private-marker'));
    const rows = raw
      .toString()
      .trimEnd()
      .split('\n')
      .map((s) => JSON.parse(s));
    for (const row of rows) {
      assert.equal(row.path_template, null);
      assert.equal(row.http_status, 200);
      if (row.requestKey === 'net:3') {
        assert.equal(row.response_capture, 'unavailable');
        assert.equal(row.response_details.omissions[0].reason, 'not_captured');
      } else {
        assert.equal(row.response_code, 'DEMO_REJECTED');
        assert.equal(
          row.response_details.value.body.newObject.items[0].count,
          3,
        );
        assert.ok(
          row.response_details.omissions.some(
            (o: { reason: string }) => o.reason === 'unstructured',
          ),
        );
      }
    }
    uploads.push(num);
    received.add(num);
    if (num === 0) throw new TypeError('synthetic interrupted response');
    return Response.json({ recording_id: 'r', number: num, sha256: digest });
  };
  const upload = () =>
    uploadRecording(
      projection,
      'app',
      'scope',
      'same-attempt',
      request,
      signal,
      () => {},
    );
  assert.equal(await upload(), 'r');
  assert.deepEqual(uploads, [0, 1]);
  assert.equal(await upload(), 'r');
  assert.deepEqual(uploads, [0, 1]);
  assert.equal(initCount, 3);
});

test('上传期间遇到范围改变、冲突、超限或暂存到期后停止写入', async () => {
  const manifest = JSON.parse(
    await readFile(
      new URL(
        '../../contracts/browser-extension/v1/golden/init-a.json',
        import.meta.url,
      ),
      'utf8',
    ),
  ).manifest;
  const signal = new AbortController().signal;
  const prepared = { manifest, samples: [], parts: async function* () {} };
  for (const [status, code] of [
    [409, 'scope_changed'],
    [409, 'manifest_conflict'],
    [413, 'quota_exceeded'],
    [410, 'upload_expired'],
  ] as const) {
    let calls = 0;
    await assert.rejects(
      uploadRecording(
        prepared,
        'app',
        'scope',
        'attempt',
        async () => {
          calls++;
          throw new PlatformError(status, code);
        },
        signal,
        () => {},
      ),
      { code },
    );
    assert.equal(calls, 1);
  }
  let reads = 0;
  await assert.rejects(
    uploadRecording(
      prepared,
      'app',
      'scope',
      'attempt',
      async () => {
        reads++;
        return Response.json({
          recording_id: 'r',
          state: 'uploading',
          missing_parts: [0],
        });
      },
      signal,
      () => {},
    ),
    /数量/,
  );
  assert.equal(reads, 1);
  let round = 0;
  await assert.rejects(
    uploadRecording(
      prepared,
      'app',
      'scope',
      'attempt',
      async (path) => {
        if (path.endsWith('/complete')) throw new TypeError('回执中断');
        return Response.json({
          recording_id: ++round === 1 ? 'original' : 'replacement',
          state: round === 1 ? 'uploading' : 'ready',
          missing_parts: [],
        });
      },
      signal,
      () => {},
    ),
    /回执无效/,
  );
  assert.equal(round, 2);
});
