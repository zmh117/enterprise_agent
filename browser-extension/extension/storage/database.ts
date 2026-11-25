import type { BlobRecord, BundleData, Chunk, EvidenceEvent, NetworkRecord, Recording, Target } from '../../shared/contracts';
import { bytes } from '../../shared/contracts';
export const DB_NAME = 'mes-evidence-v1';
const STORES = ['recordings', 'targets', 'chunks', 'blobs', 'network', 'exports'] as const;
export async function sha256(data: string | Uint8Array): Promise<string> {
  const b = typeof data === 'string' ? new TextEncoder().encode(data) : new Uint8Array(data);
  const hash = await crypto.subtle.digest('SHA-256', b);
  return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, '0')).join('');
}
const req = <T>(r: IDBRequest<T>) => new Promise<T>((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
const done = (tx: IDBTransaction) => new Promise<void>((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onabort = tx.onerror = () => reject(tx.error ?? new Error('IndexedDB transaction aborted')); });
export class EvidenceDB {
  private db?: Promise<IDBDatabase>;
  open() {
    return this.db ??= new Promise<IDBDatabase>((resolve, reject) => {
      const r = indexedDB.open(DB_NAME, 1);
      r.onupgradeneeded = () => {
        for (const name of STORES) {
          const keyPath = name === 'recordings' ? 'recordingId' : name === 'targets' ? 'tabInstanceId' : name === 'network' ? 'requestKey' : 'id';
          const s = r.result.createObjectStore(name, { keyPath });
          if (name !== 'recordings') s.createIndex('recordingId', 'recordingId');
        }
      };
      r.onsuccess = () => { r.result.onversionchange = () => r.result.close(); resolve(r.result); };
      r.onerror = () => reject(r.error);
      r.onblocked = () => reject(new Error('数据库升级被另一个控制页阻塞，请关闭旧控制页'));
    });
  }
  async listRecordings(): Promise<Recording[]> { const db = await this.open(); return req(db.transaction('recordings').objectStore('recordings').getAll()); }
  async getRecording(id: string): Promise<Recording | undefined> { const db = await this.open(); return req(db.transaction('recordings').objectStore('recordings').get(id)); }
  async list<T>(store: Exclude<typeof STORES[number], 'recordings'>, recordingId: string): Promise<T[]> {
    const db = await this.open(); return req(db.transaction(store).objectStore(store).index('recordingId').getAll(recordingId));
  }
  async *recordingKeys(store: 'chunks' | 'network', recordingId: string): AsyncGenerator<string> {
    const db = await this.open();
    let after = '';
    while (true) {
      const page = await new Promise<string[]>((resolve, reject) => {
        const keys: string[] = [];
        const cursor = db.transaction(store).objectStore(store).index('recordingId').openKeyCursor(IDBKeyRange.only(recordingId));
        cursor.onerror = () => reject(cursor.error);
        cursor.onsuccess = () => {
          const current = cursor.result;
          if (!current) return resolve(keys);
          const key = String(current.primaryKey);
          if (key < after) return current.continuePrimaryKey(recordingId, after);
          if (key !== after) keys.push(key);
          if (keys.length === 64) return resolve(keys);
          current.continue();
        };
      });
      for (const key of page) yield key;
      if (page.length < 64) break;
      after = page[page.length - 1]!;
    }
  }
  async recordedItem<T extends { recordingId: string }>(store: 'chunks' | 'network' | 'blobs', id: string, recordingId: string): Promise<T> {
    const db = await this.open();
    const row = await req<T | undefined>(db.transaction(store).objectStore(store).get(id));
    if (!row || row.recordingId !== recordingId) throw new Error('本地录制已变化，请重新预览');
    return row;
  }
  async saveBatch(recording: Recording, targets: Target[], chunks: Chunk[], blobs: BlobRecord[], network: NetworkRecord[]) {
    const db = await this.open();
    const tx = db.transaction(['recordings', 'targets', 'chunks', 'blobs', 'network'], 'readwrite', { durability: 'strict' });
    const complete = done(tx);
    tx.objectStore('recordings').put(recording);
    for (const t of targets) tx.objectStore('targets').put(t);
    for (const c of chunks) tx.objectStore('chunks').put(c);
    for (const b of blobs) tx.objectStore('blobs').put(b);
    for (const n of network) tx.objectStore('network').put(n);
    await complete;
  }
  async bundle(id: string): Promise<BundleData> {
    const recording = await this.getRecording(id);
    if (!recording) throw new Error('找不到该采集会话');
    const [targets, chunks, blobs, network] = await Promise.all([
      this.list<Target>('targets', id), this.list<Chunk>('chunks', id), this.list<BlobRecord>('blobs', id), this.list<NetworkRecord>('network', id),
    ]);
    chunks.sort((a, b) => a.chunkSeq - b.chunkSeq);
    return { recording, targets, chunks, blobs, network };
  }
  async saveExport(id: string, result: Record<string, unknown>, attemptId = id) {
    const db = await this.open(); const tx = db.transaction('exports', 'readwrite'); const complete = done(tx);
    tx.objectStore('exports').put({ ...result, id: attemptId, recordingId: id }); await complete;
  }
  async deleteRecording(id: string) {
    const db = await this.open(); const tx = db.transaction([...STORES], 'readwrite'); const complete = done(tx);
    tx.objectStore('recordings').delete(id);
    for (const name of STORES.filter(x => x !== 'recordings')) {
      const s = tx.objectStore(name); const cursor = s.index('recordingId').openKeyCursor(IDBKeyRange.only(id));
      cursor.onsuccess = () => { const c = cursor.result; if (c) { s.delete(c.primaryKey); c.continue(); } };
    }
    await complete;
  }
}

/** One writer; each committed chunk and its checkpoint share a transaction. */
export class Journal {
  private events: EvidenceEvent[] = [];
  private blobs: BlobRecord[] = [];
  private network = new Map<string, NetworkRecord>();
  private queuedBytes = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private chain: Promise<void> = Promise.resolve();
  private failure?: Error;
  private dirty = false;
  private writing = false;
  private inFlightBytes = 0; private peakBytes = 0;
  private pending?: { snapshot: Recording; targets: Target[]; chunks: Chunk[]; blobs: BlobRecord[]; network: NetworkRecord[]; size: number; eventCount: number };
  constructor(public db: EvidenceDB, public recording: Recording, private targets: () => Target[], private onError: (e: Error) => void) {}

  append(events: EvidenceEvent[], blobs: BlobRecord[] = [], network: NetworkRecord[] = []) {
    if (this.failure) throw this.failure;
    const size = bytes(events) + bytes(blobs) + bytes(network);
    if (this.queuedBytes + this.inFlightBytes + size > this.recording.policy.budgets.queueBytes) throw new Error('persistence_queue_limit');
    this.events.push(...structuredClone(events)); this.blobs.push(...structuredClone(blobs));
    for (const n of network) this.network.set(n.requestKey, structuredClone(n));
    this.queuedBytes += size; this.peakBytes = Math.max(this.peakBytes, this.queuedBytes + this.inFlightBytes); this.recording.bytesAccepted += size; this.touch();
    if (this.queuedBytes >= 256 * 1024) void this.flush().catch(() => {});
  }
  metrics() { return { queuedBytes: this.queuedBytes, inFlightBytes: this.inFlightBytes, peakBytes: this.peakBytes, transactionUnsettled: this.writing, retryableFailure: !!this.failure, pendingBatch: this.pending?.chunks.map(c => c.id) ?? [] }; }
  touch() {
    this.dirty = true; this.recording.saveState = this.failure ? 'error' : 'pending';
    this.timer ??= setTimeout(() => { this.timer = undefined; void this.flush().catch(() => {}); }, 1000);
  }
  flush(): Promise<void> {
    if (this.timer) { clearTimeout(this.timer); this.timer = undefined; }
    this.chain = this.chain.catch(() => {}).then(async () => {
      if (this.failure) throw this.failure;
      if (!this.dirty && !this.pending) return;
      if (!this.pending) {
        const events = this.events.splice(0); const blobs = this.blobs.splice(0); const network = [...this.network.values()]; this.network.clear();
        const size = this.queuedBytes; this.inFlightBytes = size; this.queuedBytes = 0; this.dirty = false;
        const groups = new Map<string, EvidenceEvent[]>();
        for (const e of events) { const a = groups.get(e.streamId) ?? []; a.push(e); groups.set(e.streamId, a); }
        const chunks: Chunk[] = []; let checkpoint = this.recording.checkpoint;
        for (const [streamId, group] of groups) {
          const chunkSeq = ++checkpoint;
          chunks.push({ id: `${this.recording.recordingId}:${chunkSeq}`, recordingId: this.recording.recordingId, browserRunId: this.recording.browserRunId, streamId, chunkSeq,
            firstSeq: group[0]!.sourceSeq, lastSeq: group.at(-1)!.sourceSeq, sha256: await sha256(JSON.stringify(group)), events: group });
        }
        const snapshot = structuredClone(this.recording);
        snapshot.checkpoint = checkpoint; snapshot.bytesPersisted += size; snapshot.eventsPersisted += events.length; snapshot.saveState = 'saved'; delete snapshot.saveError;
        this.pending = { snapshot, targets: structuredClone(this.targets()), chunks, blobs, network, size, eventCount: events.length };
      }
      const batch = this.pending;
      try { this.writing = true; await this.db.saveBatch(batch.snapshot, batch.targets, batch.chunks, batch.blobs, batch.network); }
      catch (e) {
        // Keep this exact immutable batch and IDs. A timeout never starts a competing transaction.
        this.failure = e instanceof Error ? e : new Error(String(e)); this.recording.saveState = 'error'; this.recording.saveError = this.failure.message;
        this.onError(this.failure); throw this.failure;
      } finally { this.writing = false; }
      this.recording.checkpoint = batch.snapshot.checkpoint; this.recording.bytesPersisted = batch.snapshot.bytesPersisted; this.recording.eventsPersisted = batch.snapshot.eventsPersisted;
      this.pending = undefined; this.inFlightBytes = 0; delete this.recording.saveError;
      this.recording.saveState = this.dirty ? 'pending' : 'saved';
    });
    return this.chain;
  }
  async retry() {
    // Wait for the original transaction outcome even if a UI deadline has elapsed.
    await this.chain.catch(() => {}); this.failure = undefined; await this.flush();
    if (this.dirty) await this.flush();
  }
}
