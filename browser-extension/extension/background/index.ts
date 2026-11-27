import {localPageContext,localPageRule} from '../site-rules';
import {LiveCapture} from './live-capture';
import {parsePolicy, policyForOrigins, revokedHostMatches} from '../../shared/policy';
import { bindingForPage } from '../../shared/workshop';
import { floatAccess, floatHostPage, listenForFloatSites } from './float-sites';
import { rememberPlatform } from '../../shared/platform-traffic';
import { SessionManager } from './session/manager';
import { observeWorkerTask } from './worker-task';
import { cleanText } from '../../shared/redaction';
import { active, now, terminal } from '../../shared/contracts';

const manager = new SessionManager();
const live = new LiveCapture();
void observeWorkerTask('恢复离线录制', manager.ready);
void observeWorkerTask('恢复持续采集', live.ready);
listenForFloatSites();
chrome.alarms.onAlarm.addListener(alarm=>{if (alarm.name==='mes-live-delivery') liveGuard(()=>live.deliver());});
const ensureDeliveryAlarm=async()=>{if (!await chrome.alarms.get('mes-live-delivery')) await chrome.alarms.create('mes-live-delivery',{periodInMinutes:0.5});};
// Alarms can be cleared or their creation interrupted. Reconcile once per worker start.
void observeWorkerTask('设置持续采集定时任务', ensureDeliveryAlarm());
const liveGuard = (fn:()=>void | Promise<unknown>) => {void observeWorkerTask('处理持续采集事件', live.ready.then(fn));};
const captureLock = <T>(task: () => Promise<T>) => navigator.locks.request('mes-capture-start',task);
chrome.tabs.onRemoved.addListener(id=>liveGuard(()=>captureLock(()=>live.closed(id))));
function liveNavigation(d:{tabId:number;frameId:number;documentId:string;url:string}, sameDocument:boolean) {
  if (d.frameId === 0) liveGuard(()=>live.navigation(d.tabId,d.documentId,d.url,sameDocument));
}
chrome.webNavigation.onCommitted.addListener(d=>liveNavigation(d,false));
chrome.webNavigation.onHistoryStateUpdated.addListener(d=>liveNavigation(d,true));
chrome.webNavigation.onReferenceFragmentUpdated.addListener(d=>liveNavigation(d,true));
chrome.storage.onChanged.addListener((changes,area)=>{if (area==='local' && (changes.agentOrigin || changes.agentActiveAccount ||
  Object.keys(changes).some(key=>key.startsWith('["workshop-bindings",')))) liveGuard(()=>captureLock(()=>live.settingsChanged(changes)));});
