import { originOf, supportedUrl } from '../../shared/policy';
import { platformTraffic } from '../../shared/platform-traffic';

export const sitesKey = 'agentFloatSites';
export const bindingsKey = (scope: string) => 'agentSiteEnvironments:' + scope;
type BindingUpdate = { scope: string; values: Record<string, string> };
export function storedBindings(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object') return {};
  return Object.fromEntries(Object.entries(value).filter(([, code]) => typeof code === 'string'));
}
export function hostPattern(origin: string) {
  const url = new URL(origin);
  return url.protocol + '//' + url.hostname + '/*';
}

export async function sites(): Promise<string[]> {
  const value = (await chrome.storage.local.get(sitesKey))[sitesKey];
  return Array.isArray(value) ? value.filter((s): s is string => typeof s === 'string') : [];
}
async function permitted(url: string) {
  const origin = originOf(url);
  return !!origin && supportedUrl(url) && !platformTraffic(url) &&
    (await sites()).includes(origin) &&
    await chrome.permissions.contains({origins: [hostPattern(origin)]});
}
async function attach(tabId: number, url: string, documentId?: string) {
  if (!await permitted(url)) return;
  try {
    await chrome.scripting.executeScript({
      target: documentId ? {tabId, documentIds: [documentId]} : {tabId, frameIds: [0]},
      files: ['float-host.js'],
    });
  } catch { /* A closed or navigated tab is no longer a target. */ }
}
async function refreshTabs() {
  for (const tab of await chrome.tabs.query({})) {
    if (!tab.id || !tab.url || tab.incognito) continue;
    if (await permitted(tab.url)) await attach(tab.id, tab.url);
    else await chrome.tabs.sendMessage(tab.id, {type: 'float.remove'}, {frameId: 0}).catch(() => {});
  }
}
export function listenForFloatSites() {
  chrome.webNavigation.onDOMContentLoaded.addListener(e => {
    if (e.frameId === 0) void attach(e.tabId, e.url, e.documentId);
  });
  function routeChanged(event: {tabId: number; frameId: number}) {
    if (event.frameId === 0) void chrome.tabs.sendMessage(event.tabId, {type:'float.pageChanged'}).catch(() => {});
  }
  chrome.webNavigation.onHistoryStateUpdated.addListener(routeChanged);
  chrome.webNavigation.onReferenceFragmentUpdated.addListener(routeChanged);
  chrome.runtime.onStartup.addListener(() => void refreshTabs());
  chrome.runtime.onInstalled.addListener(() => void refreshTabs());
  chrome.permissions.onRemoved.addListener(() => void refreshTabs());
}

export async function updateFloatSites(add: string[], remove: string[], binding?: BindingUpdate) {
  if (!Array.isArray(add) || !Array.isArray(remove) ||
      [...add, ...remove].some(origin => typeof origin !== 'string' || !supportedUrl(origin) || originOf(origin) !== origin))
    throw new Error('请选择有效的站点');
  await navigator.locks.request(sitesKey, async () => {
    const origins = [...new Set(add.map(hostPattern))];
    if (origins.length && !await chrome.permissions.contains({origins}))
      throw new Error('未获得所选站点的访问权限，设置未保存');
    const updated = new Set(await sites());
    for (const origin of remove) updated.delete(origin);
    for (const origin of add) updated.add(origin);
    const changes: Record<string, unknown> = {[sitesKey]: [...updated]};
    if (binding) {
      if (!binding.scope || typeof binding.scope !== 'string' || !binding.values || typeof binding.values !== 'object')
        throw new Error('环境关联无效');
      const key = bindingsKey(binding.scope);
      const values = storedBindings((await chrome.storage.local.get(key))[key]);
      for (const site of remove) delete values[site];
      for (const [site, code] of Object.entries(binding.values)) {
        if (!updated.has(site) || typeof code !== 'string') throw new Error('站点或环境已变更，请刷新');
        if (code) values[site] = code; else delete values[site];
      }
      changes[key] = values;
    }
    await chrome.storage.local.set(changes);
  });
  await refreshTabs();
}

// Only the isolated top-frame script can obtain a ticket. Bind it to the
// top document and then to the actual extension frame, including across worker restarts.
export async function floatHostPage(sender: chrome.runtime.MessageSender, ticket: unknown) {
  const tabId = sender.tab?.id;
  if (tabId === undefined || sender.tab?.incognito || sender.frameId !== 0 ||
      !sender.documentId || typeof ticket !== 'string') return;
  const key = 'float-ticket:' + tabId;
  const grant = (await chrome.storage.session.get(key))[key] as {nonce:string; top:string} | undefined;
  if (grant?.nonce !== ticket || grant.top !== sender.documentId) return;
  const top = await chrome.webNavigation.getFrame({tabId, frameId:0});
  if (top?.documentId === sender.documentId && await permitted(top.url)) return top;
}

export async function floatAccess(sender: chrome.runtime.MessageSender, ticket?: string) {
  const tabId = sender.tab?.id;
  if (!tabId || sender.tab?.incognito || !sender.documentId) return false;
  const top = await chrome.webNavigation.getFrame({tabId, frameId: 0});
  if (!top || !await permitted(top.url)) return false;
  const key = 'float-ticket:' + tabId;
  if (ticket === undefined) {
    if (sender.frameId !== 0 || top.documentId !== sender.documentId) return false;
    const nonce = crypto.randomUUID();
    await chrome.storage.session.set({[key]: {nonce, top: top.documentId}});
    return nonce;
  }
  if (!ticket || !sender.frameId || sender.url?.split('#')[0] !== chrome.runtime.getURL('floating.html')) return false;
  // Chrome omits embedded extension documents from webNavigation. The private
  // ticket ties this frame to the isolated script of the authorized top document.
  const grant = (await chrome.storage.session.get(key))[key] as
    {nonce: string; top: string; frame?: string} | undefined;
  if (!grant || grant.nonce !== ticket || grant.top !== top.documentId ||
      (grant.frame && grant.frame !== sender.documentId)) return false;
  await chrome.storage.session.set({[key]: {...grant, frame: sender.documentId}});
  return true;
}
