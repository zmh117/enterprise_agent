import { platformTraffic } from './platform-traffic';
import type { Policy } from './contracts';
const MiB = 1024 * 1024;
export const DEFAULT_POLICY: Policy = {
  policyVersion: '3.0.0', pageOrigins: [], apiRules: [],
  requestTypes: ['XHR', 'Fetch', 'Document', 'WebSocket', 'EventSource'],
  allowedInputNames: ['*'],
  allowedQueryKeys: ['*'],
  sensitiveSelectors: [],
  maskAllText: false, screenshots: 'disabled', captureStreaming: false, businessRules: [],
  correlationSources: [
    { field: 'frontendBuildId', source: 'response_header', key: 'x-frontend-build', component: 'frontend' },
    { field: 'backendBuildId', source: 'response_header', key: 'x-backend-build', component: 'backend' },
    { field: 'serviceInstance', source: 'response_header', key: 'x-service-instance', component: 'backend' },
    { field: 'requestId', source: 'response_header', key: 'x-request-id', component: 'backend' },
  ], sourceMappings: [],
  budgets: { softTabs: 10, hardTabs: 30, reminderMinutes: 30, ipcBytes: 128 * 1024, baselineBytes: 8 * MiB, bodyBytes: MiB, softBytes: 100 * MiB, hardBytes: 200 * MiB, queueBytes: 16 * MiB, bodyConcurrency: 2 },
  logTimeMarginSeconds: 120,
};
export function originOf(url: string): string | null {
  try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.origin : null; } catch { return null; }
}
// Only selects which existing captures to invalidate; never grants access.
// Chrome host patterns ignore paths and match all ports unless one is specified.
export function revokedHostMatches(pattern: string, url: string): boolean {
  const origin = originOf(url); if (!origin) return false;
  if (pattern === '<all_urls>') return true;
  const m = /^(https?|\*):\/\/(\[[^\]]+\]|[^/:]+)(?::(\*|\d+))?\//.exec(pattern);
  if (!m) return !pattern.startsWith('file:'); // Unknown removal fails closed.
  const u = new URL(origin), host = m[2]!.toLowerCase();
  if (m[1] !== '*' && u.protocol !== m[1] + ':') return false;
  if (m[3] && m[3] !== '*' && (u.port || (u.protocol === 'https:' ? '443' : '80')) !== m[3]) return false;
  return host === '*' || u.hostname === host || (host.startsWith('*.') && (u.hostname === host.slice(2) || u.hostname.endsWith(host.slice(1))));
}
export function supportedUrl(url: string): boolean {
  const origin = originOf(url);
  return !!origin && !['https://chromewebstore.google.com', 'https://chrome.google.com'].includes(origin);
}
export function pageAllowed(policy: Policy, url: string) { const o = originOf(url); return !!o && !platformTraffic(url) && policy.pageOrigins.includes(o) && supportedUrl(url); }
export function apiAllowed(policy: Pick<Policy,'apiRules'|'requestTypes'>, url: string, type: string) {
  try {
    const u = new URL(url.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:'));
    return !platformTraffic(url) && policy.requestTypes.includes(type) && policy.apiRules.some(r => u.origin === r.origin && u.pathname.startsWith(r.pathPrefix));
  } catch { return false; }
}
export function parsePolicy(input: unknown, mode: 'offline'|'continuous' = 'offline'): Policy {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('采集策略必须为对象');
  const p = structuredClone(input) as Policy;
  const strings = (v: unknown, n: number): v is string[] => Array.isArray(v) && v.length <= n && v.every(x => typeof x === 'string' && x.length <= 500);
  if (!strings(p.pageOrigins, 100) || !p.pageOrigins.length || p.pageOrigins.some(x => originOf(x) !== x)) throw new Error('页面规则须为明确的 http/https origin（不带路径）');
  for (const key of ['allowedInputNames', 'allowedQueryKeys', 'sensitiveSelectors', 'requestTypes'] as const) if (!strings(p[key], 100)) throw new Error(`无效策略: ${key}`);
  if (!Array.isArray(p.apiRules) || p.apiRules.length > 100 || !p.apiRules.every(r => r && originOf(r.origin) === r.origin && typeof r.pathPrefix === 'string' && r.pathPrefix.startsWith('/') && r.pathPrefix.length < 500)) throw new Error('无效 API 允许规则');
  if (!Array.isArray(p.businessRules) || p.businessRules.length > 100 || !p.businessRules.every(r => originOf(r.origin) === r.origin && typeof r.pathPrefix === 'string' && r.pathPrefix.startsWith('/') && /^[\w.]+$/.test(r.codePath) && Array.isArray(r.successValues) && r.successValues.length <= 100 && r.successValues.every(x => typeof x === 'number' || typeof x === 'string'))) throw new Error('无效业务成功码规则');
  if (typeof p.captureStreaming !== 'boolean' || typeof p.maskAllText !== 'boolean' || p.screenshots !== 'disabled') throw new Error('当前版本截图固定停用：无法保证动态页面像素脱敏');
  if (!Array.isArray(p.correlationSources) || p.correlationSources.length > 32 || !p.correlationSources.every(r => r && ['frontendBuildId','backendBuildId','serviceInstance','requestId','traceId','spanId'].includes(r.field) && ['response_header','response_json','page_meta'].includes(r.source) && typeof r.key === 'string' && r.key.length <= 200 && (r.source === 'response_header' ? /^[a-zA-Z0-9-]{1,80}$/.test(r.key) : r.source === 'response_json' ? /^(\/([^~]|~[01])*)+$/.test(r.key) : /^meta\[name=(?:"[a-zA-Z0-9_.-]+"|'[a-zA-Z0-9_.-]+')\]$/.test(r.key)) && typeof r.component === 'string' && r.component.length > 0 && r.component.length <= 80 && (r.origin === undefined || (typeof r.origin === 'string' && originOf(r.origin) === r.origin)) && (r.pathPrefix === undefined || (typeof r.pathPrefix === 'string' && r.pathPrefix.startsWith('/') && r.pathPrefix.length < 500)))) throw new Error('无效版本/日志来源配置');
  if (!Array.isArray(p.sourceMappings) || p.sourceMappings.length > 100 || !p.sourceMappings.every(m => m && ['environmentId','component','buildId','codeSnapshot'].every(k => typeof (m as any)[k] === 'string' && (m as any)[k].length > 0 && (m as any)[k].length <= 500))) throw new Error('无效显式源码映射');

  const bounds: Record<keyof Policy['budgets'], [number, number]> = { softTabs: [1, 100], hardTabs: [1, 100], reminderMinutes: [1, 240], ipcBytes: [4096, 128 * 1024], baselineBytes: [1024, 16 * MiB], bodyBytes: [1024, (mode === 'continuous' ? 32 : 4) * MiB], softBytes: [MiB, 400 * MiB], hardBytes: [MiB, 500 * MiB], queueBytes: [MiB, (mode === 'continuous' ? 128 : 32) * MiB], bodyConcurrency: [1, 4] };
  if (!p.budgets) throw new Error('缺少容量预算');
  for (const [k, [min, max]] of Object.entries(bounds)) { const v = p.budgets[k as keyof Policy['budgets']]; if (!Number.isInteger(v) || v < min || v > max) throw new Error(`预算 ${k} 应在 ${min}–${max} 内`); }
  if (mode === 'continuous' && p.budgets.queueBytes < p.budgets.bodyBytes) throw new Error('持续采集队列至少要能容纳一份正文');
  if (p.budgets.softBytes > p.budgets.hardBytes || p.budgets.softTabs > p.budgets.hardTabs) throw new Error('软阈值不能高于硬限制');
  if (!Number.isFinite(p.logTimeMarginSeconds) || p.logTimeMarginSeconds < 0 || p.logTimeMarginSeconds > 3600) throw new Error('日志时间余量应在 0–3600 秒内');
  p.policyVersion = '3.0.0';
  p.pageOrigins = [...new Set(p.pageOrigins)];
  return p;
}
