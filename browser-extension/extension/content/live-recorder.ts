import { record } from '@rrweb/record';
import {
  actions,
  matchesPage,
  safeElement,
  structuralBaseline,
  structuralMutation,
  type PageEvidence,
} from '../../shared/live-page';
import type { WorkshopBinding } from '../../shared/workshop';

type Ticket = { id: string; binding: WorkshopBinding; rules: WorkshopBinding[]; platformOrigin: string };
type Recorder = { id?: string; paused: boolean; stop: () => void; updateRules?: (rules: WorkshopBinding[]) => boolean };
const isolated = globalThis as typeof globalThis & {
  __mesContinuous?: Recorder;
  __mesLiveTicket?: string;
  navigation?: EventTarget;
};
if (!isolated.__mesContinuous && window.top === window) {
  const state: Recorder = { paused: false, stop: () => {} };
  isolated.__mesContinuous = state;
  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message.type === 'live.rules') {
      reply({ok: message.ticket === state.id && !!state.updateRules?.(message.rules)});
      return;
    }
    if (message.type === 'live.end') {
      if (message.ticket === state.id) state.stop();
      return;
    }
    if (message.type !== 'live.begin') return;
    const ticket: Ticket = message.ticket;
    if (state.paused || !ticket || !matchesPage(location.href, ticket.binding, ticket.rules, ticket.platformOrigin)) {
      reply({ ok: false });
      return;
    }
    if (state.id !== ticket.id) {
      state.stop();
      begin(state, ticket);
    }
    reply({ ok: !state.paused });
  });
}

function begin(state: Recorder, ticket: Ticket) {
  const abort = new AbortController();
  let stopRrweb: (() => void) | undefined,
    pending = 0;
  let tail = Promise.resolve();
  let baselineId: string | undefined,
    baselineNumber = 0;
  state.id = ticket.id;
  isolated.__mesLiveTicket = ticket.id;
  state.stop = () => {
    if (abort.signal.aborted) return;
    abort.abort();
    stopRrweb?.();
    state.id = undefined;
    state.updateRules = undefined;
    isolated.__mesLiveTicket = undefined;
  };
  let checkedUrl: string | undefined;
  state.updateRules = rules => {
    ticket.rules = rules;
    checkedUrl = undefined;
    return check();
  };
  async function stopAndNotify(type: 'live.gap' | 'live.pause') {
    if (abort.signal.aborted) return;
    state.stop();
    try {
      // Reload can invalidate this document's runtime before sendMessage returns a Promise.
      if (chrome.runtime?.id) await chrome.runtime.sendMessage({ type, ticket: ticket.id });
    } catch {
      // The recorder is already stopped; only its original runtime can accept this ticket.
    }
  }
  function check() {
    if (abort.signal.aborted) return false;
    const url = location.href;
    if (url === checkedUrl) return true;
    if (matchesPage(url, ticket.binding, ticket.rules, ticket.platformOrigin)) {
      checkedUrl = url;
      return true;
    }
    state.paused = true;
    void stopAndNotify('live.pause');
    return false;
  }
  function gap() {
    return stopAndNotify('live.gap');
  }
  function offer(event: PageEvidence) {
    if (!check()) return;
    if (event.kind === 'baseline') baselineId = ticket.id + ':' + ++baselineNumber;
    if (!baselineId) return;
    const reference = baselineId;
    const size = new TextEncoder().encode(JSON.stringify(event)).byteLength;
    if (pending + size > 8 * 1024 * 1024) {
      gap();
      return;
    }
    pending += size;
    tail = tail
      .then(async () => {
        if (!check()) return;
        const result = await chrome.runtime.sendMessage({
          type: 'live.event',
          ticket: ticket.id,
          baselineId: reference,
          event,
        });
        if (!result?.ok) gap();
      })
      .catch(gap)
      .finally(() => {
        pending -= size;
      });
  }
  isolated.navigation?.addEventListener('currententrychange', check, { signal: abort.signal });
  for (const name of ['hashchange', 'popstate'])
    window.addEventListener(name, check, { signal: abort.signal });
  window.addEventListener('pagehide', () => state.stop(), { once: true, signal: abort.signal });
  try {
    stopRrweb = record({
      emit(event) {
        if (!check()) return;
        try {
          if (event.type === 2)
            offer({ kind: 'baseline', node: structuralBaseline(event.data.node) });
          if (
            event.type === 3 &&
            event.data.source === 0 &&
            (event.data.adds.length || event.data.removes.length)
          )
            offer(structuralMutation(event.data));
        } catch {
          gap();
        }
      },
      recordAfter: 'DOMContentLoaded',
      checkoutEveryNms: 60_000,
      maskAllInputs: true,
      maskTextSelector: '*',
      maskTextFn: () => '',
      maskInputFn: () => '',
      blockSelector: 'iframe,script,style,link,[data-mes-agent-host]',
      recordCrossOriginIframes: false,
      inlineStylesheet: false,
      inlineImages: false,
      recordCanvas: false,
      collectFonts: false,
      sampling: { mousemove: false },
      errorHandler() {
        gap();
        return true;
      },
    });
    if (abort.signal.aborted) stopRrweb?.();
    for (const action of actions)
      document.addEventListener(
        action,
        (e) => {
          if (
            !e.isTrusted ||
            !check() ||
            !(e.target instanceof Element) ||
            e.target.closest('[data-mes-agent-host]')
          )
            return;
          offer({
            kind: 'action',
            action,
            element: safeElement(e.target.localName),
            node_id: record.mirror.getId(e.target),
          });
        },
        { capture: true, signal: abort.signal },
      );
  } catch {
    gap();
  }
}
