import { platformTraffic } from './platform-traffic';
import type { BodyFields, Policy } from './contracts';
import { bytes } from './contracts';
export const MASK = '[REDACTED]';
// Policy v3: only password fields are protected; tokens, cookies and business text remain intact.
export const sensitiveKey = (key: string) => /(?:password|passwd|pwd|密码)|^(?:(?:login|current|old|new|user)[_-]?)?pass$/i.test(key);
export function cleanText(input: string): string {
  return input
    .replace(/((?:password|passwd|pwd|密码|(?<![\w-])(?:(?:login|current|old|new|user)[_-]?)?pass)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;&<>]+)/gi, `$1${MASK}`)
    .replace(/https?:\/\/[^\s"<>]+/g, url => cleanUrl(url));
}
export function cleanUrl(input: string, allowed: string[] = ['*']): string {
  try {
    const u = new URL(input, 'https://relative.invalid');
    if(platformTraffic(input)) return u.origin + '/api/browser-extension';
    if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return `${u.protocol}[excluded]`;
    let changed = false;
    if (u.password) { u.password = MASK; changed = true; }
    for (const key of [...u.searchParams.keys()]) if (sensitiveKey(key) || (!allowed.includes('*') && !allowed.includes(key))) { u.searchParams.set(key, MASK); changed = true; }
    if (u.hash) {
      const hash = u.hash.slice(1), split = hash.indexOf('?');
      const params = new URLSearchParams(split < 0 ? hash : hash.slice(split + 1)); let masked = false;
      for (const key of [...params.keys()]) if (sensitiveKey(key)) { params.set(key, MASK); masked = true; }
      if (masked) { u.hash = (split < 0 ? '' : hash.slice(0, split + 1)) + params.toString(); changed = true; }
    }
    if (!changed) return input;
    return u.origin === 'https://relative.invalid' ? `${u.pathname}${u.search}${u.hash}` : u.href;
  } catch { return '[invalid URL]'; }
}
export function cleanHeaders(headers: Record<string, unknown> = {}): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) {
    if (sensitiveKey(k)) { result[k.toLowerCase()] = MASK; continue; }
    if (/^(?:proxy-)?authorization$/i.test(k) && /^Basic\s+/i.test(String(v))) {
      try { const decoded = atob(String(v).replace(/^Basic\s+/i, '')); const split = decoded.indexOf(':'); result[k.toLowerCase()] = split < 0 ? MASK : `Basic ${btoa(decoded.slice(0, split + 1) + MASK)}`; }
      catch { result[k.toLowerCase()] = MASK; }
      continue;
    }
    result[k.toLowerCase()] = cleanText([':path', 'location'].includes(k.toLowerCase()) ? cleanUrl(String(v)) : String(v)).slice(0, 8192);
  }
  return result;
}
export function cleanValue(value: unknown, depth = 0): any {
  if (depth > 40) return '[excluded: nesting limit]';
  if (typeof value === 'string') return cleanText(value);
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(v => cleanValue(v, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
    out[k] = sensitiveKey(k) ? MASK : cleanValue(v, depth + 1);
  }
  return out;
}
export function emptyBody(status: BodyFields['bodyCaptureStatus'] = 'unavailable', reason: string | null = 'not_received'): BodyFields {
  return { bodyCaptureStatus: status, bodyRef: null, bodyCaptureReason: reason, redactionStatus: 'none' };
}
export function sanitizeBody(raw: string, mime: string, policy: Policy): { fields: BodyFields; content?: string; mime?: string; parsed?: unknown } {
  const size = bytes(raw);
  if (!size) return { fields: { ...emptyBody('empty', null), originalBytes: 0, savedBytes: 0 } };
  const excluded = (reason: string) => ({ fields: { ...emptyBody('excluded_by_policy', reason), redactionStatus: 'failed_excluded' as const, originalBytes: size, savedBytes: 0 } });
  if (size > policy.budgets.bodyBytes) return excluded('body_size_limit_no_partial_json');
  let content: string; let parsed: unknown;
  if (/json/i.test(mime)) {
    // A narrowly recognized XSSI guard is transport syntax, never executable code.
    const json = raw.replace(/^\)\]\}'\r?\n/, '');
    try { const value = JSON.parse(json); parsed = cleanValue(value); content = JSON.stringify(value) === JSON.stringify(parsed) ? json : JSON.stringify(parsed); } catch { return excluded('invalid_json_cannot_redact'); }
  } else if (/x-www-form-urlencoded/i.test(mime)) {
    const params = new URLSearchParams(raw);
    const cleaned = new URLSearchParams(); let changed = false;
    for (const [k, v] of params) { const value = sensitiveKey(k) ? MASK : cleanText(v); cleaned.append(k, value); changed ||= value !== v; }
    content = changed ? cleaned.toString() : raw;
  } else if (/^text\/plain\b/i.test(mime)) {
    // text/plain JSON uses structured password protection; other text retains its values.
    try {
      const value: unknown = JSON.parse(raw);
      parsed = cleanValue(value); content = JSON.stringify(value) === JSON.stringify(parsed) ? raw : JSON.stringify(parsed); mime = 'application/json';
    } catch { content = cleanText(raw); }
  } else return excluded('unsupported_or_binary_mime');
  if (bytes(content) > policy.budgets.bodyBytes) return excluded('sanitized_body_size_limit');
  return { fields: { ...emptyBody('captured', null), redactionStatus: content === raw ? 'none' : 'applied', originalBytes: size, savedBytes: bytes(content) }, content, parsed, mime };
}
/** Keep rrweb structural IDs/types intact; redact data, never remove a dependency mutation. */
export function cleanRrweb(event: any, policy: Policy): any {
  function visit(v: any, key = '', depth = 0): any {
    if (depth > 200) throw new Error('rrweb nesting limit');
    if (typeof v === 'string') {
      if (['href', 'src', 'url', 'action', 'poster', 'background', 'xlink:href'].includes(key)) return cleanUrl(v, policy.allowedQueryKeys);
      return sensitiveKey(key) ? MASK : cleanText(v);
    }
    if (!v || typeof v !== 'object') return v;
    if (Array.isArray(v)) return v.map(x => visit(x, key, depth + 1));
    const out: Record<string, any> = {};
    for (const [k, x] of Object.entries(v)) {
      if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
      out[k] = sensitiveKey(k) ? MASK : visit(x, k, depth + 1);
    }
    if (out.attributes) {
      const a = out.attributes;
      if (a.type === 'password' || sensitiveKey(String(a.name ?? '')) || sensitiveKey(String(a.id ?? ''))) {
        a.value = MASK;
        for (const field of ['content', 'title', 'placeholder', 'data-value']) if (field in a) a[field] = MASK;
      }
      else if ('value' in a && !policy.allowedInputNames.includes('*') && !policy.allowedInputNames.includes(String(a.name ?? ''))) a.value = MASK;
    }
    return out;
  }
  return visit(event);
}
