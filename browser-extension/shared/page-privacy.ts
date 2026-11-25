import type { Policy } from './contracts';
import { cleanText, MASK, sensitiveKey } from './redaction';

export function sensitiveSelector(policy: Policy): string {
  return ['input[type="password"]', '[autocomplete="current-password"]', '[autocomplete="new-password"]', 'script', 'noscript', ...policy.sensitiveSelectors].join(',');
}

/** Use the browser's parser, not a partial CSS grammar. Empty entries must not disable masking. */
export function validateSensitiveSelectors(policy: Policy, doc: Document): void {
  policy.sensitiveSelectors.forEach((selector, index) => {
    try { if (!selector.trim()) throw new Error('empty'); doc.querySelector(selector); }
    catch { throw new Error(`敏感选择器第 ${index + 1} 项无效`); }
  });
  doc.querySelector(sensitiveSelector(policy));
}

export function pagePrivacy(policy: Policy, doc: Document, omitted?: (scope: string, count: number, exact: boolean) => void) {
  validateSensitiveSelectors(policy, doc);
  const selector = sensitiveSelector(policy);
  const marked = new WeakSet<Element>();
  const sensitive = (el: Element | null): boolean => {
    if (!el) return false;
    if (marked.has(el) || el.closest(selector) || sensitiveKey(el.getAttribute('name') ?? '') || sensitiveKey(el.id)) {
      marked.add(el); return true;
    }
    return false;
  };
  const text = (value: string, el?: Element | null) => {
    if (policy.maskAllText || sensitive(el ?? null)) return MASK;
    if (value.length > 2000) omitted?.('text_characters', value.length - 2000, true);
    return cleanText(value.slice(0, 2000));
  };
  // A non-sensitive form/button can contain a sensitive descendant. Never flatten it first.
  const content = (el: Element): string => {
    if (policy.maskAllText || sensitive(el)) return MASK;
    let result = ''; let visited = 0; let exhausted = false;
    const walk = (node: Node) => {
      if (++visited > 512 || result.length >= 2000) { exhausted = true; return; }
      if (node.nodeType === 1 && sensitive(node as Element)) { result += MASK; return; }
      if (node.nodeType === 3) { const value = node.textContent ?? ''; if (value.length > 2000 - result.length) exhausted = true; result += value.slice(0, 2000 - result.length); }
      else for (const child of node.childNodes) { walk(child); if (exhausted) break; }
    };
    walk(el); if (exhausted) omitted?.('text_or_dom_nodes', 1, false);
    return cleanText(result.trim()).slice(0, 2000);
  };

  const attribute = (el: Element | null, name: string): string | null => {
    const value = el?.getAttribute(name);
    return value == null ? null : sensitiveKey(name) ? MASK : text(value, el);
  };
  return { selector, sensitive, text, content, attribute };
}
