import { bytes, now, SCHEMA_VERSION, uuid, type BlobRecord, type CaptureToken, type Context, type NetworkRecord, type Policy, type Recording, type Target } from '../../../shared/contracts';
import { extractFacts, projectVersions } from '../../../shared/correlation';
import { apiAllowed } from '../../../shared/policy';
import { cleanHeaders, cleanText, cleanUrl, cleanValue, emptyBody, sanitizeBody } from '../../../shared/redaction';

export interface CaptureHost {
  recording: Recording;
  valid(token: CaptureToken): boolean;
  write(token: CaptureToken, kind: string, payload: Record<string, any>, meta?: { sourceTime?: number; sourceClock?: string; streamId?: string }, network?: NetworkRecord, blobs?: BlobRecord[]): string | null;
  diagnostic(code: string, detail: string, target?: Target, channel?: 'network' | 'runtime' | 'page' | 'semantic' | 'screenshot'): void;
  finalizeNetwork(target: Target, record: NetworkRecord): void;
  late(target: Target): void;
}
interface Extra { headers: Record<string, string>; statusCode?: number }
interface Hop { record?: NetworkRecord; expectsExtra?: boolean; requestExtra?: Extra; responseExtra?: Extra; decodedBytes?: number }
interface Chain { hops: Hop[]; requestExtras: Extra[]; responseExtras: Extra[] }

/** Redirect-aware queues. Extra headers are merged only after protocol flags make the mapping unique. */
export class ExtraInfoChain {
  chains = new Map<string, Chain>();
  get(id: string): Chain { let c = this.chains.get(id); if (!c) { c = { hops: [], requestExtras: [], responseExtras: [] }; this.chains.set(id, c); } return c; }
  addHop(id: string, record?: NetworkRecord) { const hop: Hop = { record }; this.get(id).hops.push(hop); return hop; }
  extra(id: string, side: 'request' | 'response', p: any) {
    const c = this.get(id); const list = side === 'request' ? c.requestExtras : c.responseExtras;
    if (list.length >= 128) return;
    list.push({ headers: cleanHeaders(p.headers), ...(side === 'response' ? { statusCode: p.statusCode } : {}) });
  }
  resolve(id: string): NetworkRecord[] {
    const c = this.get(id); const changed: NetworkRecord[] = [];
    // False skips a hop, unknown is a barrier. Do not let a later response steal a previous hop's headers.
    let req = 0; let res = 0; let blocked = false;
    for (const h of c.hops) {
      if (h.expectsExtra === undefined) { blocked = true; continue; }
      if (!h.expectsExtra) {
        if (h.record && h.record.extraInfoStatus !== 'not_expected') { h.record.extraInfoStatus = 'not_expected'; changed.push(h.record); }
        continue;
      }
      if (blocked) continue;
      const a = c.requestExtras[req++]; const b = c.responseExtras[res++];
      if (a && !h.requestExtra) { h.requestExtra = a; if (h.record) { h.record.request.headers = { ...h.record.request.headers, ...a.headers }; changed.push(h.record); } }
      if (b && !h.responseExtra) { h.responseExtra = b; if (h.record) { h.record.response.headers = { ...h.record.response.headers, ...b.headers }; changed.push(h.record); } }
      if (h.record) h.record.extraInfoStatus = h.requestExtra && h.responseExtra ? 'matched_by_protocol_order' : 'pending';
    }
    return [...new Set(changed)];
  }
}

