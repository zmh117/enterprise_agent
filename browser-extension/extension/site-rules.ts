import { bindingForPage, type WorkshopBinding } from '../shared/workshop';

export async function localPageContext(url: string) {
  const {agentOrigin, agentActiveAccount} = await chrome.storage.local.get(['agentOrigin', 'agentActiveAccount']);
  if (typeof agentOrigin !== 'string' || typeof agentActiveAccount !== 'string') return;
  const appKey = JSON.stringify(['agent-app', agentOrigin, agentActiveAccount]);
  const app = (await chrome.storage.local.get(appKey))[appKey];
  if (typeof app !== 'string') return;
  const key = JSON.stringify(['workshop-bindings', agentOrigin, agentActiveAccount, app]);
  const rules = (await chrome.storage.local.get(key))[key] as WorkshopBinding[] | undefined;
  const binding = rules && bindingForPage(url, rules, agentOrigin);
  if (binding) return {binding, destination:{origin:agentOrigin, account:agentActiveAccount, app}};
}
