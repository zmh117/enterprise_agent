import type { PageTicket } from '../../shared/contracts';
import { cleanText, cleanUrl, cleanValue, MASK } from '../../shared/redaction';
import { pagePrivacy } from '../../shared/page-privacy';

/** Each state is an observation, never a reconstructed pre-action state. */
export function startSemantic(ticket: PageTicket, emit: (kind: 'ui.observation' | 'capture.page_diagnostic', payload: Record<string, any>) => number, nodeId: (el: Element) => number) {
  const policy = ticket.policy;
  let stopped = false;
  const cleanup: (() => void)[] = [];
  const last = new WeakMap<Element, { packetSeq: number; sourceTime: number }>();
  let omissions: { scope: string; count: number; exact: boolean; reason: string }[] = [];
  const omit = (scope: string, count: number, exact = true) => { if (count > 0) omissions.push({ scope, count, exact, reason: 'semantic_read_budget' }); };
  const privacy = pagePrivacy(policy, document, omit);
  const alerts = 'dialog,[role="dialog"],[role="alert"],[aria-live]';
  const controls = `input,select,textarea,button,${alerts}`;
  const visible = (el: Element) => el.isConnected && !el.closest('[hidden],[aria-hidden="true"]') && getComputedStyle(el).visibility !== 'hidden' && el.getClientRects().length > 0;
  function stateOf(el: Element) {
    const field = el as HTMLInputElement;
    const masked = privacy.sensitive(el) || (!policy.allowedInputNames.includes('*') && !policy.allowedInputNames.includes(field.name ?? ''));
    const value = (v: string) => { if (masked) return MASK; if (v.length > 2000) omit('value_characters', v.length - 2000); return cleanText(v.slice(0, 2000)); };
    const selected = el instanceof HTMLSelectElement ? [...el.selectedOptions].slice(0, 30) : [];
    if (el instanceof HTMLSelectElement) omit('selected_options', el.selectedOptions.length - selected.length);
    return { value: 'value' in field ? { status: masked ? 'masked' : 'known', value: value(String(field.value)) } : { status: 'not_applicable' },
      checked: 'checked' in field ? { status: masked ? 'masked' : 'known', value: masked ? MASK : field.checked } : { status: 'not_applicable' },
      selectedOptions: el instanceof HTMLSelectElement ? masked ? MASK : selected.map(o => value(o.value)) : null,
      selectedIndex: el instanceof HTMLSelectElement && !masked ? el.selectedIndex : null,
      disabled: !!field.disabled, readonly: !!field.readOnly, visible: visible(el), open: el instanceof HTMLDialogElement ? el.open : null,
      validationMessage: field.validationMessage ? privacy.text(field.validationMessage, el) : '', loading: privacy.attribute(el, 'aria-busy'), text: privacy.content(el) };
  }
  function targetOf(el: Element) {
    const id = nodeId(el); const attrs = [...el.attributes].filter(a => a.name.startsWith('data-'));
    omit('target_attributes', attrs.length - 20);
    const label = el.getAttribute('aria-label') ?? (el as HTMLInputElement).labels?.[0]?.textContent ?? el.getAttribute('title') ?? '';
    return { role: privacy.attribute(el, 'role') ?? el.tagName.toLowerCase(), label: privacy.text(label, el), name: privacy.attribute(el, 'name'), id: privacy.attribute(el, 'id'), text: privacy.content(el),
      data: Object.fromEntries(attrs.slice(0, 20).map(a => [a.name, privacy.attribute(el, a.name)])),
      elementRef: id >= 0 ? { recorderStreamId: ticket.recorderStreamId, nodeId: id } : null, elementRefStatus: id >= 0 ? 'mapped' : 'unavailable_child_remapping' };
  }
  function regionOf(el: Element) {
    const region = el.closest('form,dialog,[role="dialog"],[data-evidence-region]') ?? el;
    const fields = region.querySelectorAll<HTMLInputElement>('input[name],select[name],textarea[name]');
    const notices = region.querySelectorAll(alerts);
    omit('region_fields', fields.length - 30); omit('region_notices', notices.length - 10);
    // Total context text is bounded independently from each field's budget.
    let remaining = 8000;
    const limited = (value: string) => { const kept = value.slice(0, remaining); remaining -= kept.length; omit('region_characters', value.length - kept.length); return kept; };
    return { scope: region === el ? 'target_only' : 'closest_form_or_dialog', form: privacy.attribute(region, 'name') ?? privacy.attribute(region, 'aria-label'),
      business: Object.fromEntries([...fields].slice(0, 30).filter(n => (policy.allowedInputNames.includes('*') || policy.allowedInputNames.includes(n.name)) && !privacy.sensitive(n)).map(n => [n.name, limited(privacy.text(n.value, n))])),
      notices: [...notices].slice(0, 10).map(n => ({ text: limited(privacy.content(n)), visible: visible(n) })) };
  }
  function observe(action: string, el: Element, phase = 'observed', scopeOmissions: typeof omissions = []) {
    if (stopped || el.closest('[data-mes-agent-host]')) return;
    omissions = [...scopeOmissions];
    const sourceTime = performance.now(); const previous = last.get(el); const after = stateOf(el);
    if (action === 'mutation') action = el.matches('dialog,[role="dialog"]') ? (after.visible && (after.open === null || after.open) ? 'dialog_open' : 'dialog_close') : el.matches('[role="alert"],[aria-live]') ? 'notice_change' : 'state_change';
    const target = targetOf(el); const region = regionOf(el);
    const payload = cleanValue({ action, phase, target, observation: { sourceTime, sourceClock: 'document_performance_ms' },
      before: previous ? { status: 'observed', packetSeq: previous.packetSeq, sourceTime: previous.sourceTime } : { status: 'unavailable', reason: 'no_previous_observation' }, after,
      context: { ...region, module: privacy.attribute(document.body, 'data-module') ?? 'unknown', url: cleanUrl(location.href, policy.allowedQueryKeys), visibility: document.visibilityState, focused: document.hasFocus() },
      omissions });
    const packetSeq = emit('ui.observation', payload); last.set(el, { packetSeq, sourceTime });
  }
  const listen = (obj: EventTarget, name: string, fn: EventListener, options?: AddEventListenerOptions) => { obj.addEventListener(name, fn, options); cleanup.push(() => obj.removeEventListener(name, fn, options)); };
  for (const name of ['click', 'input', 'change', 'submit', 'invalid']) listen(document, name, e => {
    const el = e.target instanceof Element ? e.target.closest('button,a,input,select,textarea,form,[role="button"],[role="checkbox"]') : null;
    if (!el) return;
    observe(name === 'change' && el.tagName === 'SELECT' ? 'select' : name, el, 'event_capture');
    queueMicrotask(() => observe(`${name}_after`, el, 'microtask_observation'));
  }, { capture: true });
  function snapshot(reason: string) {
    if (reason === 'initial_state') for (const rule of policy.correlationSources.filter(r => r.source === 'page_meta' && (!r.origin || r.origin === location.origin) && (!r.pathPrefix || location.pathname.startsWith(r.pathPrefix)))) {
      const el = document.querySelector(rule.key); const value = privacy.attribute(el, 'content');
      if (value && value !== MASK && value.length <= 256) emit('ui.observation', { action: 'build_metadata', after: { metadataFacts: [{ field: rule.field, component: rule.component, value, source: `page_meta:${rule.key}`, observedAt: new Date().toISOString() }] }, before: { status: 'unavailable' }, target: null, context: { url: cleanUrl(location.href, policy.allowedQueryKeys) } });
    }
    const els = document.querySelectorAll(controls); const excess = els.length > 150 ? [{ scope: 'snapshot_fields', count: els.length - 150, exact: true, reason: 'semantic_read_budget' }] : [];
    for (const el of [...els].slice(0, 150)) observe(reason, el, 'snapshot_observation', excess);
  }
  const observer = new MutationObserver(records => {
    const changed = new Set<Element>(); let omitted = 0;
    const add = (el: Element) => { if (changed.has(el)) return; if (changed.size < 150) changed.add(el); else omitted++; };
    for (const m of records) {
      const el = m.target instanceof Element ? m.target : m.target.parentElement;
      const relevant = el?.closest(`${controls},[data-evidence]`); if (relevant) add(relevant);
      // Ancestor class/style/hidden changes can hide a nested role dialog.
      if (el && m.type === 'attributes') for (const n of el.querySelectorAll(alerts)) add(n);
      for (const n of [...m.addedNodes, ...m.removedNodes]) if (n instanceof Element) { if (n.matches(alerts)) add(n); for (const x of n.querySelectorAll(alerts)) add(x); }
    }
    for (const el of changed) observe('mutation', el, 'mutation_observation', omitted ? [{ scope: 'mutation_elements', count: omitted, exact: false, reason: 'semantic_read_budget' }] : []);
  });
  observer.observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['disabled', 'readonly', 'aria-busy', 'aria-hidden', 'open', 'class', 'style', 'hidden', 'value', 'checked', 'selected', 'required'] });
  cleanup.push(() => observer.disconnect());
  for (const [proto, keys] of [[HTMLInputElement.prototype, ['value', 'checked']], [HTMLTextAreaElement.prototype, ['value']], [HTMLSelectElement.prototype, ['value', 'selectedIndex']], [HTMLOptionElement.prototype, ['selected']]] as const) for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(proto, key); if (!d?.set || !d.configurable) continue;
    const setter = function(this: Element, value: unknown) {
      const el = this instanceof HTMLOptionElement ? this.closest('select') ?? this : this;
      if (!stopped) observe('programmatic_before', el, 'before_setter_observation');
      d.set!.call(this, value);
      if (!stopped) observe('programmatic_change', el, 'setter_observation');
    };
    Object.defineProperty(proto, key, { ...d, set: setter });
    cleanup.push(() => { if (Object.getOwnPropertyDescriptor(proto, key)?.set === setter) Object.defineProperty(proto, key, d); });
  }
  listen(window, 'hashchange', () => snapshot('route_change')); listen(window, 'popstate', () => snapshot('route_change'));
  listen(document, 'visibilitychange', () => observe('visibility_change', document.documentElement));
  emit('capture.page_diagnostic', { code: 'semantic_started', mode: ticket.mode });
  return { snapshot, stop() { if (stopped) return; stopped = true; for (const fn of cleanup.reverse()) fn(); } };
}