export class BodyQueue {
  private running = 0;
  private reservedBytes = 0;
  private tasks: { owner: string; valid: () => boolean; run: () => Promise<void>; bytes: number }[] = [];
  private peakRunning = 0; private peakWaiting = 0; private peakBytes = 0;
  constructor(private concurrency: number, private maxBytes = 16 * 1024 * 1024) {}
  add(owner: string, valid: () => boolean, run: () => Promise<void>, bytes: number): boolean {
    if (!valid() || this.tasks.length >= 128 || this.reservedBytes + bytes > this.maxBytes) return false;
    this.tasks.push({ owner, valid, run, bytes }); this.reservedBytes += bytes; this.peakBytes = Math.max(this.peakBytes, this.reservedBytes);
    this.peakWaiting = Math.max(this.peakWaiting, this.tasks.length); this.drain(); return true;
  }
  cancel(owner: string) { this.tasks = this.tasks.filter(t => { if (t.owner !== owner) return true; this.reservedBytes -= t.bytes; return false; }); }
  stats() { return { running: this.running, waiting: this.tasks.length, reservedBytes: this.reservedBytes, peakRunning: this.peakRunning, peakWaiting: this.peakWaiting, peakReservedBytes: this.peakBytes, byteMeaning: 'maximum_body_bytes_reserved;not_measured_heap' }; }
  private drain() {
    while (this.running < this.concurrency && this.tasks.length) {
      const task = this.tasks.shift()!;
      if (!task.valid()) { this.reservedBytes -= task.bytes; continue; }
      this.running++; this.peakRunning = Math.max(this.peakRunning, this.running);
      void task.run().catch(() => {}).finally(() => { this.running--; this.reservedBytes -= task.bytes; this.drain(); });
    }
  }
}

export class NetworkCollector {
  readonly chains = new ExtraInfoChain();
  readonly records = new Map<string, NetworkRecord>();
  private queue: BodyQueue;
  private sourceSeq = 0;
  private stopped = false;
  private sockets = new Map<string, NetworkRecord>();
  private retired = new Set<string>();
  private policy: Policy;
  constructor(private host: CaptureHost, readonly target: Target, readonly token: CaptureToken, readonly sessionKey: string, private send: (method: string, params?: object) => Promise<any>, private documentContext: (frame?: string, loader?: string) => Context | null = () => null, queue?: BodyQueue) {
    this.policy = host.recording.policy; this.queue = queue ?? new BodyQueue(this.policy.budgets.bodyConcurrency, this.policy.budgets.queueBytes);
  }
  private valid() { return !this.stopped && this.host.valid(this.token); }
  private enqueue(task: () => Promise<void>) { return this.queue.add(this.sessionKey, () => this.valid(), task, this.policy.budgets.bodyBytes); }
  private emit(kind: string, record: NetworkRecord, p: any = {}) {
    this.correlate(record);
    const accepted = this.host.write(this.token, kind, { requestKey: record.requestKey, ...p }, { sourceTime: p.timestamp, sourceClock: 'cdp_monotonic_seconds', streamId: this.sessionKey }, record);
    if (accepted) { this.records.set(record.requestKey, structuredClone(record)); projectVersions(this.host.recording, record.correlationFacts ?? [], `requestKey:${record.requestKey}`); }
  }
  private correlate(r: NetworkRecord) {
    const h = r.response.headers; const q = r.request.headers;
    if (h['x-request-id'] || h['request-id']) { r.serverCorrelation.requestId = h['x-request-id'] ?? h['request-id']!; r.serverCorrelation.requestIdSource = `response_header:${h['x-request-id'] ? 'x-request-id' : 'request-id'}`; }
    const trace = h.traceparent ?? q.traceparent;
    const m = trace?.match(/^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$/i);
    if (m) { r.serverCorrelation.traceId = m[1]!; r.serverCorrelation.spanId = m[2]!; r.serverCorrelation.traceIdSource = h.traceparent ? 'response_header:traceparent' : 'request_header:traceparent'; }
    this.facts(r, extractFacts(this.policy, r.request.url, 'response_header', h));
  }
  private facts(r: NetworkRecord, facts: NonNullable<NetworkRecord['correlationFacts']>) {
    r.correlationFacts ??= [];
    for (const fact of facts) if (!r.correlationFacts.some(f => f.field === fact.field && f.value === fact.value && f.source === fact.source && f.component === fact.component)) r.correlationFacts.push(fact);
    for (const field of ['requestId', 'traceId', 'spanId'] as const) {
      const found = r.correlationFacts.filter(f => f.field === field); const values = [...new Set(found.map(f => f.value))];
      if (values.length) { r.serverCorrelation[field] = values.length === 1 ? values[0]! : null; if (field !== 'spanId') r.serverCorrelation[`${field}Source`] = values.length === 1 ? found[0]!.source : 'conflicting_sources;see_correlationFacts'; }
    }
  }

