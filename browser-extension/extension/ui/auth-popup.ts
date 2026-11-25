// Chrome creates the identity popup after the authorization page starts loading.
export async function openAuthPopup(url: string): Promise<string | undefined> {
  let listening = true;
  function stop() {
    listening = false;
    chrome.tabs.onCreated.removeListener(onTab);
    chrome.tabs.onUpdated.removeListener(onUpdate);
  }
  async function fit(tab: chrome.tabs.Tab) {
    const popup = await chrome.windows.get(tab.windowId, {populate: true});
    const current = popup.tabs?.[0];
    if (!listening || popup.type !== 'popup' || popup.tabs?.length !== 1 || !current ||
        current.id !== tab.id || (current.url !== url && current.pendingUrl !== url)) return;
    stop();
    const width = Math.min(480, popup.width ?? 480);
    const height = Math.min(520, popup.height ?? 520);
    const left = (popup.left ?? 0) + Math.round(((popup.width ?? width) - width) / 2);
    const top = (popup.top ?? 0) + Math.round(((popup.height ?? height) - height) / 2);
    await chrome.windows.update(tab.windowId, {width, height, left, top});
  }
  function onTab(tab: chrome.tabs.Tab) {
    if (tab.url === url || tab.pendingUrl === url) void fit(tab).catch(() => {});
  }
  function onUpdate(_id: number, change: chrome.tabs.OnUpdatedInfo, tab: chrome.tabs.Tab) {
    if (change.url || change.status === 'complete') onTab(tab);
  }
  chrome.tabs.onCreated.addListener(onTab);
  chrome.tabs.onUpdated.addListener(onUpdate);
  try {
    return await chrome.identity.launchWebAuthFlow({url, interactive: true});
  } finally {
    stop();
  }
}
