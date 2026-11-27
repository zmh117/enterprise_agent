import { bindingForPage, type WorkshopBinding, type WorkshopClient } from '../shared/workshop';

export type SiteRule = WorkshopBinding & {app: string};
export interface SiteCatalog {
  origin: string;
  account: string;
  rules: SiteRule[];
}
export const siteCatalogKey = (origin: string, account: string) => JSON.stringify(['site-rules', origin, account]);

// The platform owns the rules. The local snapshot lets the worker match a tab before opening the UI.
export async function fetchSiteCatalog(origin: string, account: string, clients: WorkshopClient[], signal: AbortSignal) {
  const key = siteCatalogKey(origin,account);
  return navigator.locks.request(key, {signal}, async () => {
    const lists = await Promise.all(clients.map(async client => ({
      client, rows: await client.list(),
    })));
    signal.throwIfAborted();
    const catalog: SiteCatalog = {origin, account, rules: lists.flatMap(({client, rows}) =>
      rows.map(rule => ({...rule, app: client.destination.app})))};
    const cache: Record<string, unknown> = {[key]: catalog};
    for (const {client, rows} of lists) cache[client.key] = rows;
    await chrome.storage.local.set(cache);
    signal.throwIfAborted();
    return catalog;
  });
}

export async function localPageContext(url: string) {
  const {agentOrigin, agentActiveAccount} = await chrome.storage.local.get(['agentOrigin', 'agentActiveAccount']);
  if (typeof agentOrigin !== 'string' || typeof agentActiveAccount !== 'string') return;
  const key = siteCatalogKey(agentOrigin, agentActiveAccount);
  const catalog = (await chrome.storage.local.get(key))[key] as SiteCatalog | undefined;
  const binding = catalog && bindingForPage(url, catalog.rules, catalog.origin);
  if (binding) return {binding, destination:{origin:agentOrigin, account:agentActiveAccount, app:binding.app}};
}

export async function localPageRule(url: string) {
  return (await localPageContext(url))?.binding;
}
