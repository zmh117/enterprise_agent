import { floatAccess, listenForFloatSites, updateFloatSites } from './float-sites';
import { rememberPlatform } from '../../shared/platform-traffic';
import { SessionManager } from './session/manager';
import { cleanText } from '../../shared/redaction';
import { active, now, terminal } from '../../shared/contracts';

const manager = new SessionManager();
listenForFloatSites();
chrome.tabs.onRemoved.addListener(id => void chrome.storage.session.remove('float-ticket:' + id));
const guard = (fn: () => void | Promise<unknown>) => { void manager.ready.then(fn).catch(e => console.error('Browser collector:', cleanText(String(e)))); };

// Synchronous top-level registration: no attach is possible before these listeners exist.
chrome.tabs.onCreated.addListener(tab => { const seq = manager.tick(); const at = now(); guard(() => manager.created(tab, seq, at)); });
chrome.tabs.onRemoved.addListener(id => { const seq = manager.tick(); guard(() => manager.closed(id, seq)); });
chrome.tabs.onAttached.addListener((id, info) => guard(() => manager.moved(id, info.newWindowId, 'tabs.onAttached')));
chrome.tabs.onDetached.addListener((id, info) => guard(() => manager.moved(id, info.oldWindowId, 'tabs.onDetached')));
chrome.tabs.onMoved.addListener((id, info) => guard(() => manager.moved(id, info.windowId, 'tabs.onMoved')));
chrome.tabs.onReplaced.addListener((added, removed) => guard(() => manager.replaced(added, removed)));
chrome.tabs.onUpdated.addListener((id, info) => guard(() => manager.updated(id, info)));
chrome.webNavigation.onCreatedNavigationTarget.addListener(d => { const seq = manager.tick(); const at = now(); guard(() => manager.navigationTarget(d, seq, at)); });
chrome.webNavigation.onTabReplaced.addListener(d => guard(() => manager.replaced(d.tabId, d.replacedTabId)));
chrome.webNavigation.onBeforeNavigate.addListener(d => guard(() => manager.beforeNavigate(d)));
chrome.webNavigation.onCommitted.addListener(d => guard(() => manager.navigation(d)));
chrome.webNavigation.onDOMContentLoaded.addListener(d => guard(() => manager.navigation(d)));
chrome.webNavigation.onHistoryStateUpdated.addListener(d => guard(() => manager.navigation(d, true)));
chrome.webNavigation.onReferenceFragmentUpdated.addListener(d => guard(() => manager.navigation(d, true)));
chrome.webNavigation.onErrorOccurred.addListener(d => guard(() => {
  const t = manager.targets.get(d.tabId);
  if (t && active(manager.recording?.state)) manager.diagnostic('navigation_error', cleanText(d.error), t, 'page');
}));
chrome.debugger.onEvent.addListener((source, method, params) => guard(() => manager.debugger?.event(source, method, params ?? {})));
chrome.debugger.onDetach.addListener((source, reason) => guard(() => manager.debugger?.detached(source, reason)));
chrome.permissions.onAdded.addListener(() => guard(() => manager.refreshPermissions()));
chrome.permissions.onRemoved.addListener(removed => guard(() => manager.permissionsRemoved(removed)));
chrome.action.onClicked.addListener(() => { void chrome.tabs.create({ url: chrome.runtime.getURL('control.html') }); });

