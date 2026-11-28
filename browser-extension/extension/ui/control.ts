import { commonEnvironment, recordingLabel } from '../../shared/recording-environment';
import type { SessionManager } from '../background/session/manager';
import { workshopSettings } from './workshop-settings';
import { hostPattern } from '../background/float-sites';
import { setupAgentPanel } from './agent-panel';
import { policyForOrigins, parsePolicy } from '../../shared/policy';
import { active, terminal, uuid, type BundleData, type Recording, type Target } from '../../shared/contracts';
import { EvidenceDB } from '../storage/database';
import { createPackage, summarize, savedPrefix } from '../export/package';
import { validateSensitiveSelectors } from '../../shared/page-privacy';
import { captureHealth } from '../../shared/capture-health';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const val = (id: string) => $<HTMLInputElement>(id).value;
const db = new EvidenceDB();
type Directory = Awaited<ReturnType<SessionManager['directory']>>;
type DirectoryTab = Directory['windows'][number]['tabs'][number];
let directory: Directory | undefined;
let current: Recording | null = null;
let targets: Target[] = [];
let viewed: string | null = null;
let records: Recording[] = [];
let historyRevision = 0;
let bundle: BundleData | null = null;
let busy = false;
let drafting = false;
const selected = new Set<number>();
async function rpc(type: string, data: object = {}) { const r = await chrome.runtime.sendMessage({ type, ...data }); if (!r?.ok) throw new Error(r?.error ?? '扩展后台无响应'); return r; }
function notice(message: string) { $('notice').textContent = message; $('notice').hidden = !message; }
function updateStartButton() { $<HTMLButtonElement>('start').disabled = busy || !selected.size; }
function element(tag: string, text = '', className = '') { const e = document.createElement(tag); e.textContent = text; e.className = className; return e; }
function on(id: string, action: () => unknown | Promise<unknown>) {
  $(id).addEventListener('click', () => { if (busy) return; busy = true; updateStartButton(); notice(''); void Promise.resolve().then(action).catch(e => notice(String(e))).finally(() => { busy = false; updateStartButton(); }); });
}
const size = (n: number) => n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
const labels: Record<string, string> = { STARTING: '准备中', RECORDING: '采集中', STOPPING: '已停止 · 清理中', FINALIZING: '正在保存', READY: '已停止 · 可导出', INTERRUPTED: '异常中断 · 可导出', FAILED: '启动失败 · 可导出', PENDING: '准备中', ACTIVE: '采集中', BLOCKED: '未覆盖', LOST: '已中断', STOPPED: '已停止' };
function defaultPolicy() {
  const origins = [...new Set((directory?.windows ?? []).flatMap(w => w.tabs)
    .filter(t => t.id !== undefined && selected.has(t.id) && t.origin).map(t => t.origin!))];
  return policyForOrigins(origins);
}
const workshop = workshopSettings(selectionChanged, () => refreshEnvironments());

