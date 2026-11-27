import { setupAgentPanel } from './agent-panel';
import { createTimeline } from './floating-timeline';

async function start() {
  const ticket = location.hash.slice(1);
  if (!ticket || window === top) return;
  const result = await chrome.runtime.sendMessage({type:'float.verify', ticket});
  if (!result?.ok) return;

  const byId = (id: string) => document.getElementById(id)!;
  const status = byId('agent-status');
  const composer = byId('agent-question').closest('.chat-compose-area')!;
  composer.prepend(status);
  const showStatus = () => { status.hidden = !status.textContent || status.textContent === '已连接'; };
  new MutationObserver(showStatus).observe(status,{childList:true,subtree:true,characterData:true});
  showStatus();
  const origin = byId('agent-origin') as HTMLInputElement;
  origin.readOnly = true;
  const history = byId('agent-open-history');
  history.hidden = false;
  history.onclick = () => void chrome.tabs.create({url: chrome.runtime.getURL('control.html#conversations')});
  const configure = byId('agent-open-console');
  configure.hidden = false;
  configure.onclick = () => void chrome.runtime.openOptionsPage();
  const saved = await chrome.storage.local.get('agentOrigin');
  if (!saved.agentOrigin) byId('agent-status').textContent = '请先在插件控制台连接 Enterprise Agent。';
  byId('floating-view').hidden = false;
  setupAgentPanel(createTimeline(byId('agent-answers')), ticket);
}
void start().catch(() => { document.body.textContent = '助手连接失败，请刷新当前页面后重试。'; });
