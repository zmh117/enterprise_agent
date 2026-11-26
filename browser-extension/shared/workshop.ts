import { platformTraffic } from './platform-traffic';

export interface WorkshopScope {
  environment_id: string;
  environment_code: string;
  environment_name: string;
  base_id: string;
  base_code: string;
  base_name: string;
  workshop_id: string;
  workshop_code: string;
  workshop_name: string;
}
export interface PageRule {
  origin: string;
  path: string;
  hash_path: string;
  query: Record<string, string>;
}
export interface WorkshopBinding {
  id: string;
  revision: number;
  enabled: boolean;
  rule: PageRule;
  reserved_paths?: Pick<PageRule, 'path' | 'hash_path'>[];
  environment_id: string;
  base_id: string;
  workshop_id: string;
}
export interface WorkshopClient {
  destination: { origin: string; account: string; app: string; scopeRef: string };
  key: string;
  name: string;
  choices: WorkshopScope[];
  list(): Promise<WorkshopBinding[]>;
  save(rule: PageRule, scope: WorkshopScope, revision: number): Promise<WorkshopBinding>;
  revoke(binding: WorkshopBinding): Promise<void>;
}
export function ruleForPage(address: string, keys: string[] = []): PageRule {
  const url = new URL(address);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
    throw new Error('请选择 HTTP 或 HTTPS 业务页面');
  const hash = url.hash.startsWith('#/') ? url.hash.slice(1) : '';
  const split = hash.indexOf('?');
  const hashParams = new URLSearchParams(split < 0 ? '' : hash.slice(split + 1));
  const query: Record<string, string> = Object.create(null);
  if (keys.length > 8) throw new Error('最多选择 8 个业务定位键');
  for (const key of keys) {
    if (
      !/^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$/.test(key) ||
      /cookie|session|ticket|signature|csrf|jwt|password|passwd|privatekey|apikey|credential|secret|token|authorization|^sid$|^pwd$/i.test(
        key.replace(/[_.-]/g, ''),
      )
    )
      throw new Error('请选择非敏感的业务定位键');
    const values = [...url.searchParams.getAll(key), ...hashParams.getAll(key)];
    if (values.length !== 1 || !/^[\p{L}\p{N}_.-]{1,128}$/u.test(values[0]!))
      throw new Error('定位键需要唯一的业务编码值');
    query[key] = values[0]!;
  }
  return {
    origin: url.origin,
    path: url.pathname,
    hash_path: split < 0 ? hash : hash.slice(0, split),
    query,
  };
}
export function sameRule(a: PageRule, b: PageRule) {
  const keys = Object.keys(a.query);
  return (
    a.origin === b.origin &&
    a.path === b.path &&
    a.hash_path === b.hash_path &&
    keys.length === Object.keys(b.query).length &&
    keys.every((k) => b.query[k] === a.query[k])
  );
}
function routePath(path: string) {
  return path.replace(/\/+$/, '');
}
function covers(parent: string, path: string) {
  return path === parent || path.startsWith(parent + '/');
}
export function bindingForPage(url: string, bindings: WorkshopBinding[], platformOrigin?: string) {
  if (platformTraffic(url, platformOrigin)) return;
  let page: PageRule;
  try { page = ruleForPage(url); } catch { return; }
  const siteBindings = bindings.filter(b => b.rule.origin === page.origin);
  // Older APIs omit inaccessible routes entirely. Keep exact matching until they supply boundaries.
  const inherit = siteBindings.some(b => Array.isArray(b.reserved_paths));
  if (inherit && [page.path, page.hash_path].some(p => /%(?:2f|5c)|\\/i.test(p) ||
    p.split('/').some(segment => /^(?:\.|%2e){1,2}$/i.test(segment)))) return;
  const path = routePath(page.path), hash = routePath(page.hash_path);
  let bestPath = -1, bestHash = -1;
  let candidates: WorkshopBinding[] = [];
  function consider(route: Pick<PageRule, 'path' | 'hash_path'>, binding?: WorkshopBinding) {
    const prefix = routePath(route.path), fragment = routePath(route.hash_path);
    if (!inherit && (route.path !== page.path || route.hash_path !== page.hash_path)) return;
    if (!covers(prefix, path) || (route.hash_path && (!page.hash_path || !covers(fragment, hash)))) return;
    const hashLength = route.hash_path ? fragment.length : -1;
    if (prefix.length < bestPath || (prefix.length === bestPath && hashLength < bestHash)) return;
    if (prefix.length > bestPath || hashLength > bestHash) {
      bestPath = prefix.length;
      bestHash = hashLength;
      candidates = [];
    }
    if (binding?.enabled) candidates.push(binding);
  }
  for (const binding of siteBindings) {
    consider(binding.rule, binding);
    for (const reserved of binding.reserved_paths ?? []) consider(reserved);
  }
  // Once a more specific route is configured, missing/ambiguous workshop keys cannot fall back.
  const matches = candidates.filter(({rule}) => {
    const keys = Object.keys(rule.query);
    if (!keys.length) return true;
    try {
      const values = ruleForPage(url, keys).query;
      return keys.every(key => values[key] === rule.query[key]);
    } catch { return false; }
  });
  return matches.length === 1 ? matches[0] : undefined;
}
export function sameWorkshop(a: WorkshopBinding, b: WorkshopBinding) {
  return a.rule.origin === b.rule.origin && a.environment_id === b.environment_id &&
    a.base_id === b.base_id && a.workshop_id === b.workshop_id;
}
export function describeRule(r: PageRule) {
  const query = new URLSearchParams(r.query).toString();
  return r.origin + r.path + (r.hash_path ? '#' + r.hash_path : '') + (query ? '?' + query : '');
}
export function workshopLabel(scope: WorkshopScope) {
  return [scope.environment_name, scope.base_name, scope.workshop_name].join(' › ');
}
