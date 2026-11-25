const known = new Set<string>();
export function rememberPlatform(origin: string) {
  const parsed = new URL(origin);
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    parsed.origin !== origin
  )
    throw new Error('平台来源无效');
  known.add(origin);
}
export function platformTraffic(raw: string, selected?: string): boolean {
  try {
    const u = new URL(raw);
    if (u.hostname === 'cnofpalbgpkfflagpkbdifgfjmfijfpi.chromiumapp.org')
      return true;
    if (u.origin !== selected && !known.has(u.origin)) return false;
    return /^\/(?:api\/(?:browser-extension|auth)(?:\/|$)|login(?:\/|$))/.test(
      u.pathname,
    );
  } catch {
    return false;
  }
}
