import { bytes } from '../../shared/contracts';
import { sha256 } from './database';
import type { PageSource } from '../../shared/live-page';
export class LiveDB {
  private opening?: Promise<IDBDatabase>;
  open() {
    return (this.opening ??= new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open('mes-workshop-live-v1', 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        const events = db.createObjectStore('liveEvidence', { keyPath: 'id' });
        events.createIndex('recordingId', 'recordingId');
        events.createIndex('progress', ['recordingId', 'delivery']);
        events.createIndex('schedule', ['destinationKey', 'delivery', 'lane', 'nextTry']);
        db.createObjectStore('liveParts', { keyPath: ['id', 'number'] });
        db.createObjectStore('liveRecordings', { keyPath: 'id' });
        db.createObjectStore('liveRequests', { keyPath: ['recordingId', 'key'] }).createIndex(
          'recordingId',
          'recordingId',
        );
      };
      req.onsuccess = () => {
        req.result.onversionchange = () => {
          req.result.close();
          this.opening = undefined;
        };
        resolve(req.result);
      };
      req.onerror = () => {
        this.opening = undefined;
        reject(req.error);
      };
    }));
  }
}

export interface LiveDestination {
  origin: string;
  account: string;
  app: string;
  scopeRef: string;
}
export interface LiveEntry {
  id: string;
  recordingId: string;
  source: PageSource;
  observedAt: number;
  seq: number;
  event: Record<string, unknown>;
  delivery: 'pending' | 'acknowledged' | 'verified';
  destination: LiveDestination;
  destinationKey: string;
  lane: number;
  nextTry: number;
  failures: number;
  nextPart: number;
  checked: number;
  digest: string;
  length: number;
  count: number;
  allocatedBytes?: number;
}
interface Counters {
  id: string;
  destination: LiveDestination;
  size: number;
  count: number;
  released?: number;
}

export const partBytes = 32 * 1024;
export const destinationKey = (d: Pick<LiveDestination, 'origin' | 'account'>) =>
  JSON.stringify([d.origin, d.account]);
export function result<T>(req: IDBRequest<T>) {
  return new Promise<T>((ok, fail) => {
    req.onsuccess = () => ok(req.result);
    req.onerror = () => fail(req.error);
  });
}
export function committed(tx: IDBTransaction) {
  return new Promise<void>((ok, fail) => {
    tx.oncomplete = () => ok();
    tx.onerror = tx.onabort = () => fail(tx.error);
  });
}

export async function saveLiveEvidence(
  db: LiveDB,
  recordingId: string,
  destination: LiveDestination,
  source: PageSource,
  event: Record<string, unknown>,
  maxBytes: number,
  at = Date.now(),
) {
  const serialized = new TextEncoder().encode(JSON.stringify(event));
  if (serialized.length > 40 * 1024 * 1024) throw new Error('live_event_limit');
  const digest = await sha256(serialized);
  const count = Math.ceil(serialized.length / partBytes);
  const conn = await db.open();
  const tx = conn.transaction(
    ['liveEvidence', 'liveRecordings', 'liveRequests', 'liveParts'],
    'readwrite',
    { durability: 'strict' },
  );
  const counters = tx.objectStore('liveRecordings');
  await new Promise<void>((resolve, reject) => {
    let failure: Error | undefined;
    tx.oncomplete = () => resolve();
    tx.onerror = tx.onabort = () =>
      reject(failure ?? tx.error ?? new Error('live_storage_unavailable'));
    const pending = counters.get(recordingId);
    pending.onsuccess = () => {
      const stats: Counters = pending.result ?? { id: recordingId, destination, size: 0, count: 0 };
      if (
        Object.keys(destination).some(
          (k) =>
            stats.destination[k as keyof LiveDestination] !==
            destination[k as keyof LiveDestination],
        )
      ) {
        failure = new Error('recording_owner_changed');
        tx.abort();
        return;
      }
      const summary =
        serialized.length <= 4096 && event.numeric_precision !== 'source'
          ? event
          : {
              kind: event.kind,
              request_key: event.request_key,
              side: event.side,
              status: event.status,
              baseline_id: event.baseline_id,
            };
      const lane = ['action', 'request', 'response', 'request_end'].includes(String(event.kind))
        ? 0
        : 1;
      const entry: LiveEntry = {
        id: crypto.randomUUID(),
        recordingId,
        source,
        observedAt: at,
        seq: stats.count + 1,
        event: summary,
        delivery: 'pending',
        destination,
        destinationKey: destinationKey(destination),
        lane,
        nextTry: Date.now(),
        failures: 0,
        nextPart: 0,
        checked: 0,
        digest,
        length: serialized.length,
        count,
      };
      const size = bytes(entry) + serialized.length + count * 96;
      entry.allocatedBytes = size;
      const append = () => {
        if (typeof event.request_key === 'string') {
          const requests = tx.objectStore('liveRequests');
          if (event.kind === 'request')
            requests.add({ recordingId, key: event.request_key, source });
          if (
            (event.kind === 'body' && event.side === 'response') ||
            (event.kind === 'request_end' && event.outcome !== 'finished')
          )
            requests.delete([recordingId, event.request_key]);
        }
        for (let number = 0; number < count; number++) {
          const data = serialized.slice(number * partBytes, (number + 1) * partBytes);
          tx.objectStore('liveParts').add({ id: entry.id, number, data });
        }
        tx.objectStore('liveEvidence').add(entry);
        counters.put({ ...stats, count: entry.seq, size: stats.size + size });
      };
      if (stats.size + size <= maxBytes) {
        append();
        return;
      }
      // Make room only from this recording's objects whose bytes have already been read back.
      const verified = tx
        .objectStore('liveEvidence')
        .index('progress')
        .openCursor([recordingId, 'verified']);
      verified.onsuccess = () => {
        const cursor = verified.result;
        if (!cursor) {
          failure = new Error('live_storage_full');
          tx.abort();
          return;
        }
        const old: LiveEntry = cursor.value;
        const range = IDBKeyRange.bound([old.id, 0], [old.id, old.count - 1]);
        tx.objectStore('liveParts').delete(range);
        cursor.delete();
        stats.size -= old.allocatedBytes ?? old.length;
        stats.released = (stats.released ?? 0) + 1;
        if (stats.size + size <= maxBytes) append();
        else cursor.continue();
      };
    };
  });
}

export async function recoverLiveRequests(
  db: LiveDB,
  recordingId: string,
  destination: LiveDestination,
  maxBytes: number,
) {
  const conn = await db.open();
  while (true) {
    const rows = await new Promise<{ key: string; source: PageSource }[]>((resolve, reject) => {
      const read = conn
        .transaction('liveRequests')
        .objectStore('liveRequests')
        .index('recordingId')
        .getAll(recordingId, 32);
      read.onsuccess = () => resolve(read.result);
      read.onerror = () => reject(read.error);
    });
    if (!rows.length) return;
    for (const row of rows)
      await saveLiveEvidence(
        db,
        recordingId,
        destination,
        row.source,
        { kind: 'request_end', request_key: row.key, outcome: 'worker_restarted' },
        maxBytes,
      );
  }
}
