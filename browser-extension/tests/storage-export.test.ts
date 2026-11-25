import 'fake-indexeddb/auto';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EvidenceDB, Journal, sha256 } from '../extension/storage/database';
import { createPackage, validatePackage } from '../extension/export/package';
import { PlatformError } from '../extension/ui/agent-answer';
import { prepareRecording, uploadRecording } from '../extension/ui/recording-upload';
import { recording } from './helpers';
import { newTarget } from '../extension/background/session/gate';
import { now, SCHEMA_VERSION, type EvidenceEvent } from '../shared/contracts';
import { zipSync, unzipSync, strFromU8, strToU8 } from 'fflate';

test('accepted atomic observations persist past cutoff, reopen, export and reference validation', async () => {
  const r = recording(); const t = newTarget(r, { id: 1, windowId: 1 }, 1, 'start', 'root'); const db = new EvidenceDB();
  const event = (seq: number, kind: string, payload: any): EvidenceEvent => ({ schemaVersion: SCHEMA_VERSION, eventId: `stream:${seq}`, recordingId: r.recordingId, browserRunId: r.browserRunId, tabInstanceId: t.tabInstanceId, browserTabId: 1, windowId: 1, emitterContext: null, subjectContext: null, streamId: 'stream', source: 'semantic', sourceSeq: seq, kind, sourceTime: seq, sourceClock: 'document_performance_ms', observedAt: now(), normalizedAt: null, captureGeneration: 1, channel: 'semantic', channelGeneration: 1, payload, quality: { redacted: true, truncated: false, limitations: [] } });
  const journal = new Journal(db, r, () => [t], e => { throw e; });
  journal.append([event(1, 'ui.state_snapshot', { after: { value: 'value' } }), event(2, 'ui.action', { action: 'input', evidenceRefs: ['stream:1'] })]);
  t.accepting = false; t.lifecycle = 'CLOSED'; r.state = 'READY'; r.stoppedAt = now(); await journal.flush();
  const settings = Object.getOwnPropertyDescriptor(globalThis, 'chrome');
  Object.defineProperty(globalThis, 'chrome', {
    configurable: true,
    value: { storage: { local: { get: async () => ({}) } } },
  });
  try {
    const signal = new AbortController().signal;
    const projected = await prepareRecording(
      db,
      r,
      'http://agent.test',
      signal,
    );
    assert.equal(projected.manifest.coverage.actions.shareable, 1);
    await assert.rejects(
      uploadRecording(
        projected,
        'app',
        'scope',
        'attempt',
        async (path) => {
          if (path.endsWith('/recordings'))
            return Response.json({
              recording_id: 'synthetic',
              state: 'uploading',
              missing_parts: [0],
            });
          throw new PlatformError(410, 'upload_expired');
        },
        signal,
        () => {},
      ),
      { code: 'upload_expired' },
    );
  } finally {
    if (settings) Object.defineProperty(globalThis, 'chrome', settings);
    else Reflect.deleteProperty(globalThis, 'chrome');
  }
  const data = await new EvidenceDB().bundle(r.recordingId);
  assert.equal(data.recording.eventsPersisted, 2); assert.equal(data.chunks.length, 1);
  assert.equal(data.chunks[0]!.sha256, await sha256(JSON.stringify(data.chunks[0]!.events)));
  const pkg = await createPackage(data); const result = await validatePackage(pkg.zip); assert.equal(result.events, 2);
  const damaged = unzipSync(pkg.zip); damaged['summary.md'] = strToU8('corrupt'); await assert.rejects(validatePackage(zipSync(damaged)), /校验失败/);
  const missing = structuredClone(data); missing.chunks[0]!.events[1]!.payload.evidenceRefs = ['missing:99']; missing.chunks[0]!.sha256 = await sha256(JSON.stringify(missing.chunks[0]!.events));
  await assert.rejects(createPackage(missing), /悬空 evidenceRef/);
  await db.deleteRecording(r.recordingId); assert.equal(await db.getRecording(r.recordingId), undefined); assert.deepEqual(await db.list('chunks', r.recordingId), []);
});

