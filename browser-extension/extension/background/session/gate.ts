import { active, CHANNELS, now, uuid, type CaptureToken, type Channel, type Recording, type Target } from '../../../shared/contracts';
export class CaptureGate {
  constructor(public recording: Recording, public targets: Map<number, Target>) {}
  token(t: Target, channel: Channel): CaptureToken {
    return { recordingId: t.recordingId, browserRunId: t.browserRunId, tabInstanceId: t.tabInstanceId, captureGeneration: t.captureGeneration, channel, channelGeneration: t.channels[channel].generation };
  }
  allows(token: CaptureToken): boolean {
    if (!active(this.recording.state) || token.recordingId !== this.recording.recordingId || token.browserRunId !== this.recording.browserRunId) return false;
    const t = [...this.targets.values()].find(x => x.tabInstanceId === token.tabInstanceId);
    return !!t && t.accepting && t.lifecycle === 'OPEN' && t.captureGeneration === token.captureGeneration && t.channels[token.channel].generation === token.channelGeneration && !['LOST', 'BLOCKED', 'STOPPED'].includes(t.channels[token.channel].state);
  }
  stopTarget(t: Target, reason: string, seq: number) {
    if (!t.accepting && t.stopReason === reason) return;
    t.accepting = false; t.captureGeneration++; t.cutoffObservedAt = now(); t.cutoffSeq = seq; t.stopReason = reason; t.captureState = 'STOPPED';
    for (const c of CHANNELS) { t.channels[c].state = 'STOPPED'; t.channels[c].stoppedAt = t.cutoffObservedAt; }
  }
  loseChannel(t: Target, channel: Channel, reason: string) {
    const c = t.channels[channel]; c.generation++; c.state = 'LOST'; c.stoppedAt = now(); c.reason = reason;
    t.quality = 'partial'; t.captureState = 'DEGRADED';
  }
  stopAll(reason: string, seq: number) {
    if (!active(this.recording.state)) return;
    // No await before every acceptance gate is shut.
    this.recording.state = 'STOPPING'; this.recording.stoppedAt = now(); this.recording.stopReason = reason;
    for (const t of this.targets.values()) if (t.lifecycle === 'OPEN') this.stopTarget(t, reason, seq);
  }
}
export function newTarget(r: Recording, tab: { id: number; windowId: number; title?: string; url?: string }, seq: number, commandId: string, reason: Target['membershipReason'], parent?: Target): Target {
  const id = uuid();
  return {
    recordingId: r.recordingId, browserRunId: r.browserRunId, tabInstanceId: id, browserTabId: tab.id, windowId: tab.windowId,
    title: tab.title ?? '', url: tab.url ?? '', parentTabInstanceId: parent?.tabInstanceId ?? null,
    rootTabInstanceIds: parent ? [...parent.rootTabInstanceIds] : [id], membershipReason: reason, lineageEvidence: [],
    scopeGrantedAt: now(), scopeGrantedSeq: seq, grantCommandId: commandId, lineageConfirmedAt: now(),
    lifecycle: 'OPEN', captureState: 'PENDING', captureGeneration: 1, accepting: true,
    channels: Object.fromEntries(CHANNELS.map(c => [c, { state: 'PENDING', generation: 1 }])) as Target['channels'],
    quality: 'partial', possibleInitialGap: true, finalFlushConfirmed: false, lateResults: 0, documents: [],
  };
}
