import { bytes, type CaptureFragment } from '../../../shared/contracts';
interface Assembly { total: number; parts: Map<number, string>; size: number; started: number }
export class FragmentAssembler {
  private pending = new Map<string, Assembly>();
  private size = 0;
  constructor(private maxBytes: number, private maxEventBytes: number, private ipcBytes: number) {}
  accept(fragment: CaptureFragment): string | null {
    const { ticketId, packetId, index, total, data } = fragment;
    if (typeof ticketId !== 'string' || ticketId.length > 100 || !Number.isSafeInteger(packetId) || packetId < 1 || !Number.isInteger(index) || !Number.isInteger(total) || total < 1 || total > 8192 || index < 0 || index >= total || typeof data !== 'string' || !data.length || bytes(data) > this.ipcBytes) throw new Error('invalid_fragment');
    if (this.prune()) throw new Error('fragment_timeout');
    const key = `${ticketId}:${packetId}`;
    let a = this.pending.get(key);
    if (!a) { if (this.pending.size >= 64) throw new Error('reassembly_count_limit'); a = { total, parts: new Map(), size: 0, started: Date.now() }; this.pending.set(key, a); }
    if (a.total !== total) throw new Error('fragment_count_conflict');
    const old = a.parts.get(index);
    if (old !== undefined) { if (old !== data) throw new Error('fragment_payload_conflict'); return null; }
    const size = bytes(data); a.size += size; this.size += size; a.parts.set(index, data);
    if (a.size > this.maxEventBytes || this.size > this.maxBytes) { this.clear(); throw new Error('reassembly_budget_exceeded'); }
    if (a.parts.size !== total) return null;
    this.pending.delete(key); this.size -= a.size;
    return Array.from({ length: total }, (_, i) => a!.parts.get(i)!).join('');
  }
  dropTicket(id: string) { let count = 0; for (const [key, a] of this.pending) if (key.startsWith(`${id}:`)) { this.size -= a.size; this.pending.delete(key); count++; } return count; }
  clear() { const n = this.pending.size; this.pending.clear(); this.size = 0; return n; }
  private prune() { let n = 0; for (const [key, a] of this.pending) if (Date.now() - a.started > 30_000) { this.pending.delete(key); this.size -= a.size; n++; } return n; }
}