function selectionChanged() {
  if (!directory) return;
  $('selection-count').textContent = `${selected.size} 个已选`;
  updateStartButton();
  const policy = defaultPolicy();
  const bindings = workshop.activeBindings(selected);
  const sites = Object.fromEntries(policy.pageOrigins.map(site => [site, bindings[site] ?? '']));
  const codes = [...new Set(Object.values(sites).filter(Boolean))];
  if (Object.values(sites).includes('')) codes.push('未关联');
  $('environment').textContent = commonEnvironment(sites) || codes.join('、') || '未关联';
  if (!$('policy-details').hasAttribute('data-edited')) $<HTMLTextAreaElement>('policy').value = JSON.stringify(policy, null, 2);
}
function visibleWindows() {
  const query = val('tab-search').trim().toLocaleLowerCase();
  return (directory?.windows ?? []).map(win => ({...win, tabs: win.tabs.filter(tab =>
    !query || (tab.title + ' ' + tab.url).toLocaleLowerCase().includes(query))})).filter(win => win.tabs.length);
}
function selectTabs(tabs: DirectoryTab[], checked: boolean) {
  for (const tab of tabs) if (tab.eligible && tab.id !== undefined) {
    if (checked) selected.add(tab.id); else selected.delete(tab.id);
  }
  renderDirectory();
}
function checkboxState(box: HTMLInputElement, tabs: DirectoryTab[]) {
  const eligible = tabs.filter(t => t.eligible && t.id !== undefined);
  const count = eligible.filter(t => selected.has(t.id!)).length;
  box.disabled = !eligible.length;
  box.checked = count > 0 && count === eligible.length;
  box.indeterminate = count > 0 && count < eligible.length;
}
function renderDirectory() {
  const root = $('directory'); root.replaceChildren();
  const windows = visibleWindows();
  const all = $<HTMLInputElement>('select-all');
  const allTabs = windows.flatMap(w => w.tabs);
  checkboxState(all, allTabs);
  const groupChecks: (() => void)[] = [];
  for (const win of windows) {
    const section = element('div', '', 'window-group');
    const heading = element('label', '', 'window-heading check');
    const check = document.createElement('input'); check.type = 'checkbox';
    heading.append(check, document.createTextNode(`窗口 ${win.id}${win.focused ? ' · 当前窗口' : ''}`));
    section.append(heading);
    checkboxState(check, win.tabs);
    groupChecks.push(() => checkboxState(check, win.tabs));
    check.onchange = () => selectTabs(win.tabs, check.checked);
    for (const tab of win.tabs) {
      const row = element('label', '', `tab-row${tab.eligible ? '' : ' disabled'}`);
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.disabled = !tab.eligible || tab.id === undefined;
      cb.checked = tab.id !== undefined && selected.has(tab.id); cb.dataset.tabId = String(tab.id);
      cb.onchange = () => {
        if (tab.id === undefined) return;
        if (cb.checked) selected.add(tab.id); else selected.delete(tab.id);
        checkboxState(all, allTabs); groupChecks.forEach(update => update()); selectionChanged();
      };
      const info = element('span');
      info.append(element('span', tab.title || '未命名标签', 'tab-title'), element('small', tab.url));
      row.append(cb, info);
      if (!tab.eligible) row.append(element('span', '受限页面', 'muted'));
      section.append(row);
    }
    root.append(section);
  }
  if (!windows.length) root.append(element('p', val('tab-search') ? '没有匹配的标签' : '暂无可选标签', 'muted'));
  selectionChanged();
}
async function refreshDirectory() {
  const d: Directory = await rpc('scope.list');
  directory = d;
  const tabs = d.windows.flatMap(w => w.tabs).filter(t => t.eligible);
  const existing = new Set(tabs.map(t => t.id));
  for (const id of selected) if (!existing.has(id)) selected.delete(id);
  $('runtime').textContent = 'v' + d.extensionVersion;
  renderDirectory();
  workshop.pages(tabs);
  selectionChanged();
}
function drawStatus(s: any) {
  if (viewed && s.recording?.recordingId !== viewed) return;
  if (s.recording?.recordingId !== current?.recordingId) {
    $('preview-panel').hidden = true; $('delivery-status').textContent = ''; $('add-root').hidden = true;
  }
  current = s.recording; targets = s.targets ?? [];
  if (!current || drafting) {
    $('prepare').hidden = false; $('session').hidden = true;
    $('status-pill').textContent = '未开始'; $('status-pill').className = 'pill';
    return;
  }
  $('prepare').hidden = true; $('session').hidden = false;
  const live = active(current.state); const done = terminal(current.state);
  const count = targets.filter(t => t.accepting && t.lifecycle === 'OPEN').length;
  const ready = targets.filter(t => t.accepting && captureHealth(t) === 'ACTIVE').length;
  const partial = live && count > 0 && ready < count;
  $('status-pill').textContent = current.state === 'STARTING' ? '准备中' : partial ? '部分采集' : labels[current.state] ?? current.state;
  $('status-pill').className = `pill${live ? partial ? ' warning' : ' live' : ''}`;
  $('recording-id').textContent = current.recordingId;
  const seconds = Math.max(0, Math.floor((Date.parse(current.stoppedAt ?? new Date().toISOString()) - Date.parse(current.startedAt)) / 1000));
  $('duration').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('target-count').textContent = `${count} / ${targets.length}`;
  $('saved-size').textContent = size(current.bytesPersisted);
  $('save-state').textContent = { saved: '已保存', pending: '正在保存', error: '保存失败' }[current.saveState];
  $('session-message').textContent = live && !count ? '当前无活动标签，等待结束 / 导出。无关新标签不会加入。' : s.durationReminder ? '已达到录制时长提醒阈值。可以结束并交付，或继续采集。' : '';
  if (current.stopProgress && (current.saveState !== 'saved' || current.stopProgress.terminal !== 'complete')) {
    const p = current.stopProgress; const phase = { pending: '等待中', complete: '已完成', error: '失败' };
    $('session-message').textContent = `采集已截止；停止标记：${phase[p.marker]}；连接清理：${phase[p.cleanup]}；批次排空：${phase[p.drain]}；终结保存：${current.saveState === 'saved' ? phase[p.terminal] : phase[current.saveState === 'error' ? 'error' : 'pending']}。${p.deadlineExceeded ? '等待已超过 5 秒，事务未确定结果时不会并发重试。' : ''}`;
    $('status-pill').textContent = '已停止 · 保存未完成';
  }

  const area = $('targets'); area.replaceChildren();
  for (const t of targets) {
    const row = element('div', '', 'target'); const heading = element('div', '', 'target-head');
    heading.append(element('strong', `${t.membershipReason === 'derived' ? '↳ ' : ''}${t.title || '未命名标签'}`, 'target-title'), element('span', t.lifecycle === 'CLOSED' ? '已关闭' : labels[t.captureState] ?? t.captureState, 'pill'));
    row.append(heading, element('div', `窗口 ${t.windowId} · ${t.url}`, 'muted'), element('div', `${t.tabInstanceId} · 父：${t.parentTabInstanceId ?? '根节点'}${t.cutoffObservedAt ? ` · 截止 ${t.cutoffObservedAt}` : ''}`, 'lineage'));
    const channels = element('div', '', 'channels');
    for (const [name, c] of Object.entries(t.channels)) channels.append(element('span', `${({ page: '页面', semantic: '操作', network: '网络', runtime: '错误', screenshot: '截图' } as any)[name]} · ${name === 'screenshot' ? '已停用（像素隐私）' : labels[c.state] ?? c.state}${c.reason && name !== 'screenshot' ? ` · ${c.reason}` : ''}`, `channel ${c.state === 'ACTIVE' ? 'good' : ['BLOCKED', 'LOST'].includes(c.state) ? 'bad' : ''}`));
    row.append(channels); area.append(row);
  }
  const select = $<HTMLSelectElement>('mark-target'); const previous = select.value; select.replaceChildren();
  for (const t of targets.filter(t => t.lifecycle === 'OPEN' && t.accepting)) { const option = new Option(t.title || `标签 ${t.browserTabId}`, String(t.browserTabId)); select.add(option); }
  if ([...select.options].some(o => o.value === previous)) select.value = previous;
  if (!live) $('add-root').hidden = true;
  $('live-actions').hidden = !live; $('stop').hidden = !live; $('new').hidden = !done;
  $<HTMLButtonElement>('preview').disabled = !done && current.saveState !== 'error'; $<HTMLButtonElement>('export').disabled = current.saveState !== 'error' && (!done || current.saveState !== 'saved');
  $('export').textContent = current.saveState === 'error' ? '导出已保存部分' : '导出 ZIP';
  $('retry-save').hidden = current.saveState !== 'error';
  $('gap-count').textContent = `${current.gaps.length} 项`;
  const gaps = $('gaps'); gaps.replaceChildren(...current.gaps.map(g => element('li', `${g.code}：${g.detail}`)));
  if (current.saveState === 'error') notice(`本地保存失败：${s.saveError ?? current.saveError ?? '未知错误'}。已停止新采集，请重试保存。`);
}
async function refreshStatus() {
  if (viewed) return;
  const result = await rpc('session.status');
  drawStatus(result);
  const live = result.continuous;
  $('live-session').hidden = !live;
  if (live) {
    $('session').hidden = true; $('prepare').hidden = true;
    $('status-pill').textContent = '持续采集已启动'; $('status-pill').className = 'pill live';
    $('live-progress').textContent='待传 '+live.pending+' · 已转发待核对 '+live.acknowledged+' · 已核对 '+live.verified;
    const states:Record<string,string> = {paused:'页面采集已暂停，请刷新或重新打开', unbound:'当前 URL 未绑定范围', baseline:'等待新文档基线', ready:'正在采集'};
    const select = $<HTMLSelectElement>('live-add-target'), selected = select.value;
    const candidates = (directory?.windows ?? []).flatMap(w=>w.tabs).filter(t=>t.eligible && !live.tabs.some((x:{tabId:number})=>x.tabId===t.id));
    select.replaceChildren(...candidates.map(t=>new Option(t.title || t.origin || '标签',String(t.id))));
    if (candidates.some(t=>String(t.id)===selected)) select.value = selected;
    $<HTMLButtonElement>('live-add').disabled = !candidates.length;
    $('live-tabs').replaceChildren(...live.tabs.map((t:{tabId:number; state:string; error?:string; networkGap?:string;network?:{mapped:boolean}}) =>
      element('p', '标签 '+t.tabId+' · '+(t.error || states[t.state] || '等待页面')+(t.networkGap?' · '+t.networkGap:t.state==='ready' && !t.network?.mapped?' · 网络通道待就绪':''))));
  }
}
async function loadBundle(id: string) { const result = await rpc('export.create', { recordingId: id }); const data = await db.bundle(id); return result.savedPrefix ? savedPrefix(data, result.cutoffAt ?? new Date().toISOString(), result.reason ?? '保存失败') : data; }
async function preview(id: string) {
  bundle = await loadBundle(id);
  $('preview-panel').hidden = false; $('summary-preview').textContent = summarize(bundle);
  const sel = $<HTMLSelectElement>('request-select'); sel.replaceChildren(new Option('选择一个请求', ''));
  bundle.network.forEach((r, i) => sel.add(new Option(`${r.request.method} ${r.request.url} · ${r.response.httpStatus} / ${r.businessOutcome}`, String(i))));
  $('request-preview').textContent = '展示已保存的正文、请求头与状态；默认仅保护登录密码，其他文本保留原值。截图停用。';
}
async function exportZip(id: string) {
  const attemptId = uuid(); const startedAt = new Date().toISOString();
  $('delivery-status').textContent = '正在读取和校验已保存数据…';
  let data: BundleData | undefined;
  const track = async (value: Record<string, unknown>) => { try { await db.saveExport(id, { startedAt, observedAt: new Date().toISOString(), ...value }, attemptId); } catch (error) { if (!data?.recording.capabilities.savedPrefixOnly) throw error; } };
  try {
    data = await loadBundle(id);
    await track({ state: 'generating' });
    $('delivery-status').textContent = '正在生成 ZIP（采集已停止）…';
    const result = await createPackage(data);
    const url = URL.createObjectURL(new Blob([new Uint8Array(result.zip)], { type: 'application/zip' }));
    let downloadId: number;
    try { downloadId = await chrome.downloads.download({ url, filename: `browser-capture-${id}.zip`, saveAs: true }); }
    catch (e) { URL.revokeObjectURL(url); throw e; }
    await track({ state: 'downloading', downloadId });
    $('delivery-status').textContent = 'ZIP 已生成，等待浏览器完成保存…';
    const watcher = (delta: chrome.downloads.DownloadDelta) => {
      if (delta.id !== downloadId || !delta.state) return;
      if (delta.state.current === 'complete' || delta.state.current === 'interrupted') {
        URL.revokeObjectURL(url); chrome.downloads.onChanged.removeListener(watcher);
        const complete = delta.state.current === 'complete';
        $('delivery-status').textContent = complete ? data!.recording.capabilities.savedPrefixOnly ? '已保存部分 ZIP 已下载；未提交批次仍待重试。' : 'ZIP 已保存，清单、SHA-256 与证据引用校验通过。' : '文件下载未完成，可以重新导出。';
        void track({ state: complete ? 'complete' : 'download_interrupted', downloadId }).catch(e => notice(`下载状态保存失败：${String(e)}；本地证据保留。`));
      }
    };
    chrome.downloads.onChanged.addListener(watcher);
    const [item] = await chrome.downloads.search({ id: downloadId });
    if (item?.state !== 'in_progress') watcher({ id: downloadId, state: { current: item?.state ?? 'interrupted' } });
  } catch (e) { $('delivery-status').textContent = '导出失败；本地证据保留，可重试。'; await track({ state: 'failed', error: String(e) }); throw e; }
}
async function exportHistory(id: string) {
  const attempts = await db.list<{ state: string; startedAt?: string; observedAt: string; downloadId?: number }>('exports', id);
  const last = attempts.sort((a, b) => (b.startedAt ?? b.observedAt).localeCompare(a.startedAt ?? a.observedAt))[0];
  if (!last) return '';
  let state = last.state;
  if (last.downloadId !== undefined && ['downloading', 'complete'].includes(state)) {
    const [item] = await chrome.downloads.search({ id: last.downloadId });
    state = item?.state === 'complete' ? 'complete' : item?.state === 'interrupted' ? 'download_interrupted' : 'downloading';
  }
  return ({ generating: '上次生成未确认完成，可重新导出', downloading: '上次下载未确认完成，可重新导出', complete: '上次 ZIP 下载已完成', download_interrupted: '上次下载未完成，可重新导出', failed: '上次导出失败，可重试；本地证据保留' } as Record<string, string>)[state] ?? '上次导出状态未知，可重新导出';
}
async function history() {
  const turn = ++historyRevision;
  const result = await rpc('history.list');
  if (turn !== historyRevision) return;
  records = result.recordings;
  renderHistory();
}
function renderHistory() {
  const root = $('history'); root.replaceChildren();
  const term = val('history-search').trim().toLocaleLowerCase();
  const rows = records.filter(r => (recordingLabel(r) + ' ' + r.recordingId + ' ' +
    Object.values(r.rootEnvironments ?? {}).join(' ')).toLocaleLowerCase().includes(term));
  if (!rows.length) root.append(element('p', term ? '没有匹配的记录' : '暂无采集记录', 'muted'));
  for (const r of rows) {
    const row = element('div', '', 'history-row'); const info = element('div'); info.append(element('strong', recordingLabel(r)), element('small', `${labels[r.state]} · ${size(r.bytesPersisted)}`));
    row.dataset.recordingId = r.recordingId;
    const lastExport = element('small', '', 'export-history'); info.append(lastExport);
    void exportHistory(r.recordingId).then(text => { lastExport.textContent = text; }).catch(() => {});
    const actions = element('div', '', 'button-row');
    for (const [title, action] of [['查看', async () => {
      if (terminal(r.state)) { const b = await db.bundle(r.recordingId); viewed = r.recordingId; drafting = false; drawStatus({ recording: b.recording, targets: b.targets }); }
      else { viewed = null; drafting = false; await refreshStatus(); }
      $('preview-panel').hidden = true; location.hash = 'capture';
    }], ['导出', () => exportZip(r.recordingId)], ['删除', async () => { if (confirm(`删除本地记录“${recordingLabel(r)}”及其全部证据？已导出文件不受影响。`)) { await rpc('history.delete', { recordingId: r.recordingId }); await history(); } }]] as [string, () => Promise<unknown>][]) {
      const button = element('button', title) as HTMLButtonElement; button.disabled = title !== '查看' && !terminal(r.state);
      button.addEventListener('click', () => { void action().catch(e => notice(String(e))); }); actions.append(button);
    }
    row.append(info, actions); root.append(row);
  }
}
on('refresh', refreshDirectory);
on('float-refresh', async () => {
  await Promise.all([refreshDirectory(), refreshEnvironments()]);
});
$('select-all').addEventListener('change', () =>
  selectTabs(visibleWindows().flatMap(w => w.tabs), $<HTMLInputElement>('select-all').checked));
