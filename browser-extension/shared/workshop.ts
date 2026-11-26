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
export function bindingForPage(url: string, bindings: WorkshopBinding[]) {
  const found = bindings.filter((b) => {
    if (!b.enabled) return false;
    try {
      return sameRule(b.rule, ruleForPage(url, Object.keys(b.rule.query)));
    } catch {
      return false;
    }
  });
  return found.length === 1 ? found[0] : undefined;
}
export function describeRule(r: PageRule) {
  const query = new URLSearchParams(r.query).toString();
  return r.origin + r.path + (r.hash_path ? '#' + r.hash_path : '') + (query ? '?' + query : '');
}
export function workshopLabel(scope: WorkshopScope) {
  return [scope.environment_name, scope.base_name, scope.workshop_name].join(' › ');
}