function controlSender(sender: chrome.runtime.MessageSender) {
  return sender.id === chrome.runtime.id && sender.url?.split('?')[0]?.split('#')[0] === chrome.runtime.getURL('control.html');
}
function validateCommand(m: any) {
  if (JSON.stringify(m).length > 128 * 1024) throw new Error('控制消息过大');
  for (const key of ['recordingId', 'commandId']) if (m[key] !== undefined && (typeof m[key] !== 'string' || !/^[a-z0-9-]{1,80}$/i.test(m[key]))) throw new Error(`无效 ${key}`);
  if (['session.start', 'session.add_root', 'session.mark', 'session.stop'].includes(m.type) && (!m.commandId || !m.recordingId)) throw new Error('缺少 commandId/recordingId');
  for (const key of ['note']) if (m[key] !== undefined && (typeof m[key] !== 'string' || m[key].length > 8000)) throw new Error(`无效 ${key}`);
  if (['session.add_root', 'session.mark'].includes(m.type) && !Number.isSafeInteger(m.browserTabId)) throw new Error('无效标签 ID');
}
chrome.runtime.onMessage.addListener((m, sender, respond) => {
  if (!m || typeof m !== 'object' || typeof m.type !== 'string' || sender.id !== chrome.runtime.id) return;
  const run = async () => {
    await manager.ready;
    if (m.type === 'page.handshake') return { ok: true, ticket: await manager.handshake(sender) };
    if (m.type === 'page.bound') { manager.bound(m.ticketId, sender); return { ok: true }; }
    if (m.type === 'page.ended') { manager.ended(m.ticketId, sender); return { ok: true }; }
    if (m.type === 'capture.batch') return manager.capture(m, sender);
    if (m.type === 'page.transport_error') { manager.transportError(m.ticketId, sender, String(m.code).slice(0, 100)); return { ok: true }; }
    if (m.type === 'float.prepare') return {ticket: await floatAccess(sender)};
    if (m.type === 'float.verify') return {ok: typeof m.ticket === 'string' && await floatAccess(sender, m.ticket)};
    if (m.type === 'agent.exclude_origin' && typeof m.ticket === 'string') {
      const saved = await chrome.storage.local.get('agentOrigin');
      return {ok: saved.agentOrigin === m.origin && await floatAccess(sender, m.ticket)};
    }
    if (!controlSender(sender)) throw new Error('只有扩展控制页可以发送控制命令');
    if (m.type === 'agent.exclude_origin') {
      rememberPlatform(m.origin);
      await navigator.locks.request('agent-platform-origins', async () => {
        const value = (await chrome.storage.local.get('agentPlatformOrigins')).agentPlatformOrigins;
        const origins: string[] = Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
        if (!origins.includes(m.origin)) await chrome.storage.local.set({agentPlatformOrigins: [...origins, m.origin]});
      });
      return { ok: true };
    }
    if (m.type === 'float.sites.update') {
      await updateFloatSites(m.add, m.remove, m.binding);
      return {ok: true};
    }
    validateCommand(m);
    switch (m.type) {
      case 'scope.list': return { ok: true, ...await manager.directory() };
      case 'session.start': return { ok: true, ...await manager.start(m) };
      case 'session.status': return { ok: true, ...manager.status() };
      case 'session.add_root': return { ok: true, ...await manager.addRoot(m) };
      case 'session.mark': return { ok: true, ...await manager.mark(m) };
      case 'session.stop':
        return { ok: true, ...await manager.stopCommand(m) };
      case 'storage.retry': await manager.retrySave(); return { ok: true };
      case 'history.list': return { ok: true, recordings: (await manager.db.listRecordings()).sort((a, b) => b.startedAt.localeCompare(a.startedAt)) };
      case 'history.delete': {
        const r = await manager.db.getRecording(m.recordingId);
        if (!r || !terminal(r.state)) throw new Error('只允许删除已结束的会话');
        await manager.db.deleteRecording(m.recordingId); return { ok: true };
      }
      case 'export.create': {
        if (manager.recording?.recordingId === m.recordingId && manager.recording.saveState === 'error' && manager.journal.metrics().retryableFailure) {
          if (!await manager.db.getRecording(m.recordingId)) throw new Error('尚无已提交数据，请重试保存');
          return { ok: true, recordingId: m.recordingId, savedPrefix: true, cutoffAt: manager.recording.stoppedAt, reason: manager.recording.saveError };
        }
        if (manager.recording?.recordingId === m.recordingId) { if (!terminal(manager.recording.state)) throw new Error('请先结束采集'); await manager.journal.flush(); }
        const r = await manager.db.getRecording(m.recordingId);
        if (!r || !terminal(r.state)) throw new Error('会话尚未完成保存');
        return { ok: true, recordingId: r.recordingId };
      }
      default: throw new Error('不支持的消息类型');
    }
  };
  void run().then(respond, e => respond({ ok: false, error: cleanText(String(e)) }));
  return true;
});
