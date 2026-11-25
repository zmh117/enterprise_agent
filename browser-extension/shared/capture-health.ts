import type { Target } from './contracts';

export const REQUIRED_CHANNELS = ['page', 'semantic', 'network', 'runtime'] as const;
export function captureHealth(t: Target): Target['captureState'] {
  if (!t.accepting || t.lifecycle !== 'OPEN') return 'STOPPED';
  const states = REQUIRED_CHANNELS.map(c => t.channels[c].state);
  if (states.every(s => s === 'ACTIVE')) return 'ACTIVE';
  if (states.some(s => s === 'ACTIVE')) return 'DEGRADED';
  return states.some(s => s === 'PENDING') ? 'ATTACHING' : 'BLOCKED';
}
