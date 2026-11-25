import { record } from '@rrweb/record';
import type { PageTicket } from '../../shared/contracts';
import { cleanRrweb, cleanText, cleanUrl, MASK } from '../../shared/redaction';
import { bytes } from '../../shared/contracts';
import { startSemantic } from './semantic';
import { pagePrivacy } from '../../shared/page-privacy';

type RecorderWindow = Window & { __mesEvidenceRecorder?: { stop: () => void; id: string | null } };
const w = window as RecorderWindow;
if (!w.__mesEvidenceRecorder) {
  const state = { stop: () => {}, id: null as string | null };
  w.__mesEvidenceRecorder = state;
  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== 'mes-evidence-v1') return;
    if (event.data.type === 'start' && event.data.ticket) {
      const ticket: PageTicket = event.data.ticket;
      if (state.id === ticket.id) return;
      state.stop();
      if (typeof ticket.id !== 'string' || !ticket.policy || ticket.documentId == null) return;
      state.id = ticket.id;
      state.stop = start(ticket, () => { state.id = null; });
    }
  });
}
window.postMessage({ channel: 'mes-evidence-v1', type: 'ready' }, location.origin);

function start(ticket: PageTicket, ended: () => void): () => void {
  let stopped = false; let seq = 0; let rrStop: (() => void) | undefined;
  const cleanup: (() => void)[] = [];
  const policy = ticket.policy;
  let privacy: ReturnType<typeof pagePrivacy>;
  try { privacy = pagePrivacy(policy, document); } catch { packet('capture.page_diagnostic', { code: 'invalid_sensitive_selector', detail: '脱敏选择器无效，页面采集未启动' }); return () => { ended(); }; }
  const sensitive = privacy.selector;
  function packet(kind: 'rrweb.event' | 'ui.observation' | 'capture.page_diagnostic', payload: Record<string, any>) {
    if (stopped) return;
    const item = { seq: ++seq, kind, sourceTime: performance.now(), payload };
    let json = JSON.stringify(item);
    let size = bytes(json);
    const styles: {id: number; attributes: {_cssText: string}}[] = [];
    const event = payload.rrwebEvent;
    // 保住完整 DOM 基线，把挤不进同一包的外部 CSS 按 rrweb 原生样式变更接在基线后。
    if (kind === 'rrweb.event' && size > policy.budgets.baselineBytes && event) {
      const pending = event.type === 2 ? [event.data.node] : (event.data?.adds ?? []).map((add: any) => add.node);
      while (pending.length) {
        const node = pending.pop();
        if (node.childNodes) for (const child of node.childNodes) pending.push(child);
        if (node.tagName !== 'link' || typeof node.attributes._cssText !== 'string') continue;
        const link = record.mirror.getNode(node.id) as HTMLLinkElement | null;
        styles.push({id:node.id, attributes:{_cssText:node.attributes._cssText}});
        delete node.attributes._cssText;
        if (link?.localName === 'link') {
          node.attributes.href = cleanUrl(link.href, policy.allowedQueryKeys);
          node.attributes.rel = link.rel;
        }
      }
      json = JSON.stringify(item);
      size = bytes(json);
    }
    if (size > policy.budgets.baselineBytes) {
      window.postMessage({ channel: 'mes-evidence-v1', type: 'packet', nonce: ticket.nonce, seq,
        json: JSON.stringify({ seq, kind: 'capture.page_diagnostic', sourceTime: performance.now(), payload: { code: 'baseline_or_event_too_large', detail: '事件未截断；停止流以保留依赖完整性' } }) }, location.origin);
      stop(); return;
    }
    window.postMessage({ channel: 'mes-evidence-v1', type: 'packet', nonce: ticket.nonce, seq, json }, location.origin);
    for (const style of styles) {
      const rrwebEvent = {type:3, timestamp:event.timestamp, data:{source:0, adds:[], removes:[], texts:[], attributes:[style]}};
      if (bytes(JSON.stringify(rrwebEvent)) + 512 > policy.budgets.baselineBytes) {
        packet('capture.page_diagnostic', {code:'stylesheet_too_large', detail:'单个样式表超过事件预算，保留页面结构。'});
      } else packet('rrweb.event', {rrwebEvent, nodeContexts:[]});
    }
  }
  const isSensitive = privacy.sensitive;
  const text = privacy.text;
  function inputValue(value: string, el: HTMLElement) { return !isSensitive(el) && (policy.allowedInputNames.includes('*') || policy.allowedInputNames.includes(el.getAttribute('name') ?? '')) ? cleanText(value) : MASK; }
  const children = new Map<Window, string>();
  const bindingFor = (node: Node | null): string | null => {
    const doc = node?.nodeType === 9 ? node as Document : node?.ownerDocument;
    try { return (doc?.defaultView as RecorderWindow | null)?.__mesEvidenceRecorder?.id ?? null; } catch { return null; }
  };
  const nodeRefs = (e: any) => {
    const ids = new Set<number>();
    const roots = new Set<number>();
    const tree = (n: any) => { if (!n) return; if (n.type === 0) { ids.add(n.id); roots.add(n.id); } for (const c of n.childNodes ?? []) tree(c); };
    tree(e.data?.node);
    if (typeof e.data?.id === 'number') ids.add(e.data.id);
    for (const a of ['texts', 'attributes', 'adds', 'removes', 'positions']) for (const item of e.data?.[a] ?? []) { if (typeof item.id === 'number') ids.add(item.id); if (typeof item.parentId === 'number') ids.add(item.parentId); tree(item.node); }
    if (e.mapping) for (const id of record.mirror.getIds()) if (record.mirror.getNode(id)?.nodeType === 9) { ids.add(id); roots.add(id); }
    const attached = new Map<number, string>();
    if (e.data?.isAttachIframe) for (const add of e.data.adds ?? []) {
      const iframe = record.mirror.getNode(add.parentId) as HTMLIFrameElement | null;
      const binding = iframe?.contentWindow && children.get(iframe.contentWindow);
      if (binding && add.node?.type === 0) attached.set(add.node.id, binding);
    }
    return [...ids].filter(id => Number.isSafeInteger(id) && id >= 0).slice(0, 4096).map(id => {
      const n = record.mirror.getNode(id);
      return { nodeId: id, recorderStreamId: ticket.recorderStreamId, documentRoot: roots.has(id), documentTicketId: attached.get(id) ?? bindingFor(n), documentRelation: n?.ownerDocument === document || n === document ? 'emitter_document' : 'unknown_or_child_document' };
    });
  };
  const onBinding = (event: MessageEvent) => {
    if (event.data?.channel !== 'mes-evidence-document' || typeof event.data.ticketId !== 'string' || !event.source || event.source === window) return;
    // Window identity, not a URL or sibling index, binds a direct child to its iframe.
    const owns = (doc: Document): boolean => [...doc.querySelectorAll('iframe')].some(f => {
      if (f.contentWindow === event.source) return true;
      try { return !!f.contentDocument && owns(f.contentDocument); } catch { return false; }
    });
    if (owns(document)) children.set(event.source as Window, event.data.ticketId);
    if (ticket.mode === 'top') packet('capture.page_diagnostic', { code: 'document_mapping', nodeContexts: nodeRefs({ mapping: true }) });
  };
  window.addEventListener('message', onBinding); cleanup.push(() => window.removeEventListener('message', onBinding));
  if (window.parent !== window) window.parent.postMessage({ channel: 'mes-evidence-document', ticketId: ticket.id }, '*');
  if (window.top && window.top !== window.parent) window.top.postMessage({ channel: 'mes-evidence-document', ticketId: ticket.id }, '*');
  // Parent owns same-origin frames. Only cross-origin children start another cooperating recorder.
  if (ticket.mode !== 'semantic-only') {
    try {
      rrStop = record({
        emit(event) { packet('rrweb.event', { rrwebEvent: cleanRrweb(event, policy), nodeContexts: nodeRefs(event) }); },
        recordCrossOriginIframes: true, recordAfter: 'DOMContentLoaded', blockSelector: [sensitive, '[data-mes-agent-host]'].filter(Boolean).join(','),
        maskAllInputs: true, maskInputFn: inputValue, maskTextSelector: '*', maskTextFn: (value, el) => text(value, el),
        inlineStylesheet: true, inlineImages: false, recordCanvas: false, collectFonts: false,
        slimDOMOptions: { script: true, comment: true, headMetaVerification: true },
        sampling: { mousemove: false, mouseInteraction: true, scroll: 250, input: 'all' },
        plugins: [{ name: 'mes-privacy', options: {}, observer: () => () => {}, eventProcessor: event => cleanRrweb(event, policy) }],
        errorHandler(error) { packet('capture.page_diagnostic', { code: 'rrweb_error', detail: cleanText(String(error)) }); return true; },
      });
      packet('capture.page_diagnostic', { code: 'recorder_started', mode: ticket.mode, timeOrigin: performance.timeOrigin });
    } catch (e) { packet('capture.page_diagnostic', { code: 'rrweb_start_failed', detail: cleanText(String(e)) }); }
  }
  const semantic = startSemantic(ticket, (kind, payload) => { packet(kind, payload); return seq; }, el => ticket.mode === 'top' ? record.mirror.getId(el) : -1);
  cleanup.push(semantic.stop);
  const snapshot = semantic.snapshot;
  const listen = (obj: EventTarget, name: string, cb: EventListener) => { obj.addEventListener(name, cb); cleanup.push(() => obj.removeEventListener(name, cb)); };
  listen(window, 'message', event => {
    const e = event as MessageEvent;
    if (e.source !== window || e.origin !== location.origin || e.data?.channel !== 'mes-evidence-v1' || e.data.nonce !== ticket.nonce) return;
    if (e.data.type === 'stop') stop();
    if (e.data.type === 'snapshot') snapshot(typeof e.data.reason === 'string' ? e.data.reason.slice(0, 100) : 'requested');
  });
  listen(window, 'pagehide', () => stop());
  snapshot('initial_state');
  function stop() {
    if (stopped) return;
    stopped = true;
    for (const fn of cleanup.reverse()) { try { fn(); } catch { /* Never modify the application's cleanup path. */ } }
    rrStop?.(); ended();
  }
  return stop;
}