for (const fault of ['AbortError','QuotaExceededError']) test(`6.3 ${fault} 保留已接受批次并用稳定身份重试，无重复或丢弃`,async()=>{
  const r=recording();const db=new EvidenceDB();const errors:string[]=[];const journal=new Journal(db,r,()=>[],e=>{errors.push(e.name);});
  const event={schemaVersion:SCHEMA_VERSION,eventId:'fault:1',recordingId:r.recordingId,browserRunId:r.browserRunId,tabInstanceId:null,browserTabId:null,windowId:null,emitterContext:null,subjectContext:null,streamId:'fault',source:'extension',sourceSeq:1,kind:'capture.gap',sourceTime:null,sourceClock:'extension_observation',observedAt:now(),normalizedAt:null,captureGeneration:0,channel:'control',channelGeneration:0,payload:{code:'test'},quality:{redacted:true,truncated:false,limitations:[]}} as EvidenceEvent;
  const original=db.saveBatch.bind(db);let fail=true;const identities:string[][]=[];
  db.saveBatch=async(...args)=>{identities.push(args[2].map(c=>c.id));if(fail){fail=false;if(fault==='AbortError'){const raw=await db.open();await new Promise<void>((resolve,reject)=>{const tx=raw.transaction('recordings','readwrite');tx.objectStore('recordings').put(args[0]);tx.onabort=()=>reject(new DOMException('injected abort','AbortError'));tx.abort();});}throw new DOMException('injected quota','QuotaExceededError');}await original(...args);};
  journal.append([event]);await assert.rejects(journal.flush());assert.equal(r.saveState,'error');assert.equal(await db.getRecording(r.recordingId),undefined);assert.equal(journal.metrics().retryableFailure,true);
  await journal.retry();assert.deepEqual(identities[0],identities[1]);assert.equal((await db.bundle(r.recordingId)).recording.eventsPersisted,1);assert.equal((await db.bundle(r.recordingId)).chunks.flatMap(c=>c.events).length,1);
  r.state='READY';journal.touch();await journal.flush();assert.equal((await validatePackage((await createPackage(await db.bundle(r.recordingId))).zip)).valid,true);assert.equal(errors.length,1);await db.deleteRecording(r.recordingId);
});

test('6.2 写事务挂起期间重复 retry 不启动竞争事务，确认后才排空后续批次',async()=>{
  const r=recording();const db=new EvidenceDB();const journal=new Journal(db,r,()=>[],()=>{});let release!:()=>void;let calls=0;let active=0;let peak=0;const original=db.saveBatch.bind(db);
  db.saveBatch=async(...args)=>{calls++;peak=Math.max(peak,++active);if(calls===1)await new Promise<void>(resolve=>{release=resolve;});await original(...args);active--;};
  journal.touch();const writing=journal.flush();for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));
  const retry1=journal.retry(),retry2=journal.retry();journal.touch();await new Promise(r=>setImmediate(r));assert.equal(calls,1);assert.equal(r.saveState,'pending');release();await Promise.all([writing,retry1,retry2]);assert.equal(peak,1);assert.equal(r.saveState,'saved');await db.deleteRecording(r.recordingId);
});

test('6.3 配额失败时只读导出已提交前缀，无需完成失败写入且保留待重试批次',async()=>{
 const {savedPrefix}=await import('../extension/export/package');const r=recording();const db=new EvidenceDB();const journal=new Journal(db,r,()=>[],()=>{});
 journal.touch();await journal.flush();const original=db.saveBatch.bind(db);db.saveBatch=async()=>{throw new DOMException('quota','QuotaExceededError');};journal.touch();await assert.rejects(journal.flush());const batch=journal.metrics().pendingBatch;
 const saved=await db.bundle(r.recordingId);const prefix=savedPrefix(saved,now(),'quota');assert.equal(saved.recording.state,'RECORDING');assert.equal(prefix.recording.state,'INTERRUPTED');assert.ok(prefix.recording.gaps.some(g=>g.code==='saved_prefix_only'));assert.equal((await validatePackage((await createPackage(prefix)).zip)).valid,true);assert.equal(journal.metrics().retryableFailure,true);assert.deepEqual(journal.metrics().pendingBatch,batch);
 db.saveBatch=original;await journal.retry();await db.deleteRecording(r.recordingId);
});

test('历史会话按新格式导出，保留站点环境，移除旧问题描述', async () => {
  const r = Object.assign(recording(), {
    state: 'READY' as const, title: 'legacy-note', expected: 'legacy-note',
    actual: 'legacy-note', frequency: 'legacy-note',
    rootEnvironments: { 'https://sample.test': 'fixture' },
  });
  const { zip, manifest, summary } = await createPackage({ recording: r, targets: [], chunks: [], blobs: [], network: [] });
  assert.equal(manifest.schemaVersion, '4.0.0');
  assert.deepEqual(manifest.recording.rootEnvironments, r.rootEnvironments);
  for (const field of ['title', 'expected', 'actual', 'frequency']) assert.equal(field in manifest.recording, false);
  assert.equal(summary.includes('legacy-note'), false);
  const files = unzipSync(zip);
  files['manifest.json'] = strToU8(JSON.stringify({...manifest, schemaVersion: '3.0.0', recording: r}));
  assert.equal((await validatePackage(zipSync(files))).valid, true);
});
