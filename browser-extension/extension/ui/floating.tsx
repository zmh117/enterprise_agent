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
  function connectButton(id: string, view: 'history' | 'console') {
    const button = byId(id) as HTMLButtonElement;
    button.hidden = false;
    button.onclick = async () => {
      button.disabled = true;
      try {
        const result = await chrome.runtime.sendMessage({type:'float.openControl', ticket, view});
        if (!result?.ok) throw new Error();
      } catch {
        byId('agent-status').textContent = '无法打开插件页面，请刷新当前 MES 页面后重试。';
      } finally {
        button.disabled = false;
      }
    };
  }
  connectButton('agent-open-history', 'history');
  connectButton('agent-open-console', 'console');
  const saved = await chrome.storage.local.get('agentOrigin');
  if (!saved.agentOrigin) byId('agent-status').textContent = '请先在插件控制台连接 Enterprise Agent。';
  byId('floating-view').hidden = false;
  setupAgentPanel(createTimeline(byId('agent-answers')), ticket);
}
void start().catch(() => { document.body.textContent = '助手连接失败，请刷新当前页面后重试。'; });