chrome.permissions.onRemoved.addListener(p=>liveGuard(()=>captureLock(()=>live.revoked(url=>(p.origins ?? []).some(pattern=>revokedHostMatches(pattern,url))))));
chrome.tabs.onRemoved.addListener(id => void observeWorkerTask('清理浮窗授权', chrome.storage.session.remove('float-ticket:' + id)));
const guard = (fn: () => void | Promise<unknown>) => { void observeWorkerTask('处理录制事件', manager.ready.then(fn)); };

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
chrome.debugger.onEvent.addListener((source,method,params)=>liveGuard(()=>live.debugEvent(source,method,params ?? {})));
chrome.debugger.onDetach.addListener((source,reason)=>{if (source.tabId!==undefined) liveGuard(()=>live.detached(source.tabId!,reason));});
chrome.debugger.onEvent.addListener((source, method, params) => guard(() => manager.debugger?.event(source, method, params ?? {})));
chrome.debugger.onDetach.addListener((source, reason) => guard(() => manager.debugger?.detached(source, reason)));
chrome.permissions.onAdded.addListener(() => guard(() => manager.refreshPermissions()));
chrome.permissions.onRemoved.addListener(removed => guard(() => manager.permissionsRemoved(removed)));
chrome.action.onClicked.addListener(() => { void observeWorkerTask('打开控制台', chrome.tabs.create({ url: chrome.runtime.getURL('control.html') })); });

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
    await live.ready;
    if (['live.pause','live.event','live.gap'].includes(m.type)) return live.message(sender,m);
    if (m.type === 'page.handshake') return { ok: true, ticket: await manager.handshake(sender) };
    if (m.type === 'page.bound') { manager.bound(m.ticketId, sender); return { ok: true }; }
    if (m.type === 'page.ended') { manager.ended(m.ticketId, sender); return { ok: true }; }
    if (m.type === 'capture.batch') return manager.capture(m, sender);
    if (m.type === 'page.transport_error') { manager.transportError(m.ticketId, sender, String(m.code).slice(0, 100)); return { ok: true }; }
    if (m.type === 'float.prepare') return {ticket: await floatAccess(sender)};
    if (['float.captureStatus','float.captureStart','float.captureStop'].includes(m.type)) {
      const command = async () => {
        const top = await floatHostPage(sender,m.ticket);
        const id = sender.tab?.id;
        if (!top || id === undefined) throw new Error('本页授权已变化，请刷新页面');
        if (m.type === 'float.captureStart') {
          if (manager.recording && !terminal(manager.recording.state)) throw new Error('请先结束离线录制');
          const context = await localPageContext(top.url);
          if (!context?.binding.floating) throw new Error('请先在站点设置绑定本页');
          await live.startPage(id,{documentId:top.documentId,binding:context.binding},context.destination,
            policyForOrigins([new URL(top.url).origin]));
        } else if (m.type === 'float.captureStop') {
          if (typeof m.membership !== 'string') throw new Error('请重新打开本页菜单');
          await live.stopPage(id,m.membership);
        }
        return {ok:true, capture:live.pageStatus(id)};
      };
      return m.type === 'float.captureStatus' ? command() : captureLock(command);
    }
    if (m.type === 'float.openControl') {
      if ((m.view !== 'history' && m.view !== 'console') ||
          typeof m.ticket !== 'string' || !await floatAccess(sender, m.ticket)) return {ok:false};
      if (m.view === 'history') {
        await chrome.tabs.create({url: chrome.runtime.getURL('control.html#conversations'), windowId: sender.tab?.windowId});
      } else {
        await chrome.runtime.openOptionsPage();
      }
      return {ok:true};
    }
    if (m.type === 'float.destination' && typeof m.ticket === 'string' && sender.tab?.id && await floatAccess(sender,m.ticket)) {
      const top = await chrome.webNavigation.getFrame({tabId:sender.tab.id,frameId:0});
      return {app:top && (await localPageRule(top.url))?.app};
    }
    if (m.type === 'float.workshop') {
      const asked=Date.now(), tabId=sender.tab?.id;
      if (typeof m.ticket !== 'string' || !tabId || !Array.isArray(m.bindings) || !m.destination) return {ok:false};
      const top=await chrome.webNavigation.getFrame({tabId, frameId:0});
      if (!top || !await floatAccess(sender,m.ticket)) return {ok:false};
      const grant=(await chrome.storage.session.get('float-ticket:'+tabId))['float-ticket:'+tabId] as {top?:string}|undefined;
      if (grant?.top!==top.documentId) return {ok:false};
      const latest = await chrome.webNavigation.getFrame({tabId, frameId:0});
      if (latest?.documentId !== top.documentId || latest.url !== top.url) return {ok:false};
      const binding=bindingForPage(top.url,m.bindings,m.destination.origin);
      const actual = await localPageRule(top.url);
      if (!binding || !actual || actual.app !== m.destination.app || actual.id !== binding.id ||
          actual.revision !== binding.revision || actual.floating === false) return {ok:false};
      return {ok:true,captureState:live.tabState(tabId),binding,
        page:binding?live.questionPage(tabId,top.documentId,binding,m.destination,asked):null};
    }
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
    validateCommand(m);
    switch (m.type) {
      case 'scope.list': return { ok: true, ...await manager.directory() };
      case 'live.start':
        return captureLock(async () => {
          if (manager.recording && !terminal(manager.recording.state)) throw new Error('请先结束离线录制');
          const policy = parsePolicy(m.policy,'continuous');
          return {ok:true, continuous:await live.start(m.ids,m.destination,policy)};
        });
      case 'live.add': return captureLock(async () => {await live.add(m.tabId); return {ok:true};});
      case 'live.stop': return captureLock(async()=>{await live.stop(); return {ok:true};});
      case 'session.start':
        return captureLock(async () => {
          if (live.active) throw new Error('请先结束持续采集');
          return {ok:true,...await manager.start(m)};
        });
      case 'session.status': return { ok: true, ...manager.status(), continuous:await live.status() };
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
