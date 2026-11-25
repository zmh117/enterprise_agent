import type { Recording } from './contracts';

export type EnvironmentOption = { code: string; name: string };
export type EnvironmentCatalog = { scope: string; options: EnvironmentOption[] };
export type SiteEnvironments = Record<string, string>;

export function commonEnvironment(sites: SiteEnvironments): string {
  const values = new Set(Object.values(sites));
  return values.size === 1 ? [...values][0]! : '';
}

export function recordingLabel(recording: Recording): string {
  const time = new Date(recording.startedAt).toLocaleString('zh-CN', { hour12: false });
  const sites = Object.values(recording.rootEnvironments ?? {});
  const environment = recording.environmentId || (sites.some(Boolean) ? '多个或部分关联环境' : '未关联环境');
  return [time, environment, recording.recordingId.slice(-8)].join(' · ');
}
