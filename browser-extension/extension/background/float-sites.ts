import {localPageRule} from '../site-rules';
import { originOf, supportedUrl } from '../../shared/policy';
import { platformTraffic } from '../../shared/platform-traffic';
import { observeWorkerTask } from './worker-task';

export function hostPattern(origin: string) {
  const url = new URL(origin);
  return url.protocol + '//' + url.hostname + '/*';
}

async function permitted(url: string) {
  const origin = originOf(url);
  return !!origin && supportedUrl(url) && !platformTraffic(url) &&
    (await localPageRule(url))?.floating === true &&
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
    if (e.frameId === 0) void observeWorkerTask('加载浮窗', attach(e.tabId, e.url, e.documentId));
  });
  async function routeChanged(event: {tabId: number; frameId: number; url: string; documentId: string}) {
    if (event.frameId !== 0) return;
    if (await permitted(event.url)) {
      await attach(event.tabId, event.url, event.documentId);
      await chrome.tabs.sendMessage(event.tabId, {type:'float.pageChanged'}).catch(() => {});
    } else await chrome.tabs.sendMessage(event.tabId,{type:'float.remove'}, {frameId:0}).catch(() => {});
  }
  const refresh = () => { void observeWorkerTask('刷新站点浮窗', refreshTabs()); };
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && (changes.agentOrigin || changes.agentActiveAccount ||
      Object.keys(changes).some(key => key.startsWith('["site-rules",')))) refresh();
  });
  const refreshRoute = (event: Parameters<typeof routeChanged>[0]) => { void observeWorkerTask('更新页面浮窗', routeChanged(event)); };
  chrome.webNavigation.onHistoryStateUpdated.addListener(refreshRoute);
  chrome.webNavigation.onReferenceFragmentUpdated.addListener(refreshRoute);
  chrome.runtime.onStartup.addListener(refresh);
  chrome.runtime.onInstalled.addListener(refresh);
  chrome.permissions.onRemoved.addListener(refresh);
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
