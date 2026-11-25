import { type CaptureToken, type Channel, type Context, type Target, uuid } from '../../../shared/contracts';
import { apiAllowed, pageAllowed } from '../../../shared/policy';
import { cleanText, cleanValue, sensitiveKey, MASK } from '../../../shared/redaction';
import { type CaptureHost, NetworkCollector, BodyQueue } from './network';

type FlatDebuggee = chrome.debugger.Debuggee & { sessionId?: string };
interface DebugSession {
  key: string; source: FlatDebuggee; target: Target; networkToken: CaptureToken; runtimeToken: CaptureToken;
  network: NetworkCollector; frames: Map<string, { url: string; allowed: boolean; loaderId?: string }>; contexts: Map<number, string>;
  worker: boolean; stopped: boolean; failed: Set<Channel>;
  isolatedContexts: Map<number, string>; documents: Map<string, { ticketId: string; context: Context }>; probes: Set<number>;
}
export interface DebugHost extends CaptureHost {
  token(t: Target, c: Channel): CaptureToken;
  channelReady(t: Target, c: Channel): void;
  channelLost(t: Target, c: Channel, reason: string): void;
  permitted(url: string): Promise<boolean>;
  permittedKnown(url: string): boolean;
  documentBinding?(t: Target, ticketId: string): Context | null;
  documentEnded?(t: Target, documentId: string, reason: string): void;
}
export class DebuggerManager {
  private exceptions = new Set<string>();
  private bodyQueues = new Map<string, BodyQueue>();
  metrics() { return [...this.bodyQueues].map(([tabInstanceId, queue]) => ({ tabInstanceId, ...queue.stats() })); }
  private sessions = new Map<string, DebugSession>();
  private attaching = new Map<number, Promise<void>>();
  private owned = new Map<number, Target>();
  private denied = new Set<number>();
  constructor(private host: DebugHost) {}
  observesPageUrl(t: Target, matches: (url: string) => boolean): boolean {
    // CDP may be ready before the content-script handshake creates a document.
    return [...this.sessions.values()].some(s => s.target === t && !s.stopped && [...s.frames.values()].some(f => matches(f.url)));
  }
  private key(source: FlatDebuggee) { return `${source.tabId}:${source.sessionId ?? 'root'}`; }
  async attach(t: Target) {
    if (t.debuggerBlocked || this.denied.has(t.browserTabId) || this.owned.has(t.browserTabId)) return;
    if (this.attaching.has(t.browserTabId)) return this.attaching.get(t.browserTabId);
    const token = this.host.token(t, 'network');
    const task = (async () => {
      if (!this.host.valid(token)) return;
      try {
        await chrome.debugger.attach({ tabId: t.browserTabId }, '1.3');
        this.owned.set(t.browserTabId, t);
        if (!this.host.valid(token)) { await this.detachOwned(t); return; }
        const session = this.session(t, { tabId: t.browserTabId }, false);
        await this.enable(session);
      } catch (e) {
        if (this.host.valid(token)) {
          this.denied.add(t.browserTabId);
          t.debuggerBlocked = true;
          for (const c of ['network', 'runtime'] as const) this.host.channelLost(t, c, `debugger_attach_failed:${cleanText(String(e))}`);
        }
      }
    })().finally(() => this.attaching.delete(t.browserTabId));
    this.attaching.set(t.browserTabId, task); return task;
  }
  private session(t: Target, source: FlatDebuggee, worker: boolean): DebugSession {
    const key = uuid(); const networkToken = this.host.token(t, 'network'); const runtimeToken = this.host.token(t, 'runtime');
    let queue = this.bodyQueues.get(t.tabInstanceId);
    if (!queue) { queue = new BodyQueue(this.host.recording.policy.budgets.bodyConcurrency, this.host.recording.policy.budgets.queueBytes); this.bodyQueues.set(t.tabInstanceId, queue); }
    const s: DebugSession = { key, source, target: t, networkToken, runtimeToken, frames: new Map(), contexts: new Map(), worker, stopped: false, failed: new Set(), isolatedContexts: new Map(), documents: new Map(), probes: new Set(),
      network: new NetworkCollector(this.host, t, networkToken, key, (m, p) => this.send(s, m, p), (frame, loader) => {
        // A navigation request arrives before frameNavigated. Never borrow the old document.
        if (!loader || s.frames.get(frame ?? '')?.loaderId !== loader) return null;
        const binding = s.documents.get(frame ?? ''); return binding ? this.host.documentBinding?.(t, binding.ticketId) ?? null : null;
      }, queue) };
    this.sessions.set(this.key(source), s); return s;
  }
  private send(s: DebugSession, method: string, params = {}): Promise<any> {
    if (s.stopped || (!this.host.valid(s.networkToken) && !this.host.valid(s.runtimeToken))) return Promise.reject(new Error('capture_stopped'));
    return chrome.debugger.sendCommand(s.source, method, params);
  }
  private async enable(s: DebugSession) {
    const t = s.target;
    if (!s.worker) {
      try {
        await this.send(s, 'Page.enable');
        const data = await this.send(s, 'Page.getFrameTree');
        const walk = (n: any) => { this.frame(s, n.frame); for (const c of n.childFrames ?? []) walk(c); }; if (data.frameTree) walk(data.frameTree);
      } catch { if (this.host.valid(s.networkToken)) this.host.diagnostic('cdp_frame_mapping_unavailable', '无法建立 CDP frame 映射，未知 frame 的业务事件被排除', t, 'network'); }
    }
    for (const channel of ['network', 'runtime'] as const) {
      const token = channel === 'network' ? s.networkToken : s.runtimeToken;
      if (!this.host.valid(token)) continue;
      try {
        const bodyBytes = this.host.recording.policy.budgets.bodyBytes;
        // Inspector text storage can use two bytes per character. Honor larger configured
        // body limits without leaving a fixed 2 MiB resource buffer that evicts them first.
        await this.send(s, channel === 'network' ? 'Network.enable' : 'Runtime.enable', channel === 'network' ? { maxTotalBufferSize: Math.max(8 * 1024 * 1024, 4 * bodyBytes), maxResourceBufferSize: 2 * bodyBytes, maxPostDataSize: bodyBytes } : {});
        if (this.host.valid(token) && !s.source.sessionId) this.host.channelReady(t, channel);
      } catch (e) {
        s.failed.add(channel);
        if (this.host.valid(token)) {
          if (!s.source.sessionId) this.host.channelLost(t, channel, `${channel}_enable_failed`);
          this.host.diagnostic(`${channel}_enable_failed:${s.key}`, cleanText(String(e)), t, channel);
        }
      }
    }
    try { await this.send(s, 'Log.enable'); } catch { /* Dedicated workers may not support Log. */ }
    try {
      await this.send(s, 'Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true, filter: [{ type: 'iframe', exclude: false }, { type: 'worker', exclude: false }, { exclude: true }] });
    } catch { if (this.host.valid(s.networkToken)) this.host.diagnostic('child_autoattach_unavailable', '专属 iframe/worker 子会话自动附加不可用', t, 'network'); }
  }
  private frame(s: DebugSession, frame: any) {
    if (!frame?.id) return;
    const allowed = this.host.permittedKnown(frame.url);
    // Same-process frame permission is checked against the frozen, granted page origins.
    s.frames.set(frame.id, { url: frame.url, allowed, loaderId: frame.loaderId });
  }
  async refreshMappings(t: Target) {
    await Promise.all([...this.sessions.values()].filter(s => s.target === t && !s.stopped).flatMap(s => [...s.isolatedContexts].map(([id, frame]) => this.mapContext(s, id, frame))));
  }
  private async mapContext(s: DebugSession, id: number, frame: string) {
    if (s.probes.has(id) || !this.host.documentBinding) return;
    s.probes.add(id);
    try {
      // Only this extension's isolated world; no page getters or page-provided IDs.
      const result = await this.send(s, 'Runtime.evaluate', { contextId: id, expression: 'globalThis.__mesEvidenceDocument', returnByValue: true, silent: true, throwOnSideEffect: true });
      const binding = typeof result.result?.value === 'string' ? this.host.documentBinding(s.target, result.result.value) : null;
      if (binding && !s.stopped && s.isolatedContexts.get(id) === frame && s.frames.get(frame)?.allowed) s.documents.set(frame, { ticketId: result.result.value, context: binding });
    } catch { /* Absence is explicit on each request; never guess from URL. */ }
    finally { s.probes.delete(id); }
  }
  event(source: chrome.debugger.Debuggee, method: string, p: any) {
    const s = this.sessions.get(this.key(source));
    if (!s || s.stopped) return;
    if (method === 'Target.attachedToTarget') { void this.child(s, p); return; }
    if (method === 'Target.detachedFromTarget') {
      const childKey = this.key({ tabId: source.tabId, sessionId: p.sessionId });
      const child = this.sessions.get(childKey); if (child) { child.stopped = true; child.network.stop('child_target_detached'); this.sessions.delete(childKey); this.host.diagnostic('child_target_detached', '专属子 target 已结束', child.target, 'network'); } return;
    }
    if (!this.host.valid(s.networkToken) && !this.host.valid(s.runtimeToken)) return;
    if (method === 'Page.frameNavigated') { s.documents.delete(p.frame.id); this.frame(s, p.frame); return; }
    if (method === 'Page.frameDetached') {
      const binding = s.documents.get(p.frameId);
      if (p.reason === 'remove' && binding?.context.documentId) this.host.documentEnded?.(s.target, binding.context.documentId, 'frame_removed');
      s.frames.delete(p.frameId); s.documents.delete(p.frameId); return;
    }
    if (method === 'Runtime.executionContextCreated') {
      const context = p.context; const frame = context?.auxData?.frameId;
      if (frame) {
        s.contexts.set(context.id, frame);
        if (context.auxData.isDefault === false && (context.origin === `chrome-extension://${chrome.runtime.id}` || context.name === `chrome-extension://${chrome.runtime.id}` || context.name === chrome.runtime.id)) {
          s.isolatedContexts.set(context.id, frame); void this.mapContext(s, context.id, frame);
        }
      }
      return;
    }
    if (method === 'Runtime.executionContextDestroyed') { const frame = s.isolatedContexts.get(p.executionContextId); if (frame) s.documents.delete(frame); s.isolatedContexts.delete(p.executionContextId); s.contexts.delete(p.executionContextId); return; }
    if (method === 'Runtime.executionContextsCleared') { s.contexts.clear(); s.isolatedContexts.clear(); s.documents.clear(); return; }
    if (method.startsWith('Network.')) {
      if (s.failed.has('network')) return;
      if (method === 'Network.requestWillBeSent' && !s.worker) {
        // CDP's documentURL is the requesting document, NOT the API URL or initiator.
        // It also exists before Page.frameNavigated for new frames/navigation requests.
        // This authorizes only this request; it cannot create a Chrome document binding.
        const cached = s.frames.get(p.frameId);
        const documentUrl = typeof p.documentURL === 'string' && p.documentURL ? p.documentURL :
          p.loaderId && p.loaderId === cached?.loaderId ? cached!.url : '';
        const authorized = typeof p.frameId === 'string' && !!p.frameId && this.host.permittedKnown(documentUrl);
        if (!authorized && apiAllowed(this.host.recording.policy, p.request?.url ?? '', p.type)) {
          const code = !p.frameId ? 'network_frame_missing' : !documentUrl ? 'network_frame_unknown' : 'network_frame_not_authorized';
          let origin = 'unknown'; try { origin = new URL(documentUrl).origin; } catch { /* metadata only */ }
          this.host.diagnostic(code, `请求来源未获授权；${JSON.stringify({ requestId: String(p.requestId).slice(0, 256), frameId: String(p.frameId ?? '').slice(0, 256), documentOrigin: origin, resourceType: p.type })}`, s.target, 'network');
        }
        // Even an excluded redirect consumes its protocol hop; no headers/body are saved.
        s.network.event(method, p, authorized); return;
      }
      if (method === 'Network.webSocketCreated' && !s.worker) {
        // CDP has no frameId on this event. Stack URL is insufficient to authorize an arbitrary embedded frame.
        if (s.frames.size !== 1 || !this.host.permittedKnown([...s.frames.values()][0]?.url ?? '')) { this.host.diagnostic('websocket_frame_ambiguous', '含多个 frame 的 WebSocket 来源无法唯一确认，未采集', s.target, 'network'); return; }
      }
      s.network.event(method, p); return;
    }
    if (!this.host.valid(s.runtimeToken) || s.failed.has('runtime')) return;
    if (method === 'Runtime.consoleAPICalled' || method === 'Runtime.exceptionThrown') {
      const context = method === 'Runtime.consoleAPICalled' ? p.executionContextId : p.exceptionDetails?.executionContextId;
      if (!s.worker && !this.host.permittedKnown(s.frames.get(s.contexts.get(context) ?? '')?.url ?? '')) return;
      if (method === 'Runtime.consoleAPICalled' && !['warning', 'error', 'assert'].includes(p.type)) return;
      if (method === 'Runtime.exceptionThrown' && Number.isSafeInteger(p.exceptionDetails?.exceptionId)) {
        const identity = `${s.key}:${context}:${p.exceptionDetails.exceptionId}:${p.timestamp}`;
        if (this.exceptions.has(identity)) { this.host.recording.capabilities.duplicateErrorTransports = Number(this.host.recording.capabilities.duplicateErrorTransports ?? 0) + 1; return; }
        this.exceptions.add(identity); if (this.exceptions.size > 4096) this.exceptions.delete(this.exceptions.values().next().value!);
      }
      const binding = s.documents.get(s.contexts.get(context) ?? '');
      const documentContext = binding ? this.host.documentBinding?.(s.target, binding.ticketId) ?? null : null;
      const payload = method === 'Runtime.consoleAPICalled' ? { level: p.type, args: (p.args ?? []).slice(0, 40).map(remotePreview), argumentCount: p.args?.length ?? 0, stackTrace: cleanValue(p.stackTrace), executionContextId: context } : { details: { ...cleanValue(p.exceptionDetails), exception: remotePreview(p.exceptionDetails?.exception) } };
      this.host.write(s.runtimeToken, method === 'Runtime.consoleAPICalled' ? 'browser.console' : 'browser.exception', { ...payload, documentContext, debuggerSessionKey: s.key, cdpFrameId: s.contexts.get(context) ?? null, deduplication: 'stable_exception_identity_only;other_sources_retained' }, { sourceTime: p.timestamp, sourceClock: 'cdp_epoch_ms', streamId: `${s.key}-runtime` });
    } else if (method === 'Log.entryAdded' && ['warning', 'error'].includes(p.entry?.level)) {
      if (!pageAllowed(this.host.recording.policy, p.entry?.url ?? '')) return;
      const { source, level, text, url, lineNumber, timestamp } = p.entry;
      this.host.write(s.runtimeToken, 'browser.diagnostic', cleanValue({ source, level, text, url, lineNumber, debuggerSessionKey: s.key, documentContext: null, mappingReason: 'log_has_no_verified_execution_context' }), { sourceTime: timestamp, sourceClock: 'cdp_epoch_ms', streamId: `${s.key}-runtime` });
    }
  }
  private async child(parent: DebugSession, p: any) {
    const source = { tabId: parent.source.tabId, sessionId: p.sessionId };
    const reject = () => chrome.debugger.sendCommand(parent.source, 'Target.detachFromTarget', { sessionId: p.sessionId }).catch(() => {});
    if (parent.stopped || !['iframe', 'worker'].includes(p.targetInfo?.type) || !this.host.valid(parent.networkToken)) { await reject(); return; }
    let url = p.targetInfo.url;
    if (!url) {
      // Worker targetInfo may be empty in the attach notification. Read metadata only; never pause it.
      const info = await chrome.debugger.sendCommand(source, 'Target.getTargetInfo').catch(() => null) as { targetInfo?: { url?: string } } | null;
      url = info?.targetInfo?.url ?? '';
    }
    // An OOPIF attachment may precede its first committed document. Read only frame
    // metadata while it is blank; do not enable business domains before permission.
    if (p.targetInfo.type === 'iframe') for (let attempt = 0; attempt < 10 && (!url || url === 'about:blank'); attempt++) {
      if (parent.stopped || !this.host.valid(parent.networkToken)) { await reject(); return; }
      const tree = await chrome.debugger.sendCommand(source, 'Page.getFrameTree').catch(() => null) as { frameTree?: { frame?: { url?: string } } } | null;
      url = tree?.frameTree?.frame?.url ?? url;
      if (!url || url === 'about:blank') await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!await this.host.permitted(url) || !this.host.valid(parent.networkToken)) { this.host.diagnostic('child_target_policy_excluded', `子 target (${p.targetInfo.type}) URL 未确认、无页面权限或不在允许域名内`, parent.target, 'network'); await reject(); return; }
    if (this.sessions.has(this.key(source))) return;
    const s = this.session(parent.target, source, p.targetInfo.type === 'worker');
    await this.enable(s);
  }
  detached(source: chrome.debugger.Debuggee, reason: string) {
    if (source.tabId === undefined) return;
    const t = this.owned.get(source.tabId); if (!t) return;
    this.owned.delete(source.tabId);
    for (const [key, s] of this.sessions) if (s.target === t) { s.stopped = true; s.network.stop(reason); this.sessions.delete(key); }
    if (t.accepting && t.lifecycle === 'OPEN') {
      this.denied.add(t.browserTabId);
      t.debuggerBlocked = true;
      for (const c of ['network', 'runtime'] as const) this.host.channelLost(t, c, `debugger_detached:${reason}`);
    }
  }
  private async detachOwned(t: Target) {
    if (this.owned.get(t.browserTabId) !== t) return;
    this.owned.delete(t.browserTabId);
    await chrome.debugger.detach({ tabId: t.browserTabId }).catch(() => {});
  }
  async stop(t: Target, reason: string) {
    for (const [key, s] of this.sessions) if (s.target === t) { s.stopped = true; s.network.stop(reason); this.sessions.delete(key); }
    await this.detachOwned(t);
  }
}
function remotePreview(o: any): unknown {
  if (!o) return null;
  if ('value' in o) {
    if (typeof o.value === 'string' && o.value.length > 8192) return { value: cleanText(o.value).slice(0, 8192), truncated: true, originalChars: o.value.length };
    return cleanValue(o.value);
  }
  if (o.preview?.properties) {
    const values: Record<string, unknown> = {};
    for (const p of o.preview.properties.slice(0, 40)) values[p.name] = sensitiveKey(p.name) ? MASK : cleanText(String(p.value ?? `[${p.type}]`)).slice(0, 2048);
    return { type: o.type, description: cleanText(String(o.description ?? '')).slice(0, 4000), preview: values, overflow: !!o.preview.overflow };
  }
  return { type: o.type, description: cleanText(String(o.description ?? '')).slice(0, 4000), status: 'preview_only_no_getters' };
}
