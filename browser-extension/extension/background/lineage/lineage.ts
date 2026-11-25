import { type LineageEvidence, type Target } from '../../../shared/contracts';
interface Candidate { id: number; createdSeq?: number; createdAt?: string; seen: number; parents: Map<number, LineageEvidence[]>; closedSeq?: number }
/** Only browser lifecycle events enter here. All comparisons use one local observation sequence. */
export class LineageTracker {
  candidates = new Map<number, Candidate>();
  constructor(private ttlMs = 30_000) {}
  private candidate(id: number) {
    let c = this.candidates.get(id);
    if (!c) { c = { id, seen: Date.now(), parents: new Map() }; this.candidates.set(id, c); }
    return c;
  }
  created(id: number, seq: number, at: string) { const c = this.candidate(id); c.createdSeq ??= seq; c.createdAt ??= at; }
  relation(e: LineageEvidence) { const c = this.candidate(e.targetBrowserTabId); const list = c.parents.get(e.sourceBrowserTabId) ?? []; if (!list.some(x => x.source === e.source)) list.push(e); c.parents.set(e.sourceBrowserTabId, list); }
  closed(id: number, seq: number) { this.candidate(id).closedSeq = seq; }
  resolve(targets: Map<number, Target>): { id: number; parent: Target; seq: number; at: string; evidence: LineageEvidence[]; closedSeq?: number }[] {
    this.prune();
    const resolved = [];
    for (const c of this.candidates.values()) {
      if (targets.has(c.id) || c.createdSeq === undefined || c.parents.size !== 1) continue;
      const [parentId, evidence] = [...c.parents.entries()][0]!;
      const parent = targets.get(parentId);
      if (!parent || c.id === parentId || c.createdSeq <= parent.scopeGrantedSeq) continue;
      if (parent.cutoffSeq !== undefined && c.createdSeq > parent.cutoffSeq) continue;
      resolved.push({ id: c.id, parent, seq: c.createdSeq, at: c.createdAt!, evidence, closedSeq: c.closedSeq });
    }
    return resolved;
  }
  ambiguous() { return [...this.candidates.values()].filter(c => c.parents.size > 1 || c.parents.has(c.id)).map(c => c.id); }
  prune() { for (const [id, c] of this.candidates) if (Date.now() - c.seen > this.ttlMs) this.candidates.delete(id); }
}