  event(method: string, p: any, requestAuthorized = true) {
    if (!this.valid()) return;
    this.sourceSeq++;
    const id = String(p.requestId ?? '');
    if (!id || id.length > 256) return;
    if (method === 'Network.requestWillBeSent') { this.request(id, p, requestAuthorized); return; }
    if (this.retired.has(id)) return;
    if (method.endsWith('ExtraInfo')) {
      if (!this.chains.chains.has(id) && this.chains.chains.size >= 5000) { this.host.diagnostic('network_queue_limit', 'ExtraInfo 缓冲上限，无法确认的额外头未保存', this.target, 'network'); return; }
      this.chains.extra(id, method.includes('requestWill') ? 'request' : 'response', p);
      for (const r of this.chains.resolve(id)) this.emit('network.extra_info', r);
      return;
    }
    if (method === 'Network.webSocketCreated') { this.socket(id, p); return; }
    if (/Network.webSocket(FrameSent|FrameReceived|Closed|FrameError|HandshakeResponseReceived)/.test(method)) { this.streaming(id, method, p); return; }
    const c = this.chains.chains.get(id); const hop = c?.hops.at(-1); const r = hop?.record;
    if (method === 'Network.responseReceived' && hop) {
      hop.expectsExtra = typeof p.hasExtraInfo === 'boolean' ? p.hasExtraInfo : undefined;
      if (r) {
        this.response(r, p.response); this.emit('network.response_observed', r, { response: r.response, timestamp: p.timestamp });
      }
      for (const changed of this.chains.resolve(id)) this.emit('network.extra_info', changed);
      return;
    }
    if (!r) return;
    if (method === 'Network.dataReceived') {
      // dataLength is decoded bytes, unlike Content-Length/encodedDataLength for gzip.
      if (Number.isSafeInteger(p.dataLength) && p.dataLength >= 0) hop!.decodedBytes = Math.min(Number.MAX_SAFE_INTEGER, (hop!.decodedBytes ?? 0) + p.dataLength);
    } else if (method === 'Network.loadingFinished') {
      r.networkOutcome = 'finished'; r.endedAt = now(); this.emit('network.loading_finished', r, { timestamp: p.timestamp, encodedDataLength: p.encodedDataLength });
      this.readResponse(r, hop!.decodedBytes ?? 0);
    } else if (method === 'Network.loadingFailed') {
      r.networkOutcome = 'failed'; r.endedAt = now(); r.error = cleanText(String(p.errorText));
      r.response = { ...r.response, ...emptyBody('unavailable', p.canceled ? 'network_cancelled' : 'network_failed') };
      this.emit('network.request_finalized', r, { error: r.error, canceled: !!p.canceled, timestamp: p.timestamp });
    } else if (method === 'Network.eventSourceMessageReceived' && this.policy.captureStreaming) {
      this.message(r, 'received', p.data, p.timestamp, { eventName: cleanText(String(p.eventName)), eventId: cleanText(String(p.eventId)) });
    }
  }
  private request(id: string, p: any, authorized = true) {
    if (!this.chains.chains.has(id) && this.chains.chains.size >= 5000) { this.host.diagnostic('network_metadata_limit', '请求链缓冲达到 5000 上限，新请求未保存；请结束本次并创建新会话', this.target, 'network'); return; }
    const c = this.chains.get(id);
    if (c.hops.length >= 64) { this.host.diagnostic('network_metadata_limit', '请求链缓冲达到上限', this.target, 'network'); return; }
    const previous = c.hops.at(-1);
    if (p.redirectResponse && previous) {
      previous.expectsExtra = typeof p.redirectHasExtraInfo === 'boolean' ? p.redirectHasExtraInfo : undefined;
      if (previous.record) {
        this.response(previous.record, p.redirectResponse); previous.record.networkOutcome = 'finished'; previous.record.endedAt = now();
        previous.record.response = { ...previous.record.response, ...emptyBody('unavailable', 'redirect_body_not_available') };
        this.emit('network.request_finalized', previous.record, { redirect: true });
      }
    }
    const hop = this.chains.addHop(id);
    for (const changed of this.chains.resolve(id)) this.emit('network.extra_info', changed);
    const request = p.request;
    // Keep an empty hop for excluded frames/APIs so redirects cannot steal ExtraInfo.
    if (!authorized || !request || !apiAllowed(this.policy, request.url, p.type)) return;
    const ordinal = c.hops.length - 1;
    const context = this.documentContext(p.frameId, p.loaderId);
    const r: NetworkRecord = {
      schemaVersion: SCHEMA_VERSION, requestKey: `${this.token.recordingId}:${this.target.tabInstanceId}:${this.sessionKey}:${id}:${ordinal}`,
      recordingId: this.token.recordingId, browserRunId: this.token.browserRunId, tabInstanceId: this.target.tabInstanceId,
      debuggerSessionKey: this.sessionKey, cdpRequestId: id, redirectOrdinal: ordinal, cdpFrameId: p.frameId, chromeFrameId: context?.chromeFrameId ?? null, documentId: context?.documentId ?? null, loaderId: p.loaderId,
      frameMappingReason: context ? 'isolated_world_ticket_and_message_sender' : 'document_binding_unconfirmed_at_request',
      request: { method: String(request.method), url: cleanUrl(request.url, this.policy.allowedQueryKeys), headers: cleanHeaders(request.headers), type: p.type, initiator: cleanValue(p.initiator), ...emptyBody(request.hasPostData || request.postData ? 'unavailable' : 'empty', request.hasPostData ? 'pending_read' : null) },
      response: { httpStatus: 'unknown', headers: {}, ...emptyBody() }, networkOutcome: 'incomplete', businessOutcome: 'unknown',
      serverCorrelation: { requestId: null, requestIdSource: null, traceId: null, traceIdSource: null }, startedAt: now(), sourceTime: p.timestamp, sourceClock: 'cdp_monotonic_seconds',
      evidenceRefs: [], actionCandidates: [], extraInfoStatus: 'pending',
    };
    hop.record = r;
    this.emit('network.request_observed', r, { request: r.request, timestamp: p.timestamp, wallTime: p.wallTime });
    if (typeof request.postData === 'string') this.body(r, 'request', request.postData, r.request.headers['content-type'] ?? '');
    else if (request.hasPostData) {
      if (!this.enqueue(async () => {
        if (!this.valid()) return;
        if (this.chains.chains.get(id)?.hops.at(-1)?.record !== r) { r.request = { ...r.request, ...emptyBody('unavailable', 'redirect_reused_request_id') }; this.emit('network.body_unavailable', r); return; }
        try {
          const data = await this.send('Network.getRequestPostData', { requestId: id });
          if (!this.valid()) { this.host.late(this.target); return; }
          // A redirect may have reused this CDP request ID while the command was in flight.
          if (this.chains.chains.get(id)?.hops.at(-1)?.record !== r) { r.request = { ...r.request, ...emptyBody('unavailable', 'redirect_reused_request_id') }; this.emit('network.body_unavailable', r); return; }
          if (typeof data?.postData !== 'string') { r.request = { ...r.request, ...emptyBody('unavailable', 'invalid_request_body_result') }; this.emit('network.body_unavailable', r); return; }
          this.body(r, 'request', data.postData, r.request.headers['content-type'] ?? '');
        } catch { if (this.valid()) { r.request = { ...r.request, ...emptyBody('unavailable', 'getRequestPostData_failed') }; this.emit('network.body_unavailable', r); } }
      })) { r.request = { ...r.request, ...emptyBody('unavailable', 'body_queue_limit') }; this.emit('network.body_unavailable', r); }
    }
  }
  private response(r: NetworkRecord, p: any) {
    r.response = { ...r.response, httpStatus: p.status, headers: cleanHeaders(p.headers), mimeType: p.mimeType, fromDiskCache: !!p.fromDiskCache, fromServiceWorker: !!p.fromServiceWorker };
  }
  private readResponse(r: NetworkRecord, decodedBytes: number) {
    const mime = r.response.mimeType ?? r.response.headers['content-type'] ?? '';
    const size = r.response.headers['content-encoding'] && r.response.headers['content-encoding'] !== 'identity' ? NaN : Number(r.response.headers['content-length']);
    if (r.request.method === 'HEAD' || [204, 304].includes(Number(r.response.httpStatus))) { r.response = { ...r.response, ...emptyBody('empty', null) }; this.emit('network.request_finalized', r); return; }
    if (decodedBytes > this.policy.budgets.bodyBytes) {
      r.response = { ...r.response, ...emptyBody('excluded_by_policy', 'decoded_body_size_limit'), originalBytes: decodedBytes, savedBytes: 0 }; this.emit('network.request_finalized', r); return;
    }
    if ((!/json|x-www-form-urlencoded|^text\/plain\b/i.test(mime)) || (Number.isFinite(size) && size > this.policy.budgets.bodyBytes)) {
      r.response = { ...r.response, ...emptyBody('excluded_by_policy', size > this.policy.budgets.bodyBytes ? 'content_length_limit' : 'unsupported_or_binary_mime') }; this.emit('network.request_finalized', r); return;
    }
    if (!this.enqueue(async () => {
      if (!this.valid()) return;
      if (this.chains.chains.get(r.cdpRequestId)?.hops.at(-1)?.record !== r) { r.response = { ...r.response, ...emptyBody('unavailable', 'redirect_reused_request_id') }; this.emit('network.body_unavailable', r); return; }
      let data: any;
      try { data = await this.send('Network.getResponseBody', { requestId: r.cdpRequestId }); }
      catch (error) {
        if (!this.valid()) { this.host.late(this.target); return; }
        // Classify known CDP failures; do not persist raw error text or replay requests.
        const message = String(error);
        const reason = /evicted from inspector cache/i.test(message) ? 'inspector_cache_evicted' : /No resource with given identifier/i.test(message) ? 'response_resource_unavailable' : 'getResponseBody_failed';
        r.response = { ...r.response, ...emptyBody('unavailable', reason) }; this.emit('network.request_finalized', r); return;
      }
      if (!this.valid()) { this.host.late(this.target); return; }
      if (this.chains.chains.get(r.cdpRequestId)?.hops.at(-1)?.record !== r) { r.response = { ...r.response, ...emptyBody('unavailable', 'redirect_reused_request_id') }; this.emit('network.body_unavailable', r); return; }
      if (typeof data?.body !== 'string') { r.response = { ...r.response, ...emptyBody('unavailable', 'invalid_response_body_result') }; this.emit('network.request_finalized', r); return; }
      if (data.base64Encoded && data.body.length > Math.ceil(this.policy.budgets.bodyBytes / 3) * 4) { r.response = { ...r.response, ...emptyBody('excluded_by_policy', 'body_size_limit') }; this.emit('network.request_finalized', r); return; }
      let raw: string;
      try { raw = data.base64Encoded ? new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(atob(data.body), c => c.charCodeAt(0))) : data.body; }
      catch { r.response = { ...r.response, ...emptyBody('unavailable', 'invalid_response_body_encoding') }; this.emit('network.request_finalized', r); return; }
      this.body(r, 'response', raw, mime);
    })) { r.response = { ...r.response, ...emptyBody('unavailable', 'body_queue_limit') }; this.emit('network.request_finalized', r); }
  }
  private body(r: NetworkRecord, side: 'request' | 'response', raw: string, mime: string) {
    if (!this.valid()) { this.host.late(this.target); return; }
    const result = sanitizeBody(raw, mime, this.policy); const blobs: BlobRecord[] = [];
    Object.assign(r[side], result.fields);
    if (result.content !== undefined) {
      const savedMime = result.mime ?? mime;
      const id = uuid(); const path = `bodies/${id}.${/json/i.test(savedMime) ? 'json' : 'txt'}`;
      r[side].bodyRef = path; blobs.push({ id, recordingId: r.recordingId, path, mime: savedMime, encoding: 'utf8', data: result.content });
    }
    if (side === 'response' && result.parsed !== undefined) {
      this.facts(r, extractFacts(this.policy, r.request.url, 'response_json', result.parsed));
      const u = new URL(r.request.url);
      const rule = this.policy.businessRules.find(x => x.origin === u.origin && u.pathname.startsWith(x.pathPrefix));
      if (rule) {
        const code = rule.codePath.split('.').reduce<any>((v, k) => v && typeof v === 'object' && Object.hasOwn(v, k) ? v[k] : undefined, result.parsed);
        if (typeof code === 'string' || typeof code === 'number') { r.businessCode = code; r.businessOutcome = rule.successValues.includes(code) ? 'success' : 'failure'; }
      }
    }
    const accepted = this.host.write(this.token, side === 'response' ? 'network.request_finalized' : 'network.request_body', { requestKey: r.requestKey, side, bodyCaptureStatus: r[side].bodyCaptureStatus, bodyRef: r[side].bodyRef, businessOutcome: r.businessOutcome }, { streamId: this.sessionKey }, r, blobs);
    if (accepted) { this.records.set(r.requestKey, structuredClone(r)); projectVersions(this.host.recording, r.correlationFacts ?? [], `requestKey:${r.requestKey}`); }
  }
  private socket(id: string, p: any) {
    if (!apiAllowed(this.policy, p.url, 'WebSocket')) return;
    this.request(id, { request: { url: p.url, method: 'GET', headers: {} }, type: 'WebSocket', timestamp: p.timestamp });
    const r = this.chains.chains.get(id)?.hops.at(-1)?.record;
    if (r) { r.request = { ...r.request, ...emptyBody('not_applicable', null) }; r.response = { ...r.response, ...emptyBody('not_applicable', null) }; this.sockets.set(id, r); }
  }
  private streaming(id: string, method: string, p: any) {
    const r = this.sockets.get(id); if (!r) return;
    if (method.endsWith('HandshakeResponseReceived')) { this.response(r, { status: p.response.status, headers: p.response.headers, mimeType: 'websocket' }); this.emit('network.response_observed', r); }
    else if (method.endsWith('Closed')) { r.networkOutcome = 'finished'; r.endedAt = now(); this.emit('network.request_finalized', r); this.sockets.delete(id); }
    else if (method.endsWith('FrameError')) { r.error = cleanText(p.errorMessage); this.emit('network.stream_error', r, { error: r.error }); }
    else if (this.policy.captureStreaming) {
      if (p.response.opcode === 1) this.message(r, method.endsWith('FrameSent') ? 'sent' : 'received', p.response.payloadData, p.timestamp);
      else this.emit('network.stream_message', r, { opcode: p.response.opcode, bodyCaptureStatus: 'excluded_by_policy', reason: 'binary_frame', timestamp: p.timestamp });
    }
  }
  private message(r: NetworkRecord, direction: string, raw: string, timestamp: number, extra = {}) {
    const data = sanitizeBody(raw, 'application/json', this.policy);
    this.emit('network.stream_message', r, { direction, timestamp, ...extra, bodyCaptureStatus: data.fields.bodyCaptureStatus, reason: data.fields.bodyCaptureReason, data: data.parsed ?? null });
  }
  stop(reason: string) {
    this.stopped = true; this.queue.cancel(this.sessionKey);
    for (const r of this.records.values()) {
      const status = reason === 'tab_closed' || reason === 'target_closed' ? 'incomplete_target_closed' : reason === 'session_stopped' || reason === 'quota_exceeded' ? 'incomplete_session_stopped' : 'unavailable';
      let changed = false;
      if (r.networkOutcome === 'incomplete') r.error = reason;
      for (const side of ['request', 'response'] as const) if (r[side].bodyCaptureStatus === 'unavailable' && ['not_received', 'pending_read'].includes(r[side].bodyCaptureReason ?? '')) { Object.assign(r[side], emptyBody(status, reason)); changed = true; }
      if (r.extraInfoStatus === 'pending') { r.extraInfoStatus = 'unresolved_at_cutoff'; changed = true; }
      // Only previously accepted fields are finalized. No CDP call or fresh business data here.
      if (changed || r.networkOutcome === 'incomplete') this.host.finalizeNetwork(this.target, r);
    }
  }
}
