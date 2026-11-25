import type { PageTicket, CaptureFragment } from '../../shared/contracts';
import { bytes } from '../../shared/contracts';

// This isolated-world script collects no page content before a sender-bound ticket is granted.
const bridgeWindow = window as Window & { __mesEvidenceBridge?: { handshake: () => Promise<void>; stop: () => void } };
if (bridgeWindow.__mesEvidenceBridge) {
  void bridgeWindow.__mesEvidenceBridge.handshake();
} else {
  let ticket: PageTicket | undefined;
  let chain = Promise.resolve();
  let queued = 0;
  let disabled = false;
  const post = (type: string, data = {}) => window.postMessage({ channel: 'mes-evidence-v1', type, ...data }, location.origin);
  const stop = () => { disabled = true; if (ticket) post('stop', { nonce: ticket.nonce }); ticket = undefined; };
  async function handshake() {
    try {
      const result = await chrome.runtime.sendMessage({ type: 'page.handshake' });
      if (!result?.ok || !result.ticket) { stop(); return; }
      if (ticket && ticket.id !== result.ticket.id) post('stop', { nonce: ticket.nonce });
      ticket = result.ticket; disabled = false;
      Object.defineProperty(globalThis, '__mesEvidenceDocument', { configurable: true, value: ticket!.id });
      void chrome.runtime.sendMessage({ type: 'page.bound', ticketId: ticket!.id }).catch(() => {});
      post('start', { ticket });
    } catch { stop(); }
  }
  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== 'mes-evidence-v1') return;
    if (event.data.type === 'ready') { if (ticket && !disabled) post('start', { ticket }); return; }
    if (event.data.type !== 'packet' || !ticket || disabled || event.data.nonce !== ticket.nonce || typeof event.data.json !== 'string') return;
    const json: string = event.data.json; const current = ticket;
    const size = bytes(json);
    if (size > current.policy.budgets.baselineBytes || queued + size > current.policy.budgets.queueBytes) {
      void chrome.runtime.sendMessage({ type: 'page.transport_error', ticketId: current.id, code: 'page_queue_or_event_limit' }).catch(() => {}); stop(); return;
    }
    const packetId = event.data.seq;
    if (!Number.isSafeInteger(packetId) || packetId < 1) return;
    queued += size;
    chain = chain.then(async () => {
      if (disabled || ticket?.id !== current.id) return;
      // At most 3 UTF-8 bytes per UTF-16 code unit (surrogates together use 4).
      const length = Math.max(256, Math.floor((current.policy.budgets.ipcBytes - 2048) / 3));
      const parts: string[] = [];
      for (let i = 0; i < json.length;) {
        let end = Math.min(i + length, json.length);
        if (end < json.length && /[\uD800-\uDBFF]/.test(json[end - 1]!)) end--;
        parts.push(json.slice(i, end)); i = end;
      }
      for (let index = 0; index < parts.length; index++) {
        if (disabled || ticket?.id !== current.id) return;
        const message: CaptureFragment = { type: 'capture.batch', ticketId: current.id, packetId, index, total: parts.length, data: parts[index]! };
        let reply: any;
        for (let attempt = 0; attempt < 2; attempt++) {
          try { reply = await chrome.runtime.sendMessage(message); break; } catch { /* One idempotent transport retry. */ }
        }
        if (!reply?.ok) { if (ticket?.id === current.id) stop(); return; }
      }
    }).catch(() => { if (ticket?.id === current.id) stop(); }).finally(() => { queued -= size; });
  });
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message.type === 'page.stop') { stop(); respond({ stopped: true }); }
    if (message.type === 'page.snapshot' && ticket) { post('snapshot', { nonce: ticket.nonce, reason: message.reason }); respond({ requested: true }); }
    if (message.type === 'page.rehandshake') { void handshake().then(() => respond({ ok: true })); return true; }
  });
  window.addEventListener('pagehide', () => {
    if (ticket) {
      post('stop', { nonce: ticket.nonce });
      void chrome.runtime.sendMessage({ type: 'page.ended', ticketId: ticket.id }).catch(() => {});
    }
    disabled = true;
  });
  window.addEventListener('pageshow', event => { if (event.persisted) void handshake(); });
  bridgeWindow.__mesEvidenceBridge = { handshake, stop };
  void handshake();
}
