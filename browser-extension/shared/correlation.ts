import { now, type CorrelationFact, type Policy, type Recording } from './contracts';
import { cleanText, MASK } from './redaction';

export function extractFacts(policy: Policy, url: string, source: 'response_header' | 'response_json', value: any): CorrelationFact[] {
  const u = new URL(url); const facts: CorrelationFact[] = [];
  for (const rule of policy.correlationSources) {
    if (rule.source !== source || (rule.origin && rule.origin !== u.origin) || (rule.pathPrefix && !u.pathname.startsWith(rule.pathPrefix))) continue;
    const raw = source === 'response_header' ? value[rule.key.toLowerCase()] : rule.key.slice(1).split('/').map(k => k.replace(/~1/g, '/').replace(/~0/g, '~')).reduce((v, k) => v && typeof v === 'object' && Object.hasOwn(v, k) ? v[k] : undefined, value);
    if (!['string', 'number'].includes(typeof raw)) continue;
    const text = cleanText(String(raw));
    if (!text || text.length > 256 || text.includes(MASK)) continue;
    facts.push({ field: rule.field, value: text, source: `${source}:${rule.key}`, component: rule.component, observedAt: now() });
  }
  return facts;
}
export function projectVersions(recording: Recording, facts: CorrelationFact[], reference: string) {
  for (const fact of facts) {
    if (!['frontendBuildId', 'backendBuildId', 'serviceInstance'].includes(fact.field)) continue;
    const field = fact.field as 'frontendBuildId' | 'backendBuildId' | 'serviceInstance'; const previous = recording.versions[field];
    recording.versions[field] = previous === 'unknown' || previous === fact.value ? fact.value : 'mixed_deployment';
    recording.versions.sources[field] ??= `${reference};${fact.source};all_sources=network/index-*.ndjson or events/*.ndjson`;
  }
}
export function sourceMatch(recording: Recording, fact: CorrelationFact, peerFacts: CorrelationFact[]) {
  const mixed = peerFacts.some(f => f.component === fact.component && f.field === fact.field && f.value !== fact.value);
  const snapshots = [...new Set(recording.policy.sourceMappings.filter(m => m.environmentId === recording.environmentId && m.component === fact.component && m.buildId === fact.value).map(m => m.codeSnapshot))];
  return { status: mixed || snapshots.length !== 1 ? 'unresolved' : 'configured_unverified', reason: mixed ? 'mixed_or_conflicting_observations' : snapshots.length > 1 ? 'conflicting_manual_mappings' : snapshots.length ? 'explicit_policy_mapping;source_not_inspected' : 'mapping_missing', snapshots, mappingSource: 'frozen_policy.sourceMappings' };
}
