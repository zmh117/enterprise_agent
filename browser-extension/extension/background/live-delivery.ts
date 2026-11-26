import { sha256 } from '../storage/database';
import { bytes } from '../../shared/contracts';
import {
  committed,
  destinationKey,
  LiveDB,
  partBytes,
  result,
  type LiveDestination,
  type LiveEntry,
} from '../storage/live-evidence';

type Send = (d: LiveDestination, path: string, body: unknown) => Promise<any>;
const interval = 30_000;
export class LiveDelivery {
  private running = false;
  private rounds = 0;
  constructor(
    private db: LiveDB,
    private send: Send,
  ) {}
  private async next(key: string, lane: number, delivery: 'pending' | 'acknowledged') {
    const conn = await this.db.open();
    const range = IDBKeyRange.bound([key, delivery, lane, 0], [key, delivery, lane, Date.now()]);
    return await result<LiveEntry | undefined>(
      conn.transaction('liveEvidence').objectStore('liveEvidence').index('schedule').get(range),
    );
  }
  private async batch(entry: LiveEntry) {
    const conn = await this.db.open();
    const parts: {
      event_id: string;
      seq: number;
      observed_ms: number;
      kind: unknown;
      event_digest: string;
      event_bytes: number;
      number: number;
      data: string;
    }[] = [];
    const payload = { recording_id: entry.recordingId, source: entry.source, parts };
    for (
      let number = entry.nextPart;
      number < Math.min(entry.nextPart + 8, entry.count);
      number++
    ) {
      const part = await result<{ data: Uint8Array } | undefined>(
        conn.transaction('liveParts').objectStore('liveParts').get([entry.id, number]),
      );
      if (!part || part.data.length !== Math.min(partBytes, entry.length - number * partBytes))
        throw new Error('local_part_missing');
      const data = btoa(String.fromCharCode(...part.data));
      parts.push({
        event_id: entry.id,
        seq: entry.seq,
        observed_ms: entry.observedAt,
        kind: entry.event.kind,
        event_digest: entry.digest,
        event_bytes: entry.length,
        number,
        data,
      });
    }
    if (bytes(payload) > 512 * 1024 || !parts.length) throw new Error('live_batch_limit');
    const ack = await this.send(entry.destination, '/live-evidence', payload);
    if (ack?.delivery !== 'forwarded' || ack.accepted !== parts.length)
      throw new Error('live_receipt_invalid');
    entry.nextPart += parts.length;
    if (entry.nextPart === entry.count) entry.delivery = 'acknowledged';
  }
  private async verify(entry: LiveEntry) {
    const check = await this.send(entry.destination, '/live-evidence/verify', {
      recording_id: entry.recordingId,
      source: entry.source,
      event_id: entry.id,
      event_digest: entry.digest,
      first: entry.checked,
    });
    if (
      !Number.isInteger(check.next) ||
      check.next < entry.checked ||
      check.next > Math.min(entry.count, entry.checked + 8)
    )
      throw new Error('live_verification_invalid');
    if (!Array.isArray(check.digests) || check.digests.length !== check.next - entry.checked)
      throw new Error('live_verification_invalid');
    const conn = await this.db.open();
    for (const remote of check.digests) {
      const part = await result<{ data: Uint8Array } | undefined>(
        conn.transaction('liveParts').objectStore('liveParts').get([entry.id, entry.checked]),
      );
      if (!part || remote !== (await sha256(part.data)))
        throw new Error('live_part_digest_mismatch');
      entry.checked++;
    }
    if (entry.checked === entry.count) {
      entry.delivery = 'verified';
      return;
    }
    if (!check.visible) {
      // Re-offer the retained source after Alloy accepted a batch but its content could not be read back.
      entry.nextPart = entry.checked;
      entry.delivery = 'pending';
      throw new Error('live_visibility_pending');
    }
  }
  async flush(identity: Pick<LiveDestination, 'origin' | 'account'>, budget = 10) {
    if (this.running) return false;
    this.running = true;
    try {
      const key = destinationKey(identity);
      for (let i = 0; i < budget; i++) {
        const turn = this.rounds++ % 4;
        const pass: ('pending' | 'acknowledged')[] =
          turn === 3 ? ['acknowledged', 'pending'] : ['pending', 'acknowledged'];
        const lanes = turn === 2 ? [1, 0] : [0, 1];
        let entry: LiveEntry | undefined;
        for (const phase of pass) {
          for (const lane of lanes) {
            entry = await this.next(key, lane, phase);
            if (entry) break;
          }
          if (entry) break;
        }
        if (!entry) return false;
        try {
          if (entry.delivery === 'pending') await this.batch(entry);
          else await this.verify(entry);
          entry.failures = 0;
          entry.nextTry = Date.now();
        } catch {
          entry.failures++;
          entry.nextTry =
            Date.now() + Math.min(8 * interval, 1000 * 2 ** Math.min(8, entry.failures));
        }
        const conn = await this.db.open();
        const tx = conn.transaction('liveEvidence', 'readwrite', { durability: 'strict' });
        const done = committed(tx);
        tx.objectStore('liveEvidence').put(entry);
        await done;
      }
      return true;
    } finally {
      this.running = false;
    }
  }
}
