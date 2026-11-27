import { commonEnvironment } from '../../../shared/recording-environment';
import { rememberPlatform } from '../../../shared/platform-traffic';
import { active, CHANNELS, now, SCHEMA_VERSION, terminal, uuid, bytes, type BlobRecord, type CaptureFragment, type CaptureToken, type Channel, type EvidenceEvent, type NetworkRecord, type PagePacket, type PageTicket, type Policy, type Recording, type Target } from '../../../shared/contracts';
import { parsePolicy, originOf, pageAllowed, supportedUrl, revokedHostMatches } from '../../../shared/policy';
import { cleanText, cleanUrl, cleanValue, cleanRrweb } from '../../../shared/redaction';
import { EvidenceDB, Journal } from '../../storage/database';
import { observeWorkerTask } from '../worker-task';
import { CaptureGate, newTarget } from './gate';
import { LineageTracker } from '../lineage/lineage';
import { FragmentAssembler } from './fragments';
import { DebuggerManager, type DebugHost } from '../cdp/manager';
import { captureHealth, REQUIRED_CHANNELS } from '../../../shared/capture-health';
import { projectVersions } from '../../../shared/correlation';
import { assertSchema } from '../../../shared/validation';

interface TicketState { ticket: PageTicket; target: Target; lastSeq: number; baseline: boolean; meta: boolean; stopped: boolean; observations?: Map<number, { snapshotRef: string; observedAt: string; sourceTime: number }> }
export class SessionManager implements DebugHost {
  readonly db = new EvidenceDB();
  recording!: Recording;
  targets = new Map<number, Target>();
  history = new Map<string, Target>();
  gate!: CaptureGate;
  journal!: Journal;
  debugger!: DebuggerManager;
  lineage = new LineageTracker();
  seq = 0;
  browserRunId = '';
  private tickets = new Map<string, TicketState>();
  private senderTickets = new Map<string, string>();
  private fragments!: FragmentAssembler;
  private streamSeq = new Map<string, number>();
  private controlStream = uuid();
  private startup = new Map<string, Promise<void>>();
  private startupRefresh = new Set<string>();
  private commandTail: Promise<unknown> = Promise.resolve();
  private stopping?: Promise<void>;
  private stopFinalState: 'READY' | 'FAILED' = 'READY';
  private gapKeys = new Set<string>();
  private resolving = false;
  private granting = new Map<string, Promise<PageTicket | null>>();
  private grantedOrigins = new Set<string>();
  private lastCaptureError = '';
  private recentActions = new Map<string, { eventId: string; observedAt: number; documentId: string }>();
  private pendingStarts = new Map<string, Promise<unknown>>();
  private canceledStarts = new Set<string>();
  private browserVersion = navigator.userAgent;
  private readiness = new Map<string, ReturnType<typeof setTimeout>>();
  private baselines = new Map<string, { eventId: string; recorderStreamId: string; nodeId: number }>();
  readonly ready: Promise<void>;
  constructor() { this.ready = this.recover(); }
  tick() { return ++this.seq; }
  private setup(r: Recording, ts: Target[] = []) {
    for (const timer of this.readiness.values()) clearTimeout(timer);
    this.readiness.clear();
    this.baselines.clear();
    this.recording = r; this.targets = new Map(ts.filter(t => t.lifecycle !== 'REPLACED').map(t => [t.browserTabId, t])); this.history = new Map(ts.map(t => [t.tabInstanceId, t]));
    this.gate = new CaptureGate(r, this.targets); this.debugger = new DebuggerManager(this);
    this.journal = new Journal(this.db, r, () => [...this.history.values()], e => {
      this.lastCaptureError = cleanText(e.message); this.gate.stopAll('storage_failure', this.tick());
      void this.stop('storage_failure').catch(() => {});
      void this.badge();
    });
    this.fragments = new FragmentAssembler(r.policy.budgets.queueBytes, r.policy.budgets.baselineBytes, r.policy.budgets.ipcBytes);
    this.tickets.clear(); this.senderTickets.clear(); this.streamSeq.clear(); this.gapKeys.clear(); this.controlStream = uuid(); this.stopping = undefined; this.stopFinalState = 'READY';
  }
  private async recover() {
    const stored = await chrome.storage.local.get(['agentPlatformOrigins','agentOrigin']);
    for (const origin of [...(Array.isArray(stored.agentPlatformOrigins) ? stored.agentPlatformOrigins : []),stored.agentOrigin]) {
      if (typeof origin === 'string') { try { rememberPlatform(origin); } catch { /* Ignore obsolete settings. */ } }
    }
    try {
      const ua = navigator as Navigator & { userAgentData?: { getHighEntropyValues: (keys: string[]) => Promise<{ fullVersionList?: { brand: string; version: string }[] }> } };
      const version = await ua.userAgentData?.getHighEntropyValues(['fullVersionList']);
      if (version?.fullVersionList?.length) this.browserVersion = version.fullVersionList.filter(x => /Chrom/i.test(x.brand)).map(x => `${x.brand}/${x.version}`).join(' ') || navigator.userAgent;
    } catch { /* Reduced UA remains an explicitly observable fallback. */ }
    await chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
    const state = await chrome.storage.session.get('browserRunId');
    this.browserRunId = typeof state.browserRunId === 'string' ? state.browserRunId : uuid();
    if (!state.browserRunId) await chrome.storage.session.set({ browserRunId: this.browserRunId });
    const canceled = await chrome.storage.session.get('canceledStarts');
    if (Array.isArray(canceled.canceledStarts)) this.canceledStarts = new Set(canceled.canceledStarts.filter((x): x is string => typeof x === 'string'));
    const intent = (await chrome.storage.local.get('stopIntent')).stopIntent as { recordingId: string; startedAt: string; reason: string; finalState: string } | undefined;
    const recordings = await this.db.listRecordings();
    // Development packages are intentionally incompatible across contract versions.
    // Exported historical files are untouched; do not append v2 events to a v1 recording.
    for (const r of recordings) if (r.schemaVersion !== SCHEMA_VERSION) await this.db.deleteRecording(r.recordingId);
    for (const r of recordings.filter(x => x.schemaVersion === SCHEMA_VERSION && !terminal(x.state))) {
      const ts = await this.db.list<Target>('targets', r.recordingId);
      if (r.browserRunId !== this.browserRunId) {
        r.state = 'INTERRUPTED'; r.stoppedAt = now(); r.stopReason = 'browser_exit_or_extension_reload';
        r.gaps.push({ id: uuid(), code: 'browser_run_changed', observedAt: now(), detail: '新浏览器运行期：旧 tabId 不再授权；最后未提交批次可能缺失' });
        for (const t of ts) { t.accepting = false; t.captureGeneration++; t.captureState = 'STOPPED'; t.stopReason = r.stopReason; for (const c of CHANNELS) t.channels[c].state = 'STOPPED'; }
        const network = await this.db.list<NetworkRecord>('network', r.recordingId);
        for (const n of network) if (n.networkOutcome === 'incomplete') { n.error = 'browser_exit'; for (const side of ['request', 'response'] as const) if (n[side].bodyCaptureStatus === 'unavailable') n[side].bodyCaptureReason = 'browser_exit'; }
        await this.db.saveBatch(r, ts, [], [], network); continue;
      }
      if (intent?.recordingId === r.recordingId) { r.state = 'STOPPING'; r.stoppedAt = intent.startedAt; r.stopReason = intent.reason; for (const t of ts) { t.accepting = false; t.captureState = 'STOPPED'; t.captureGeneration++; } }
      this.setup(r, ts); this.seq = Math.max(0, ...ts.flatMap(t => [t.scopeGrantedSeq, t.cutoffSeq ?? 0])) + 1;
      if (!active(r.state)) {
        this.diagnostic('interrupted_finalization', '停止整理中断，仅恢复已提交事务；最后未提交批次可能缺失，保持采集截止');
        for (const t of ts) { t.accepting = false; for (const c of CHANNELS) t.channels[c].state = 'STOPPED'; await this.cleanup(t, r.stopReason ?? 'interrupted_finalization'); }
        r.state = 'FINALIZING'; this.journal.touch(); await this.journal.flush();
        r.stopProgress = { startedAt: r.stoppedAt ?? now(), cutoff: 'complete', marker: 'complete', cleanup: 'complete', drain: 'complete', terminal: 'complete', deadlineExceeded: false };
        r.state = intent?.finalState === 'FAILED' ? 'FAILED' : 'READY'; this.journal.touch(); await this.journal.flush();
        await chrome.storage.local.remove('stopIntent'); continue;
      }

      this.diagnostic('service_worker_restarted', '后台重新对账；旧流终止，未提交批次可能缺失，新 recorder 必须重建基线');
      const pending = await this.db.list<NetworkRecord>('network', r.recordingId);
      for (const n of pending) if (n.networkOutcome === 'incomplete') { n.error = 'service_worker_restarted'; this.journal.append([], [], [n]); }
      await this.refreshPermissions();
      for (const t of this.targets.values()) {
        if (t.lifecycle !== 'OPEN' || !t.accepting) continue;
        for (const doc of t.documents) doc.endedAt ??= now();
        t.captureGeneration++;
        for (const c of CHANNELS) { t.channels[c].generation++; t.channels[c].state = 'PENDING'; }
        if (t.debuggerBlocked) for (const c of ['network', 'runtime'] as const) { t.channels[c].state = 'LOST'; t.channels[c].reason = 'previous_debugger_denial_preserved'; }
        // Only the extension that owns an attachment can detach it. Errors leave other debuggers alone.
        await chrome.debugger.detach({ tabId: t.browserTabId }).catch(() => {});
        try {
          const tab = await chrome.tabs.get(t.browserTabId);
          if (tab.incognito) { this.closed(t.browserTabId); continue; }
          t.url = cleanUrl(tab.url ?? ''); t.windowId = tab.windowId;
          void this.startTarget(t);
        } catch { this.closed(t.browserTabId); }
      }
      this.journal.touch(); await this.journal.flush();
    }
    await this.badge();
  }
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const result = this.commandTail.then(fn, fn); this.commandTail = result.catch(() => {}); return result;
  }
  async refreshPermissions() {
    const epoch = ++this.permissionEpoch, recording = this.recording;
    const granted = await chrome.permissions.getAll();
    const next = new Set<string>();
    for (const o of recording?.policy.pageOrigins ?? []) if (await chrome.permissions.contains({ origins: [`${o}/*`] })) next.add(o);
    if (epoch === this.permissionEpoch && recording === this.recording) this.grantedOrigins = next;
    return granted;
  }
  async permitted(url: string) {
    return !!this.recording && pageAllowed(this.recording.policy, url) && await chrome.permissions.contains({ origins: [`${originOf(url)}/*`] });
  }
  permittedKnown(url: string) { return !!this.recording && pageAllowed(this.recording.policy, url) && this.grantedOrigins.has(originOf(url) ?? ''); }
  documentBinding(t: Target, id: string) {
    const s = this.tickets.get(id);
    if (!s || s.target !== t || s.stopped || s.ticket.captureGeneration !== t.captureGeneration || !t.accepting) return null;
    return { chromeFrameId: s.ticket.chromeFrameId, documentId: s.ticket.documentId, verifiedBy: 'isolated_world_ticket_and_message_sender' };
  }
  documentEnded(t: Target, documentId: string, reason: string) {
    for (const s of this.tickets.values()) if (s.target === t && s.ticket.documentId === documentId) { s.stopped = true; this.fragments.dropTicket(s.ticket.id); }
    for (const doc of t.documents) if (doc.documentId === documentId) doc.endedAt ??= now();
    this.control('lifecycle.document_ended', { documentId, reason }, t);
  }
  ended(id: string, sender: chrome.runtime.MessageSender) {
    const s = this.verifyTicket(id, sender); if (s) this.documentEnded(s.target, s.ticket.documentId, 'pagehide');
  }
  private permissionEpoch = 0;
  private permissionWork: Promise<void> = Promise.resolve();
  permissionsRemoved(removed: chrome.permissions.Permissions): Promise<void> {
    const patterns = removed.origins ?? [];
    if (!patterns.length) return Promise.resolve();
    const revoked = (url: string) => patterns.some(p => revokedHostMatches(p, url));
    ++this.permissionEpoch;
    for (const origin of this.grantedOrigins) if (revoked(origin)) this.grantedOrigins.delete(origin);
    const recording = this.recording;
    const affected: { target: Target; generation: number }[] = [];
    // Fence every affected channel before the first await. Child bodies share
    // the tab's token, so revoke the old CDP generation as well as the page flow.
    for (const t of this.targets.values()) {
      if (!t.accepting || !active(recording?.state) || (!revoked(t.url) && !t.documents.some(d => !d.endedAt && revoked(d.url)) && !this.debugger.observesPageUrl(t, revoked))) continue;
      t.captureGeneration++; this.invalidateTickets(t);
      for (const c of REQUIRED_CHANNELS) { t.channels[c].generation++; t.channels[c].state = 'BLOCKED'; t.channels[c].reason = 'host_permission_revoked'; }
      t.captureState = 'BLOCKED';
      this.diagnostic(revoked(t.url) ? 'page_permission_revoked' : 'frame_permission_revoked', '主机权限撤回：旧页面流和 CDP 读取已截止，重新核实仍授权范围', t);
      affected.push({ target: t, generation: t.captureGeneration });
    }
    const previous = this.permissionWork;
    const refreshed = this.refreshPermissions();
    const cleaned = Promise.all(affected.map(({ target }) => this.cleanup(target, 'host_permission_revoked')));
    const work = (async () => {
      await Promise.all([previous, refreshed, cleaned]);
      if (this.recording !== recording || !active(recording?.state)) return;
      for (const { target, generation } of affected) {
        if (this.targets.get(target.browserTabId) === target && target.accepting && target.captureGeneration === generation) await this.startTarget(target);
      }
    })();
    this.permissionWork = work.catch(() => {});
    return work;
  }
  bound(id: string, sender: chrome.runtime.MessageSender) {
    const s = this.verifyTicket(id, sender);
    if (s) void this.debugger.refreshMappings(s.target);
  }
  private nodeContexts(s: TicketState, raw: any): any[] {
    if (!Array.isArray(raw) || raw.length > 4096) throw new Error('invalid_node_contexts');
    return raw.map(n => {
      if (!Number.isSafeInteger(n.nodeId) || n.nodeId < 0 || n.recorderStreamId !== s.ticket.recorderStreamId) throw new Error('invalid_node_identity');
      const binding = typeof n.documentTicketId === 'string' ? this.documentBinding(s.target, n.documentTicketId) : null;
      return { nodeId: n.nodeId, recorderStreamId: s.ticket.recorderStreamId, documentRoot: n.documentRoot === true,
        context: binding ? { ...binding, verifiedBy: 'registered_sender_document;page_observed_node_relation', status: 'mapped' } : { chromeFrameId: null, documentId: null, status: 'unknown', reason: 'node_document_binding_unconfirmed' } };
    });
  }
  private linkBaselines(s: TicketState, event: EvidenceEvent) {
    for (const node of event.payload.nodeContexts ?? []) {
      const key = `${s.ticket.recorderStreamId}:${node.nodeId}`;
      if (node.documentRoot && event.kind === 'rrweb.event') this.baselines.set(key, { eventId: event.eventId, recorderStreamId: s.ticket.recorderStreamId, nodeId: node.nodeId });
      const baseline = this.baselines.get(key);
      if (!node.documentRoot || !baseline || !node.context?.documentId) continue;
      const doc = s.target.documents.find(d => d.documentId === node.context.documentId && !d.endedAt);
      if (doc) { doc.baselineRef = baseline; doc.firstBaselineAt ??= event.observedAt; doc.status = 'baseline_received'; doc.subjectMapping = 'registered_document_baseline'; }
    }
  }
  token(t: Target, c: Channel) { return this.gate.token(t, c); }
  valid(token: CaptureToken) { return !!this.gate && this.gate.allows(token); }
  private event(t: Target | undefined, channel: Channel | 'control', kind: string, payload: Record<string, any>, meta: { streamId?: string; sourceTime?: number; sourceClock?: string } = {}): EvidenceEvent {
    const streamId = meta.streamId ?? this.controlStream;
    const sourceSeq = (this.streamSeq.get(streamId) ?? 0) + 1; this.streamSeq.set(streamId, sourceSeq);
    return {
      schemaVersion: SCHEMA_VERSION, eventId: `${streamId}:${sourceSeq}`, recordingId: this.recording.recordingId, browserRunId: this.browserRunId,
      tabInstanceId: t?.tabInstanceId ?? null, browserTabId: t?.browserTabId ?? null, windowId: t?.windowId ?? null,
      emitterContext: null, subjectContext: null, streamId, source: channel === 'control' ? 'extension' : channel, sourceSeq, kind,
      sourceTime: meta.sourceTime ?? null, sourceClock: meta.sourceClock ?? 'extension_observation', observedAt: now(), normalizedAt: null,
      captureGeneration: t?.captureGeneration ?? 0, channel, channelGeneration: channel === 'control' ? 0 : t!.channels[channel].generation,
      payload, quality: { redacted: true, truncated: false, limitations: [] },
    };
  }
  write(token: CaptureToken, kind: string, payload: Record<string, any>, meta = {}, network?: NetworkRecord, blobs: BlobRecord[] = []) {
    const t = this.history.get(token.tabInstanceId);
    if (!t || !this.valid(token)) { if (t) this.late(t); return null; }
    const e = this.event(t, token.channel, kind, cleanValue(payload), meta);
    const context = payload.documentContext;
    if (kind.startsWith('browser.') && context?.documentId && t.documents.some(d => d.documentId === context.documentId && d.chromeFrameId === context.chromeFrameId)) { e.subjectContext = { ...context }; e.emitterContext = { ...context }; }
    if (network && kind === 'network.request_observed') {
      const action = this.recentActions.get(t.tabInstanceId);
      if (action && (!network.documentId || action.documentId === network.documentId) && Date.now() - action.observedAt < 1500) network.actionCandidates = [{ actionId: action.eventId, basis: 'temporal_proximity_extension_observation', confirmed: false }];
    }
    if (network) network.evidenceRefs.push(e.eventId);
    if (!this.accept([e], blobs, network ? [network] : [])) { if (network) network.evidenceRefs.pop(); return null; }
    if (kind === 'network.response_observed' && network && !['Document', 'WebSocket', 'EventSource'].includes(network.request.type)) void chrome.tabs.sendMessage(t.browserTabId, { type: 'page.snapshot', reason: 'response_observed' }).catch(() => {});
    return e.eventId;
  }
  private discardSequences(events: EvidenceEvent[]) {
    for (const e of [...events].reverse()) if (this.streamSeq.get(e.streamId) === e.sourceSeq) this.streamSeq.set(e.streamId, e.sourceSeq - 1);
  }
  private accept(events: EvidenceEvent[], blobs: BlobRecord[] = [], network: NetworkRecord[] = []) {
    try { for (const event of events) assertSchema('event', event); for (const request of network) assertSchema('network', request); }
    catch (error) { this.discardSequences(events); throw error; }
    const size = bytes(events) + bytes(blobs) + bytes(network);
    if (this.recording.bytesAccepted + size > this.recording.policy.budgets.hardBytes) {
      this.discardSequences(events);
      this.diagnostic('hard_budget_reached', '达到本次会话硬预算，停止新增采集并保留已接受数据');
      void this.stop('quota_exceeded'); return false;
    }
    try { this.journal.append(events, blobs, network); }
    catch (e) { this.discardSequences(events); this.diagnostic('acceptance_queue_failure', cleanText(String(e))); void this.stop('queue_exceeded'); return false; }
    if (this.recording.bytesAccepted >= this.recording.policy.budgets.softBytes) this.diagnostic('soft_budget_reached', '已达到本次会话容量提醒阈值，可结束采集或继续至硬预算');
    return true;
  }
  control(kind: string, payload: Record<string, any>, t?: Target, network?: NetworkRecord) {
    if (!this.journal) return;
    const event = this.event(t, 'control', kind, cleanValue(payload));
    try { this.journal.append([event], [], network ? [network] : []); }
    catch {
      this.streamSeq.set(event.streamId, event.sourceSeq - 1); this.recording.saveState = 'error';
      if (!this.gapKeys.has('control_queue_failure')) {
        this.gapKeys.add('control_queue_failure'); this.recording.gaps.push({ id: uuid(), code: 'control_queue_failure', observedAt: now(), detail: '部分截止或整理信息未能入队；已保存业务数据保留，请结合目标截止与保存失败状态解释未完成请求' });
      }
      this.journal.touch();
    }
  }
  diagnostic(code: string, detail: string, target?: Target, channel?: Channel) {
    if (!this.recording) return;
    const key = `${target?.tabInstanceId ?? ''}:${channel ?? ''}:${code}`;
    if (this.gapKeys.has(key)) return;
    this.gapKeys.add(key);
    const gap = { id: uuid(), code, observedAt: now(), tabInstanceId: target?.tabInstanceId, channel, detail: cleanText(detail).slice(0, 2000) };
    this.recording.gaps.push(gap);
    this.control('capture.gap', gap, target);
  }
  finalizeNetwork(t: Target, r: NetworkRecord) { this.control('network.incomplete_finalization', { requestKey: r.requestKey, reason: r.error ?? r.extraInfoStatus }, t, r); }
  late(t: Target) { t.lateResults++; if (t.lateResults === 1) this.control('capture.late_result_dropped', { payloadDiscarded: true }, t); this.journal.touch(); }
  channelReady(t: Target, c: Channel) {
    if (!t.accepting || !active(this.recording.state)) return;
    if (t.channels[c].state !== 'PENDING') return;
    t.channels[c].state = 'ACTIVE'; t.channels[c].readyAt = now();
    if (c === 'network') t.networkReadyAt = t.channels[c].readyAt;
    if (c === 'runtime') t.runtimeReadyAt = t.channels[c].readyAt;
    t.captureState = captureHealth(t);
    if (this.recording.state === 'STARTING') this.recording.state = 'RECORDING';
    this.control('capture.channel_ready', { channel: c, readyAt: t.channels[c].readyAt }, t); void this.badge();
  }
  channelLost(t: Target, c: Channel, reason: string) {
    if (!t.accepting) return;
    this.gate.loseChannel(t, c, reason); this.diagnostic('channel_lost', reason, t, c); this.control('capture.channel_lost', { channel: c, reason }, t); void this.badge();
    t.captureState = captureHealth(t);
  }
  private watchReadiness(t: Target) {
    for (const c of REQUIRED_CHANNELS) {
      if (t.channels[c].state !== 'PENDING') continue;
      const token = this.token(t, c); const key = `${t.tabInstanceId}:${t.captureGeneration}:${c}:${token.channelGeneration}`;
      if (this.readiness.has(key)) continue;
      const r = this.recording;
      const timer = setTimeout(() => {
        this.readiness.delete(key);
        if (this.recording !== r || !this.valid(token) || t.channels[c].state !== 'PENDING') return;
        this.channelLost(t, c, 'readiness_timeout'); this.finishFailedStartup();
      }, 10_000);
      timer.unref?.(); this.readiness.set(key, timer);
    }
  }
  private finishFailedStartup() {
    if (this.recording.state !== 'STARTING') return;
    const states = [...this.targets.values()].flatMap(t => REQUIRED_CHANNELS.map(c => t.channels[c].state));
    if (states.every(s => s !== 'ACTIVE' && s !== 'PENDING')) {
      this.diagnostic('all_channels_failed', '所有已选根均不可用，保留失败会话和逐目标诊断');
      void this.stop('all_channels_failed', 'FAILED');
    }
  }
  async directory() {
    const windows = await chrome.windows.getAll({ populate: true, windowTypes: ['normal', 'popup'] });
    return { browserRunId: this.browserRunId, browserVersion: this.browserVersion, extensionVersion: chrome.runtime.getManifest().version,
      windows: windows.filter(w => !w.incognito).map(w => ({ id: w.id, focused: w.focused, tabs: (w.tabs ?? []).map(t => ({ id: t.id, windowId: t.windowId, title: cleanText(t.title ?? ''), url: cleanUrl(t.url ?? ''), origin: originOf(t.url ?? ''), active: t.active, eligible: supportedUrl(t.url ?? ''), reason: supportedUrl(t.url ?? '') ? null : '浏览器受限页面或无 http/https 文档' })) })) };
  }
  async start(command: any) {
    const task = this.serial(async () => {
      if (this.canceledStarts.has(command.recordingId)) throw new Error('该启动命令已取消，旧 recordingId 不可重新启动');
      if (command.browserRunId !== this.browserRunId) throw new Error('浏览器运行期已变化，请刷新目标列表');
      if (this.recording && this.recording.recordingId === command.recordingId) return this.status();
      if (this.recording && !terminal(this.recording.state)) throw new Error('已有活动或尚未保存完成的会话');
      if (await this.db.getRecording(command.recordingId)) throw new Error('该 recordingId 已存在，不能重新启动旧会话');
      if (!Array.isArray(command.rootBrowserTabIds) || !command.rootBrowserTabIds.length || command.rootBrowserTabIds.length > 100 || !command.rootBrowserTabIds.every(Number.isSafeInteger)) throw new Error('请选择有效的根标签');
      const policy = parsePolicy(command.policy);
      const ids: number[] = [...new Set<number>(command.rootBrowserTabIds)];
      if (ids.length > policy.budgets.hardTabs) throw new Error('所选根标签超过配置的硬上限，请调整策略或减少选择');
      const tabs = await Promise.all(ids.map(async id => { try { return await chrome.tabs.get(id); } catch { return { id, windowId: -1, url: '', title: '目标已关闭' } as chrome.tabs.Tab; } }));
      if (this.canceledStarts.has(command.recordingId)) throw new Error('启动已被停止命令取消');
      const rootEnvironments: Record<string, string> = {};
      for (const tab of tabs) {
        const site = originOf(tab.url ?? '');
        if (site) rootEnvironments[site] = cleanText(command.environments?.[site] ?? '');
      }
      const r: Recording = {
        schemaVersion: SCHEMA_VERSION, recordingId: command.recordingId, browserRunId: this.browserRunId, state: 'STARTING', scopeVersion: 1,
        rootEnvironments, environmentId: commonEnvironment(rootEnvironments),
        browserVersion: this.browserVersion, extensionVersion: chrome.runtime.getManifest().version, rrwebVersion: '2.2.2', startedAt: now(),
        policy, gaps: [], rootTabInstanceIds: [], commands: [command.commandId], bytesAccepted: 0, bytesPersisted: 0, eventsPersisted: 0, checkpoint: 0, saveState: 'pending',
        versions: { frontendBuildId: 'unknown', backendBuildId: 'unknown', serviceInstance: 'unknown', codeSnapshotMatch: 'unresolved', sources: {} },
        capabilities: { domTopLevel: 'pending', sameOriginFrames: 'parent_unified_stream', crossOriginFrames: 'cooperating_recorders_subject_mapping_partial', sharedWorkerInternals: 'not_collected', serviceWorkerInternals: 'not_collected', networkBodies: 'bounded', initialRequests: 'possible_gap', finalFlushConfirmed: false, screenshots: 'disabled_privacy', canvas: 'not_collected', shadowDom: 'open_only', websocketSse: policy.captureStreaming ? 'bounded_json_only' : 'handshake_only', missingChunks: [] },
      };
      this.setup(r); const grant = this.tick();
      for (const tab of tabs) {
        const t = newTarget(r, { id: tab.id!, windowId: tab.windowId, title: cleanText(tab.title ?? ''), url: cleanUrl(tab.url ?? '') }, grant, command.commandId, 'root');
        this.enroll(t); r.rootTabInstanceIds.push(t.tabInstanceId);
        if (tab.incognito || !supportedUrl(tab.url ?? '')) { t.captureState = 'BLOCKED'; for (const c of CHANNELS) t.channels[c].state = 'BLOCKED'; this.diagnostic('invalid_root', '根标签已关闭、隐身或受浏览器限制', t); }
      }
      this.control('lifecycle.session_started', { rootTabInstanceIds: r.rootTabInstanceIds, commandId: command.commandId });
      this.diagnostic('initial_coverage_gap', '采集开始前与 attach/注入就绪前的请求和页面变化可能缺失；不刷新或重放业务');
      this.diagnostic('screenshots_disabled', '截图像素脱敏无法保证；当前策略停用截图，保留页面状态和 rrweb 证据', undefined, 'screenshot');
      this.diagnostic('worker_scope_limit', '共享 worker/service worker 内部事件不采集；只保留有明确页面归属的响应');
      await this.refreshPermissions(); await this.journal.flush();
      if (this.canceledStarts.has(command.recordingId)) { await this.stop(); return this.status(); }
      for (const t of this.targets.values()) if (t.captureState !== 'BLOCKED') void this.startTarget(t);
      void this.resolveLineage();
      this.finishFailedStartup();
      await this.badge(); return this.status();
    });
    this.pendingStarts.set(command.recordingId, task);
    try { return await task; } finally { if (this.pendingStarts.get(command.recordingId) === task) this.pendingStarts.delete(command.recordingId); }
  }
  async stopCommand(command: any) {
    if (this.recording?.recordingId === command.recordingId) {
      await this.stop(); return this.status();
    }
    const pending = this.pendingStarts.get(command.recordingId);
    if (!pending) throw new Error('当前会话不匹配');
    this.canceledStarts.add(command.recordingId);
    await chrome.storage.session.set({ canceledStarts: [...this.canceledStarts].slice(-1000) });
    await pending.catch(() => {});
    return this.status();
  }
  private enroll(t: Target) {
    this.targets.set(t.browserTabId, t); this.history.set(t.tabInstanceId, t);
    this.control('lifecycle.tab_enrolled', { membershipReason: t.membershipReason, parentTabInstanceId: t.parentTabInstanceId, scopeGrantedSeq: t.scopeGrantedSeq }, t);
    if ([...this.targets.values()].filter(x => x.lifecycle === 'OPEN').length >= this.recording.policy.budgets.softTabs) this.diagnostic('soft_tab_limit', '纳入标签数达到提醒阈值，请关注本地资源占用');
  }
  private startTarget(t: Target): Promise<void> {
    const key = t.tabInstanceId;
    const old = this.startup.get(key);
    if (old) { this.startupRefresh.add(key); return old; }
    const generation = t.captureGeneration;
    const task = (async () => {
      if (!t.accepting || !active(this.recording.state) || t.lifecycle !== 'OPEN') return;
      this.watchReadiness(t);
      let tab: chrome.tabs.Tab;
      try { tab = await chrome.tabs.get(t.browserTabId); } catch { this.closed(t.browserTabId); return; }
      if (!t.accepting || t.captureGeneration !== generation) return;
      const url = tab.url ?? '';
      t.url = cleanUrl(url, this.recording.policy.allowedQueryKeys); t.title = cleanText(tab.title ?? ''); t.windowId = tab.windowId;
      if (url.startsWith(chrome.runtime.getURL(''))) {
        this.gate.stopTarget(t, 'collector_control_page_excluded', this.tick()); t.captureState = 'BLOCKED';
        this.control('capture.control_page_excluded', { reason: 'extension_control_is_never_a_business_target' }, t); return;
      }
      if (!await this.permitted(url)) {
        if (t.captureGeneration !== generation || !t.accepting) return;
        if (!url || url === 'about:blank') { t.captureState = 'PENDING'; this.journal.touch(); return; }
        t.captureState = 'BLOCKED'; for (const c of CHANNELS) if (c !== 'screenshot') { t.channels[c].state = 'BLOCKED'; t.channels[c].reason = 'page_policy_or_permission'; }
        this.diagnostic('page_not_permitted', '当前文档不在允许页面 origin 内或尚未获主机权限', t); this.journal.touch(); return;
      }
      if (!t.accepting || t.captureGeneration !== generation) return;
      for (const c of CHANNELS) if (t.channels[c].state === 'BLOCKED' && c !== 'screenshot') { t.channels[c].state = 'PENDING'; t.channels[c].generation++; }
      if (t.debuggerBlocked) for (const c of ['network', 'runtime'] as const) { t.channels[c].state = 'LOST'; t.channels[c].reason = 'previous_debugger_denial_preserved'; }
      t.captureState = 'ATTACHING'; t.channels.screenshot.state = 'BLOCKED'; t.channels.screenshot.reason = 'privacy_disabled';
      this.watchReadiness(t);
      await Promise.allSettled([this.debugger.attach(t), this.injectFrames(t)]);
      if (t.accepting && t.captureGeneration === generation) t.captureState = captureHealth(t);
      this.journal.touch();
    })().finally(() => {
      this.startup.delete(key);
      // A navigation/discard recovery can finish while attach is still pending.
      // Coalesce those real lifecycle notifications, then inspect the current
      // document once more instead of losing its injection request.
      const refresh = this.startupRefresh.delete(key);
      if (refresh && this.targets.get(t.browserTabId) === t && t.accepting && active(this.recording.state)) void this.startTarget(t);
      this.finishFailedStartup();
    });
    this.startup.set(key, task); return task;
  }
  async injectFrames(t: Target) {
    const token = this.token(t, 'page');
    if (!this.valid(token)) return;
    const frames = await chrome.webNavigation.getAllFrames({ tabId: t.browserTabId }).catch(() => null);
    if (!frames || !this.valid(token)) return;
    for (const frame of frames.sort((a, b) => a.frameId - b.frameId)) {
      if (!this.valid(token)) return;
      if (!await this.permitted(frame.url)) { this.diagnostic('frame_not_permitted', `frame ${frame.frameId} 未获页面域名授权，未注入采集器`, t, 'page'); continue; }
      if (!this.valid(token)) return;
      try {
        await chrome.scripting.executeScript({ target: { tabId: t.browserTabId, documentIds: [frame.documentId] }, world: 'ISOLATED', files: ['bootstrap.js'], injectImmediately: true });
        if (!this.valid(token)) { await chrome.tabs.sendMessage(t.browserTabId, { type: 'page.stop' }, { documentId: frame.documentId }).catch(() => {}); return; }
        await chrome.scripting.executeScript({ target: { tabId: t.browserTabId, documentIds: [frame.documentId] }, world: 'MAIN', files: ['recorder.js'], injectImmediately: true });
        if (!this.valid(token)) await chrome.tabs.sendMessage(t.browserTabId, { type: 'page.stop' }, { documentId: frame.documentId }).catch(() => {});
      } catch (e) { if (this.valid(token)) this.diagnostic('frame_injection_failed', `frame ${frame.frameId}: ${cleanText(String(e))}`, t, 'page'); }
    }
  }
  async handshake(sender: chrome.runtime.MessageSender): Promise<PageTicket | null> {
    if (!sender.tab?.id || sender.tab.incognito || !sender.documentId || sender.frameId === undefined || !active(this.recording?.state)) return null;
    const t = this.targets.get(sender.tab.id); if (!t?.accepting || t.lifecycle !== 'OPEN') return null;
    const key = `${t.tabInstanceId}:${sender.documentId}`;
    const inFlight = this.granting.get(key); if (inFlight) return inFlight;
    const work = this.grantTicket(t, sender, key).finally(() => this.granting.delete(key)); this.granting.set(key, work); return work;
  }
  private async grantTicket(t: Target, sender: chrome.runtime.MessageSender, key: string): Promise<PageTicket | null> {
    const token = this.token(t, 'page');
    if (!this.valid(token) || !await this.permitted(sender.url ?? '')) return null;
    const frame = await chrome.webNavigation.getFrame({ tabId: t.browserTabId, frameId: sender.frameId! }).catch(() => null);
    if (!frame || frame.documentId !== sender.documentId || !this.valid(token)) return null;
    let mode: PageTicket['mode'] = 'top';
    if (sender.frameId !== 0) {
      const parent = await chrome.webNavigation.getFrame({ tabId: t.browserTabId, frameId: frame.parentFrameId }).catch(() => null);
      if (!parent || !pageAllowed(this.recording.policy, parent.url)) return null;
      mode = originOf(parent.url) === originOf(frame.url) ? 'semantic-only' : 'cross-origin';
    }
    if (!this.valid(token)) return null;
    const existing = this.tickets.get(this.senderTickets.get(key) ?? '');
    if (existing && !existing.stopped && existing.ticket.captureGeneration === t.captureGeneration && existing.ticket.pageGeneration === t.channels.page.generation) return existing.ticket;
    const ticket: PageTicket = { id: uuid(), recordingId: this.recording.recordingId, browserRunId: this.browserRunId, tabInstanceId: t.tabInstanceId, captureGeneration: t.captureGeneration,
      pageGeneration: t.channels.page.generation, semanticGeneration: t.channels.semantic.generation, documentId: sender.documentId!, chromeFrameId: sender.frameId!, recorderStreamId: uuid(), nonce: uuid(), policy: this.recording.policy, mode };
    for (const doc of t.documents) if (doc.chromeFrameId === ticket.chromeFrameId) doc.endedAt ??= now();
    this.tickets.set(ticket.id, { ticket, target: t, lastSeq: 0, baseline: false, meta: false, stopped: false }); this.senderTickets.set(key, ticket.id);
    t.documents.push({ documentId: ticket.documentId, chromeFrameId: ticket.chromeFrameId, parentFrameId: frame.parentFrameId, url: cleanUrl(frame.url), observedAt: now(), recorderStreamId: ticket.recorderStreamId, status: 'pending_baseline', subjectMapping: mode === 'top' ? 'node_document_relation_partial' : mode === 'semantic-only' ? 'parent_unified_rrweb_semantic_sender_verified' : 'rrweb_parent_remapped_unknown_subject' });
    this.control('lifecycle.document_started', { documentId: ticket.documentId, chromeFrameId: ticket.chromeFrameId, recorderStreamId: ticket.recorderStreamId, mode }, t);
    return ticket;
  }
  private verifyTicket(id: string, sender: chrome.runtime.MessageSender): TicketState | undefined {
    const s = this.tickets.get(id);
    if (!s || sender.tab?.id !== s.target.browserTabId || sender.documentId !== s.ticket.documentId || sender.frameId !== s.ticket.chromeFrameId) return;
    if (!this.permittedKnown(sender.url ?? '')) return;
    if (s.stopped) { this.late(s.target); return; }
    if (s.ticket.browserRunId !== this.browserRunId || s.ticket.recordingId !== this.recording.recordingId || s.ticket.captureGeneration !== s.target.captureGeneration) { this.late(s.target); return; }
    return s;
  }
  capture(fragment: CaptureFragment, sender: chrome.runtime.MessageSender) {
    const s = this.verifyTicket(fragment.ticketId, sender); if (!s) return { ok: false, reason: 'ticket_or_sender_invalid' };
    const token = this.token(s.target, 'page'); token.captureGeneration = s.ticket.captureGeneration; token.channelGeneration = s.ticket.pageGeneration;
    const semanticToken = { ...token, channel: 'semantic' as const, channelGeneration: s.ticket.semanticGeneration };
    if (!this.valid(token) && !this.valid(semanticToken)) { this.late(s.target); return { ok: false, reason: 'stopped' }; }
    if (fragment.packetId <= s.lastSeq) return { ok: true, duplicate: true };
    try {
      const json = this.fragments.accept(fragment); if (json === null) return { ok: true };
      const p = JSON.parse(json) as PagePacket;
      assertSchema('pagePacket', p);
      if (!p || p.seq !== fragment.packetId || p.seq !== s.lastSeq + 1 || !Number.isFinite(p.sourceTime) || !p.payload || typeof p.payload !== 'object' || Array.isArray(p.payload) || !['rrweb.event', 'ui.observation', 'capture.page_diagnostic'].includes(p.kind)) throw new Error('page_schema_or_sequence_gap');
      if (p.kind === 'capture.page_diagnostic') {
        if (p.payload.code === 'document_mapping' && this.valid(token)) {
          const ev = this.event(s.target, 'page', 'rrweb.document_mapping', { nodeContexts: this.nodeContexts(s, p.payload.nodeContexts) }, { streamId: `${s.ticket.recorderStreamId}-page` });
          ev.recorderStreamId = s.ticket.recorderStreamId;
          ev.emitterContext = { chromeFrameId: s.ticket.chromeFrameId, documentId: s.ticket.documentId, verifiedBy: 'extension_message_sender' };
          if (this.accept([ev])) this.linkBaselines(s, ev);
        } else if (p.payload.code === 'semantic_started') {
          if (s.ticket.mode === 'top' && this.valid(semanticToken)) this.channelReady(s.target, 'semantic');
        } else if (p.payload.code === 'recorder_started') {
          const doc = s.target.documents.find(d => d.recorderStreamId === s.ticket.recorderStreamId); if (doc) { doc.recorderStartedAt = now(); if (s.ticket.mode === 'cross-origin') doc.status = 'cooperating_baseline_unconfirmed'; }
        } else {
          this.diagnostic(String(p.payload.code).slice(0, 100), String(p.payload.detail ?? '').slice(0, 1000), s.target, 'page');
          if (['baseline_or_event_too_large', 'invalid_sensitive_selector'].includes(p.payload.code)) throw new Error(p.payload.code);
          if (['rrweb_start_failed', 'rrweb_error'].includes(p.payload.code) && s.ticket.mode === 'top') this.channelLost(s.target, 'page', p.payload.code);
        }
        s.lastSeq = p.seq; return { ok: true };
      }
      const channel = p.kind === 'rrweb.event' ? 'page' : 'semantic';
      const channelToken = { ...token, channel, channelGeneration: channel === 'page' ? s.ticket.pageGeneration : s.ticket.semanticGeneration } as CaptureToken;
      if (!this.valid(channelToken)) { s.lastSeq = p.seq; return { ok: true, dropped: 'channel_stopped' }; }
      const meta = { streamId: `${s.ticket.recorderStreamId}-${channel}`, sourceTime: p.sourceTime, sourceClock: 'document_performance_ms' };
      const events: EvidenceEvent[] = [];
      if (p.kind === 'rrweb.event') {
        const e = p.payload.rrwebEvent;
        if (!e || !Number.isInteger(e.type) || e.type < 0 || e.type > 6 || !Number.isFinite(e.timestamp)) throw new Error('invalid_rrweb_event');
        if (e.type === 4) s.meta = true;
        if (e.type === 2) { if (!s.meta || !e.data?.node) throw new Error('baseline_without_meta'); s.baseline = true; }
        if (e.type === 3 && !s.baseline) throw new Error('incremental_without_baseline');
        const nodeContexts = this.nodeContexts(s, p.payload.nodeContexts ?? []);
        const ev = this.event(s.target, 'page', 'rrweb.event', { rrwebEvent: cleanRrweb(e, this.recording.policy), nodeContexts, mappingStatus: 'registered_document_relations;page_content_untrusted' }, meta);
        ev.recorderStreamId = s.ticket.recorderStreamId;
        ev.emitterContext = { chromeFrameId: s.ticket.chromeFrameId, documentId: s.ticket.documentId, verifiedBy: 'extension_message_sender' };
        ev.subjectContext = { chromeFrameId: null, documentId: null, status: 'unknown_or_multiple', reason: 'unified_rrweb_stream_includes_iframes;use_node_document_relation' };
        const known = nodeContexts.filter(n => n.context.documentId);
        if (known.length && known.length === nodeContexts.length && new Set(known.map(n => n.context.documentId)).size === 1) ev.subjectContext = known[0]!.context;
        if (e.type === 4) ev.subjectContext = { ...ev.emitterContext, status: 'mapped' };
        events.push(ev);
      } else {
        if (typeof p.payload.action !== 'string' || p.payload.action.length > 100) throw new Error('invalid_semantic_action');
        const observed = cleanValue({ action: p.payload.action, phase: p.payload.phase, target: p.payload.target ?? null, before: p.payload.before, after: p.payload.after, context: p.payload.context, observation: p.payload.observation, omissions: p.payload.omissions ?? [] });
        const previous = s.observations?.get(p.payload.before?.packetSeq);
        observed.before = previous ? { status: 'observed', ...previous } : { status: 'unavailable', reason: p.payload.before?.status === 'observed' ? 'previous_observation_not_retained' : 'no_previous_observation' };
        if (observed.target?.elementRef && (s.ticket.mode !== 'top' || observed.target.elementRef.recorderStreamId !== s.ticket.recorderStreamId || !Number.isInteger(observed.target.elementRef.nodeId))) {
          observed.target.elementRef = null; observed.target.elementRefStatus = 'unavailable_invalid_reference';
        }
        const snapshot = this.event(s.target, 'semantic', 'ui.state_snapshot', observed, meta);
        snapshot.recorderStreamId = s.ticket.recorderStreamId;
        snapshot.emitterContext = { chromeFrameId: s.ticket.chromeFrameId, documentId: s.ticket.documentId, verifiedBy: 'extension_message_sender' };
        snapshot.subjectContext = { chromeFrameId: s.ticket.chromeFrameId, documentId: s.ticket.documentId, status: 'verified' };
        const action = this.event(s.target, 'semantic', 'ui.action', { ...observed, evidenceRefs: [snapshot.eventId] }, meta);
        action.emitterContext = snapshot.emitterContext; action.subjectContext = snapshot.subjectContext; action.recorderStreamId = s.ticket.recorderStreamId;
        for (const e of [snapshot, action]) { e.quality.truncated = observed.omissions.length > 0; e.quality.limitations = e.quality.truncated ? ['semantic_read_budget;see_payload_omissions'] : []; }
        events.push(snapshot, action);
      }
      if (!this.accept(events)) return { ok: false, reason: 'budget_or_storage' };
      if (channel === 'semantic') {
        if (p.payload.action === 'build_metadata') projectVersions(this.recording, p.payload.after?.metadataFacts ?? [], `eventId:${events[0]!.eventId}`);
        s.observations ??= new Map(); s.observations.set(p.seq, { snapshotRef: events[0]!.eventId, observedAt: events[0]!.observedAt, sourceTime: p.payload.observation?.sourceTime ?? p.sourceTime });
        if (s.observations.size > 512) s.observations.delete(s.observations.keys().next().value!);
      }
      for (const event of events) if (event.kind === 'rrweb.event') this.linkBaselines(s, event);
      if (channel === 'semantic' && ['click', 'submit', 'input', 'change', 'select'].includes(p.payload.action)) this.recentActions.set(s.target.tabInstanceId, { eventId: events.at(-1)!.eventId, observedAt: Date.now(), documentId: s.ticket.documentId });
      s.lastSeq = p.seq;
      if (s.baseline) {
        const doc = s.target.documents.find(d => d.recorderStreamId === s.ticket.recorderStreamId);
        if (doc) {
          doc.firstBaselineAt ??= now(); doc.status = 'baseline_received';
          if (s.ticket.mode === 'top') { s.target.firstBaselineAt ??= doc.firstBaselineAt; this.recording.capabilities.domTopLevel = 'available'; this.channelReady(s.target, 'page'); }
        }
      }
      return { ok: true };
    } catch (e) {
      s.stopped = true; this.fragments.dropTicket(s.ticket.id); this.diagnostic('page_stream_rejected', cleanText(String(e)), s.target, 'page');
      if (s.ticket.mode === 'top') for (const c of ['page', 'semantic'] as const) this.channelLost(s.target, c, 'page_stream_rejected');
      void chrome.tabs.sendMessage(s.target.browserTabId, { type: 'page.stop' }, { documentId: s.ticket.documentId }).catch(() => {});
      return { ok: false, reason: 'stream_invalid' };
    }
  }
  transportError(id: string, sender: chrome.runtime.MessageSender, code: string) {
    const s = this.verifyTicket(id, sender); if (!s) return;
    s.stopped = true; this.fragments.dropTicket(id); this.diagnostic('transport_error', code, s.target, 'page');
    if (s.ticket.mode === 'top') for (const c of ['page', 'semantic'] as const) this.channelLost(s.target, c, 'transport_error');
  }
  created(tab: chrome.tabs.Tab, seq: number, at: string) {
    if (tab.id === undefined || tab.incognito) return;
    if ((tab.pendingUrl || tab.url || '').startsWith(chrome.runtime.getURL(''))) return;
    this.lineage.created(tab.id, seq, at);
    if (tab.openerTabId !== undefined) this.lineage.relation({ source: 'tabs.onCreated', sourceBrowserTabId: tab.openerTabId, targetBrowserTabId: tab.id, observedAt: at, observedSeq: seq });
    void this.resolveLineage();
  }
  navigationTarget(d: chrome.webNavigation.WebNavigationSourceCallbackDetails, seq: number, at: string) {
    this.lineage.relation({ source: 'webNavigation.onCreatedNavigationTarget', sourceBrowserTabId: d.sourceTabId, targetBrowserTabId: d.tabId, sourceFrameId: d.sourceFrameId, observedAt: at, observedSeq: seq, sourceTime: d.timeStamp, sourceClock: 'webNavigation_epoch_ms' });
    void this.resolveLineage();
  }
  private async resolveLineage() {
    if (this.resolving || !this.recording || !active(this.recording.state)) return;
    this.resolving = true;
    try {
      let pending = this.lineage.resolve(this.targets);
      while (pending.length && active(this.recording.state)) {
        for (const candidate of pending) {
          if (this.targets.has(candidate.id)) continue;
          let tab: chrome.tabs.Tab | undefined;
          try { tab = await chrome.tabs.get(candidate.id); } catch { /* Closed before delayed source confirmation: keep lineage, never attach. */ }
          if (!active(this.recording.state) || tab?.incognito) continue;
          if ((tab?.pendingUrl || tab?.url || '').startsWith(chrome.runtime.getURL(''))) { this.lineage.candidates.delete(candidate.id); continue; }
          const t = newTarget(this.recording, { id: candidate.id, windowId: tab?.windowId ?? -1, title: cleanText(tab?.title ?? ''), url: cleanUrl(tab?.url ?? '') }, candidate.seq, candidate.parent.grantCommandId, 'derived', candidate.parent);
          t.createdObservedAt = candidate.at; t.lineageEvidence = candidate.evidence;
          this.enroll(t); this.recording.scopeVersion++;
          if (!tab || candidate.closedSeq !== undefined) { this.gate.stopTarget(t, 'tab_closed', candidate.closedSeq ?? this.tick()); t.lifecycle = 'CLOSED'; }
          else if ([...this.targets.values()].filter(x => x.lifecycle === 'OPEN' && x.accepting).length > this.recording.policy.budgets.hardTabs) {
            this.gate.stopTarget(t, 'tab_limit', this.tick()); t.captureState = 'BLOCKED'; this.diagnostic('hard_tab_limit', '硬上限已达到：保留谱系，但此目标未启动业务采集', t);
          } else void this.startTarget(t);
        }
        pending = this.lineage.resolve(this.targets);
      }
      for (const id of this.lineage.ambiguous()) {
        const t = this.targets.get(id);
        const candidate = this.lineage.candidates.get(id);
        if (!t && ![...candidate?.parents.keys() ?? []].some(parent => this.targets.has(parent))) continue;
        this.diagnostic(`ambiguous_lineage_${id}`, `标签 ${id} 来源冲突/循环，停止自动采集，可手动添加`, t);
        if (t?.membershipReason === 'derived' && t.accepting) { this.gate.stopTarget(t, 'ambiguous_lineage', this.tick()); void this.cleanup(t, 'ambiguous_lineage'); }
      }
    } finally { this.resolving = false; }
  }
  closed(tabId: number, seq = this.tick()) {
    this.lineage.closed(tabId, seq);
    const t = this.targets.get(tabId); if (!t || t.lifecycle !== 'OPEN' || !this.gate) return;
    this.gate.stopTarget(t, 'tab_closed', seq); t.lifecycle = 'CLOSED';
    this.invalidateTickets(t); this.control('lifecycle.tab_closed', { cutoffObservedAt: t.cutoffObservedAt, cutoffSeq: seq, finalFlushConfirmed: false }, t);
    void this.cleanup(t, 'tab_closed'); void this.badge();
  }
  moved(tabId: number, windowId: number, source: string) { const t = this.targets.get(tabId); if (!t || !active(this.recording?.state)) return; t.windowId = windowId; this.control('lifecycle.tab_moved', { windowId, source }, t); }
  async replaced(added: number, removed: number) {
    const old = this.targets.get(removed); if (!old || old.lifecycle === 'REPLACED' || this.targets.has(added) || !active(this.recording?.state)) return;
    const seq = this.tick(); this.gate.stopTarget(old, 'tab_replaced', seq); old.lifecycle = 'REPLACED'; this.invalidateTickets(old); void this.cleanup(old, 'tab_replaced');
    let tab: chrome.tabs.Tab; try { tab = await chrome.tabs.get(added); } catch { this.diagnostic('replacement_missing', '替换后的标签已不可用', old); return; }
    // Both tabs and webNavigation report a replacement. Claim the old instance
    // before awaiting tabs.get, and recheck ownership after that async boundary.
    if (!active(this.recording.state) || this.targets.get(removed) !== old || this.targets.has(added)) return;
    const t = newTarget(this.recording, { id: added, windowId: tab.windowId, title: cleanText(tab.title ?? ''), url: cleanUrl(tab.url ?? '') }, seq, old.grantCommandId, 'replacement');
    t.parentTabInstanceId = old.parentTabInstanceId; t.rootTabInstanceIds = old.rootTabInstanceIds; t.replacesTabInstanceId = old.tabInstanceId;
    this.enroll(t); this.control('lifecycle.tab_replaced', { replacesTabInstanceId: old.tabInstanceId }, t); void this.startTarget(t);
  }
  beforeNavigate(d: { tabId: number; frameId: number; url: string }) {
    const t = this.targets.get(d.tabId); if (!t?.accepting || !active(this.recording?.state)) return;
    if (d.frameId === 0 && (!pageAllowed(this.recording.policy, d.url) || !this.grantedOrigins.has(originOf(d.url) ?? ''))) {
      // Preserve enrollment while invalidating every channel before any asynchronous cleanup.
      t.captureGeneration++; this.invalidateTickets(t);
      for (const c of CHANNELS) { t.channels[c].generation++; t.channels[c].state = 'BLOCKED'; }
      t.captureState = 'BLOCKED'; this.diagnostic('navigation_policy_blocked', '目标导航到未授权页面，相应通道已暂停', t);
      void this.cleanup(t, 'policy_blocked');
    }
  }
  navigation(d: { tabId: number; frameId: number; documentId?: string; url: string; timeStamp: number }, route = false) {
    const t = this.targets.get(d.tabId); if (!t?.accepting || !active(this.recording?.state)) return;
    if (route) {
      if (pageAllowed(this.recording.policy, d.url)) this.write(this.token(t, 'semantic'), 'lifecycle.route_changed', { url: cleanUrl(d.url, this.recording.policy.allowedQueryKeys), documentId: d.documentId ?? null, chromeFrameId: d.frameId }, { sourceTime: d.timeStamp, sourceClock: 'webNavigation_epoch_ms' });
      void chrome.tabs.sendMessage(t.browserTabId, { type: 'page.snapshot', reason: 'route_change' }, { frameId: d.frameId }).catch(() => {}); return;
    }
    if (d.frameId === 0 && [...this.tickets.values()].some(s => s.target === t && !s.stopped && s.ticket.chromeFrameId === 0 && s.ticket.documentId !== d.documentId)) {
      this.invalidateTickets(t);
      for (const c of ['page', 'semantic'] as const) { t.channels[c].generation++; t.channels[c].state = 'PENDING'; }
      t.captureState = 'DEGRADED';
    }
    for (const s of this.tickets.values()) if (s.target === t && s.ticket.chromeFrameId === d.frameId && s.ticket.documentId !== d.documentId) { s.stopped = true; if (this.fragments.dropTicket(s.ticket.id)) this.diagnostic('navigation_incomplete_fragment', '导航时尚未重组完的事件已丢弃', t, 'page'); }
    for (const doc of t.documents) if (doc.chromeFrameId === d.frameId && doc.documentId !== d.documentId) doc.endedAt ??= now();
    if (d.frameId === 0) void this.startTarget(t);
    else void this.injectFrames(t);
  }
  async updated(tabId: number, change: { discarded?: boolean; status?: string; frozen?: boolean }) {
    const t = this.targets.get(tabId); if (!t?.accepting || !active(this.recording?.state)) return;
    if (change.discarded === true || (change as any).frozen === true) {
      this.diagnostic('tab_suspended', '标签被 discard/freeze；该区间不保证持续页面覆盖', t, 'page'); this.invalidateTickets(t);
      t.channels.page.generation++; t.channels.semantic.generation++; t.channels.page.state = 'PENDING'; t.channels.semantic.state = 'PENDING';
    }
    if (change.status === 'complete' || change.discarded === false || (change as any).frozen === false) void this.startTarget(t);
  }
  private invalidateTickets(t: Target) {
    for (const doc of t.documents) doc.endedAt ??= now();
    for (const s of this.tickets.values()) if (s.target === t) { s.stopped = true; const n = this.fragments.dropTicket(s.ticket.id); if (n) this.diagnostic('incomplete_ipc_at_cutoff', `${n} 个未完成事件在截止时丢弃，无语义引用`, t, 'page'); }
  }
  private async cleanup(t: Target, reason: string) {
    await Promise.allSettled([this.debugger.stop(t, reason), chrome.tabs.sendMessage(t.browserTabId, { type: 'page.stop' })]);
  }
  async addRoot(command: any) {
    return this.serial(async () => {
      this.requireCurrent(command.recordingId);
      if (this.recording.commands.includes(command.commandId)) return this.status();
      if (!active(this.recording.state)) throw new Error('会话已停止');
      if (command.scopeVersion !== this.recording.scopeVersion) throw new Error('目标范围已更新，请刷新后重试');
      if (this.targets.get(command.browserTabId)?.accepting) return this.status();
      const tab = await chrome.tabs.get(command.browserTabId);
      if (tab.incognito || !supportedUrl(tab.url ?? '')) throw new Error('该标签不可采集');
      if ([...this.targets.values()].filter(t => t.accepting).length >= this.recording.policy.budgets.hardTabs) throw new Error('已达到标签硬上限');
      if (!pageAllowed(this.recording.policy, tab.url ?? '')) throw new Error('该域名不在本次冻结策略内；请结束后以新策略开始');
      if (!active(this.recording.state)) throw new Error('会话已停止');
      const t = newTarget(this.recording, { id: tab.id!, windowId: tab.windowId, title: cleanText(tab.title ?? ''), url: cleanUrl(tab.url ?? '') }, this.tick(), command.commandId, 'manual_add');
      const site = originOf(tab.url ?? '');
      const environments = this.recording.rootEnvironments;
      if (site && environments && !(site in environments)) {
        environments[site] = cleanText(command.environments?.[site] ?? '');
        this.recording.environmentId = commonEnvironment(environments);
      }
      this.recording.scopeVersion++; this.recording.commands.push(command.commandId); this.recording.rootTabInstanceIds.push(t.tabInstanceId); this.enroll(t);
      await this.journal.flush(); void this.startTarget(t); void this.resolveLineage(); return this.status();
    });
  }
  async mark(command: any) {
    this.requireCurrent(command.recordingId);
    if (!active(this.recording.state)) throw new Error('会话已停止');
    if (this.recording.commands.includes(command.commandId)) return this.status();
    const t = this.targets.get(command.browserTabId); if (!t?.accepting || t.lifecycle !== 'OPEN') throw new Error('当前标签尚未纳入或已关闭，请先手动添加');
    this.recording.commands.push(command.commandId);
    this.write(this.token(t, 'semantic'), 'ui.issue_marker', { note: cleanText(command.note ?? ''), screenshot: { status: 'unavailable', reason: 'disabled_privacy' }, commandId: command.commandId });
    await chrome.tabs.sendMessage(t.browserTabId, { type: 'page.snapshot', reason: 'issue_marker' }).catch(() => {});
    await this.journal.flush(); return this.status();
  }
  requireCurrent(id: string) { if (!this.recording || this.recording.recordingId !== id) throw new Error('当前会话不匹配'); }
  stop(reason = 'session_stopped', finalState: 'READY' | 'FAILED' = 'READY'): Promise<void> {
    if (this.stopping) return this.stopping;
    if (!this.recording || terminal(this.recording.state)) return Promise.resolve();
    this.stopFinalState = finalState;
    this.gate.stopAll(reason, this.tick());
    for (const timer of this.readiness.values()) clearTimeout(timer);
    this.readiness.clear();
    for (const t of this.targets.values()) this.invalidateTickets(t);
    this.control('lifecycle.session_stopped', { reason, stoppedAt: this.recording.stoppedAt });
    const progress: NonNullable<Recording['stopProgress']> = this.recording.stopProgress = { startedAt: this.recording.stoppedAt ?? now(), cutoff: 'complete' as const, marker: 'pending' as 'pending' | 'complete' | 'error', cleanup: 'pending' as 'pending' | 'complete' | 'error', drain: 'pending' as 'pending' | 'complete' | 'error', terminal: 'pending' as 'pending' | 'complete' | 'error', deadlineExceeded: false };
    const timer = setTimeout(() => { progress.deadlineExceeded = true; this.diagnostic('stop_wait_threshold', '停止已超过 5 秒；查看 stopProgress 的持久化标记、连接清理、批次排空和终结保存阶段，未完成不代表保存成功'); }, 5000);
    // Independent STOP intent survives worker termination even while IndexedDB is busy.
    const marker = chrome.storage.local.set({ stopIntent: { recordingId: this.recording.recordingId, reason, startedAt: progress.startedAt, finalState } }).then(() => { progress.marker = 'complete'; }, e => { progress.marker = 'error'; throw e; });
    const cleanup = Promise.all([...this.targets.values()].map(t => this.cleanup(t, reason))).then(() => { progress.cleanup = 'complete'; });
    const run = async () => {
      await Promise.all([marker, cleanup, this.journal.flush().then(() => { progress.drain = 'complete'; }, e => { progress.drain = 'error'; throw e; })]);
      this.recording.state = 'FINALIZING'; this.journal.touch(); await this.journal.flush();
      this.recording.state = finalState; progress.terminal = 'complete'; this.journal.touch(); await this.journal.flush();
      await chrome.storage.local.remove('stopIntent'); await this.badge();
    };
    this.stopping = run().catch(e => { this.recording.state = 'FINALIZING'; progress.terminal = 'error'; this.recording.saveState = 'error'; this.recording.saveError = cleanText(String(e)); throw e; }).finally(() => clearTimeout(timer));

    return this.stopping;
  }
  status() {
    if (!this.recording) return { recording: null, targets: [] };
    const activeTargets = [...this.targets.values()].filter(t => t.lifecycle === 'OPEN' && t.accepting);
    return { recording: this.recording, targets: [...this.history.values()], activeTargets: activeTargets.length,
      readyTargets: activeTargets.filter(t => captureHealth(t) === 'ACTIVE').length,
      durationReminder: active(this.recording.state) && Date.now() - Date.parse(this.recording.startedAt) >= this.recording.policy.budgets.reminderMinutes * 60_000,
      resources: { bodyQueues: this.debugger.metrics(), journal: this.journal.metrics() },
      saveError: this.lastCaptureError || this.recording.saveError, pendingStarts: this.startup.size };
  }
  private async badge() {
    const recording = this.recording && active(this.recording.state);
    const count = recording ? [...this.targets.values()].filter(t => t.accepting && t.lifecycle === 'OPEN').length : 0;
    await observeWorkerTask('更新采集图标', Promise.all([
      chrome.action.setBadgeText({ text: recording ? String(count) : '' }),
      chrome.action.setBadgeBackgroundColor({ color: recording ? '#c33e33' : '#526273' }),
    ]));
  }
  async retrySave() { await this.stopping?.catch(() => {}); await this.journal.retry(); this.lastCaptureError = ''; this.stopping = undefined; if (!terminal(this.recording.state)) await this.stop(this.recording.stopReason ?? 'storage_failure', this.stopFinalState); }
}