$('tab-search').addEventListener('input', renderDirectory);
$('history-search').addEventListener('input', renderHistory);
function showView() {
  const id = location.hash.slice(1);
  const view = ['records','sites','assistant','conversations'].includes(id) ? id : 'capture';
  for (const panel of document.querySelectorAll<HTMLElement>('.view')) panel.hidden = panel.id !== view;
  for (const link of document.querySelectorAll<HTMLAnchorElement>('nav a')) {
    if (link.hash === '#' + view) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
  }
  if (view === 'records') void history().catch(e => notice(String(e)));
}
window.addEventListener('hashchange', showView);
showView();
$('policy').addEventListener('input', () => $('policy-details').setAttribute('data-edited', 'true'));
$('record-mode').addEventListener('change', () => {
  const continuous = val('record-mode') === 'continuous';
  $('start-feedback').textContent = '';
  $('offline-environment').hidden = continuous;
  $('start-settings').hidden = !continuous;
  $('policy-summary').textContent = continuous
    ? '在已绑定页面采集可见业务文字、操作和策略允许的输入值，脱敏后上传平台。'
    : '本地保存，仅隐藏登录密码，其他文本保留原值。';
});
$('start-settings').addEventListener('click', () => {
  if (selected.size === 1) workshop.selectTab([...selected][0]!);
});
on('live-refresh', async () => {await refreshDirectory(); await refreshStatus();});
on('live-add', async () => {await rpc('live.add',{tabId:Number(val('live-add-target'))}); await refreshStatus();});
on('live-stop', async () => {await rpc('live.stop'); drafting = true; await refreshStatus();});
on('reset-policy', () => { $('policy-details').removeAttribute('data-edited'); selectionChanged(); });
on('fixture-policy', () => {
  const p = defaultPolicy(); p.pageOrigins = ['http://127.0.0.1:4317', 'http://localhost:4318']; p.apiRules = p.pageOrigins.map(origin => ({ origin, pathPrefix: '/' })); p.captureStreaming = true;
  p.businessRules = [{ origin: 'http://127.0.0.1:4317', pathPrefix: '/api/', codePath: 'code', successValues: ['OK'] }];
  $<HTMLTextAreaElement>('policy').value = JSON.stringify(p, null, 2); $('policy-details').setAttribute('data-edited', 'true');
});
// permissions.request must be invoked directly in the click's user-gesture task.
$('start').addEventListener('click', async () => {
  if (busy) return;
  const feedback = $('start-feedback');
  const mode = val('record-mode') === 'continuous' ? 'continuous' : 'offline';
  const ids = [...selected];
  busy = true;
  updateStartButton();
  try {
    const policy = parsePolicy(JSON.parse(val('policy')), mode);
    validateSensitiveSelectors(policy, document);
    const destination = mode === 'continuous' ? workshop.destination(ids) : undefined;
    const patterns = [...policy.pageOrigins, ...policy.apiRules.map(r => r.origin)].map(hostPattern);
    feedback.textContent = '正在确认 Chrome 站点权限…';
    const granted = await chrome.permissions.request({ origins: [...new Set(patterns)] });
    if (destination) {
      feedback.textContent = granted ? '正在核对页面绑定范围并启动持续采集…' : '正在核对已获授权的标签页…';
      await rpc('live.start', {destination, ids, policy});
      viewed = null; drafting = false;
      await refreshStatus();
    } else {
      feedback.textContent = '正在启动离线录制…';
      const session = await rpc('session.start', {recordingId: uuid(), commandId: uuid(), browserRunId: directory!.browserRunId, rootBrowserTabIds: ids, policy, environments: workshop.activeBindings(selected)});
      viewed = null; drafting = false;
      drawStatus(session);
      await history();
    }
    feedback.textContent = '';
    notice('');
  } catch (e) {
    feedback.textContent = e instanceof Error ? e.message.replace(/^Error: /, '') : '启动失败，请重试';
  } finally {
    busy = false;
    updateStartButton();
  }
});
on('stop', async () => { drawStatus(await rpc('session.stop', { recordingId: current!.recordingId, commandId: uuid() })); await history(); });
on('mark', async () => { await rpc('session.mark', { recordingId: current!.recordingId, commandId: uuid(), browserTabId: Number(val('mark-target')), note: val('mark-note') }); $<HTMLInputElement>('mark-note').value = ''; notice('时间标记已保存。'); });
on('show-add', async () => { const d = await rpc('scope.list'); const sel = $<HTMLSelectElement>('add-target'); sel.replaceChildren(); for (const w of d.windows) for (const t of w.tabs) if (t.eligible && !targets.some(x => x.browserTabId === t.id && x.accepting)) sel.add(new Option(`${t.title} · ${t.origin}`, String(t.id))); $('add-root').hidden = false; });
on('add', async () => { drawStatus(await rpc('session.add_root', { recordingId: current!.recordingId, commandId: uuid(), scopeVersion: current!.scopeVersion, browserTabId: Number(val('add-target')), environments: workshop.activeBindings([Number(val('add-target'))]) })); $('add-root').hidden = true; });
on('retry-save', async () => { await rpc('storage.retry'); await refreshStatus(); });
on('preview', () => preview(current!.recordingId));
on('export', () => exportZip(current!.recordingId));
on('close-preview', () => { $('preview-panel').hidden = true; });
on('new', async () => { viewed = null; drafting = true; current = null; $('status-pill').textContent = '未开始'; $('prepare').hidden = false; $('session').hidden = true; $('preview-panel').hidden = true; await refreshDirectory(); });
$('request-select').addEventListener('change', () => {
  if (!bundle || val('request-select') === '') return;
  const r = bundle.network[Number(val('request-select'))]; if (!r) return;
  $('request-preview').textContent = JSON.stringify({ ...r, requestBody: bundle.blobs.find(b => b.path === r.request.bodyRef)?.data ?? null, responseBody: bundle.blobs.find(b => b.path === r.response.bodyRef)?.data ?? null }, null, 2);
});
void Promise.all([refreshDirectory(), refreshStatus(), history()]).catch(e => notice(String(e)));
setInterval(() => { if (!busy) void refreshStatus().catch(e => notice(String(e))); }, 1500);

const refreshEnvironments = setupAgentPanel(undefined, undefined, workshop.setCatalog);
