export type Json = string | number | null | boolean | Json[] | { [key: string]: Json };
export type Omission = {
  path: string;
  reason: 'protected' | 'truncated' | 'unstructured' | 'not_captured';
};

const names =
  /authorization|cookie|password|passwd|credential|secret|token|privatekey|apikey|modelkey|sessionid|sessionkey|csrf|xsrf|accesskey|signingkey|密码|令牌|^(pwd|session|sid|jwt|signature|ticket|rawbody|rawmessage|postdata|requestheaders|responseheaders|setcookie|headers)$/i;
export const protectedName = (s: string) => names.test(s.replace(/[\s._-]+/g, ''));
export const unsafeText = (s: string) =>
  /\b(?:Bearer|Basic)\s+\S+|-----BEGIN [^\n]*PRIVATE KEY-----|\beyJ[\w-]+\.eyJ[\w-]+\.[\w-]+|(?:^|[\r\n])\s*(?:Authorization|Set-Cookie|Cookie)\s*:|[a-z][a-z0-9+.-]{0,15}:\/\/[^ /:@]+:[^ /@]+@/i.test(
    s,
  );
const rawText = (s: string) => /^\s*(?:\{|\[|<!DOCTYPE|<html|<\?xml)/i.test(s);

export function detail(input: unknown, exactNumbers?: WeakSet<object>) {
  const omissions: Omission[] = [];
  function project(value: unknown, path: string, depth: number): Json {
    const omit = (reason: Omission['reason']) => {
      omissions.push({ path, reason });
      return null;
    };
    if (depth > 28) return omit('truncated');
    if (value && typeof value === 'object' && exactNumbers?.has(value)) return value as Json;
    if (typeof value === 'string') {
      if (unsafeText(value) || value === '[REDACTED]') return omit('protected');
      if (rawText(value)) return omit('unstructured');
      return value;
    }
    if (
      value === null ||
      typeof value === 'boolean' ||
      (typeof value === 'number' && Number.isFinite(value))
    )
      return value;
    if (Array.isArray(value)) return value.map((v, i) => project(v, path + '/' + i, depth + 1));
    if (typeof value !== 'object') return omit('unstructured');
    const entries = Object.entries(value);
    if (
      entries.some(
        ([k, v]) =>
          ['name', 'key', 'field', 'fieldName', 'header'].includes(k) &&
          typeof v === 'string' &&
          protectedName(v),
      )
    )
      return omit('protected');
    const out: Record<string, Json> = Object.create(null);
    for (const [k, v] of entries) {
      if (unsafeText(k) || rawText(k) || k.length > 128) {
        omissions.push({ path, reason: 'protected' });
        continue;
      }
      const ptr = path + '/' + k.replace(/~/g, '~0').replace(/\//g, '~1');
      if (protectedName(k)) {
        omissions.push({ path: ptr, reason: 'protected' });
        continue;
      }
      out[k] = project(v, ptr, depth + 1);
    }
    return out;
  }
  return { value: project(input, '', 0), omissions };
}
