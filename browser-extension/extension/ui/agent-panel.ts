import { workshopLabel, type WorkshopScope, type WorkshopClient, type WorkshopBinding } from '../../shared/workshop';
import { Platform } from '../platform';
export { Platform } from '../platform';
import { recordingLabel, type EnvironmentCatalog, type EnvironmentOption } from '../../shared/recording-environment';
import { EvidenceDB } from '../storage/database';
import { terminal } from '../../shared/contracts';
import {
  canonicalManifest,
  prepareRecording,
  uploadRecording,
} from './recording-upload';
import { displayAnswer, messageTime, PlatformError } from './agent-answer';
import { ConversationHistory } from './conversation-history';
import { ActivityView, followActivity } from './job-activity';
import { copyReply } from './reply-copy';

import {
  finishMessage,
  chooseConversation,
  loadChat,
  rememberMessage,
  type Chat,
  type MessageRef,
  type Receipt,
} from './agent-chat';

type App = { id: string; name: string; scope_ref: string; environments?: EnvironmentOption[]; workshop_scopes?: WorkshopScope[] };
const el = <T extends HTMLElement>(id: string) =>
  document.getElementById(id) as T;

export function explain(e: unknown) {
  const messages: Record<string, string> = {
    login_required: '请重新登录以继续',
    consent_required: '请登录并确认插件授权',
    access_denied: '已无权读取此任务或应用',
    not_found: '资源已不可用，请重新选择录制或解除绑定',
    upload_expired: '暂存已到期，请重新确认共享',
    manifest_conflict: '分片或源记录与已确认清单不匹配',
    quota_exceeded: '录制超过平台配额',
    scope_changed: '应用配置已更新，请重新连接并选择应用',
    account_changed: '账号已切换，请重新连接',
    message_conflict: '同一问题的提交内容已改变',
    conversation_scope_changed:'该会话属于其他车间，请在当前页新建对话',
    application_unavailable: '应用暂时不可用，请稍后重试。如果持续出现，请管理员检查应用配置和 Agent Runtime 的就绪状态。',
  };
  return e instanceof PlatformError
    ? (messages[e.code] ?? '平台请求失败（' + e.status + '）')
    : e instanceof Error
      ? e.message
      : '平台连接失败';
}

export interface AgentTimeline {
  clear(): void;
  follow(job: string, platform: Platform, signal: AbortSignal): void;
  questions(rows: {job_id: string; question: string; asked_at?: string}[], prepend: boolean): void;
}

export function setupAgentPanel(timeline?: AgentTimeline, frameTicket?: string, onEnvironments?: (catalog: EnvironmentCatalog | null) => void, onWorkshop?: (client: WorkshopClient | null) => void) {
  const input = el<HTMLInputElement>('agent-origin'),
    applications = el<HTMLSelectElement>('agent-app');
  const question = el<HTMLTextAreaElement>('agent-question'),
    send = el<HTMLButtonElement>('agent-send');
  const status = el('agent-status'),
    output = el('agent-answers'),
    older = el<HTMLButtonElement>('agent-history'),
    login = el<HTMLButtonElement>('agent-login');
  let platform: Platform | undefined,
    selection: AbortController | undefined,
    app: App | undefined;
  let catalog: App[] = [],
    storageKey = '',
    account = '',
    history: Chat = { conversation: '', jobs: [], awaiting: [] };
  let pending: MessageRef | undefined, originalQuestion: string | undefined;
  let streams = new AbortController();
  const recordingBox = el<HTMLFieldSetElement>('agent-recording'),
    choices = el<HTMLSelectElement>('agent-record-choice');
  const preview = el<HTMLButtonElement>('agent-record-preview'),
    share = el<HTMLButtonElement>('agent-record-share'),
    clear = el<HTMLButtonElement>('agent-record-clear');
  const sample = el('agent-record-sample'),
    recordingStatus = el('agent-record-status');
  const connection = el<HTMLDetailsElement>('agent-connection');
  const evidence = el<HTMLButtonElement>('agent-evidence-toggle');
  const drawer = el('agent-record-drawer');
  function showEvidence(open: boolean) {
    drawer.hidden = !open;
    evidence.setAttribute('aria-expanded', String(open));
  }
  evidence.onclick = () => showEvidence(Boolean(drawer.hidden));
  question.onkeydown = event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      send.click();
    }
  };
  connection.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      connection.open = false;
      connection.querySelector('summary')?.focus();
    }
  });
  document.addEventListener('pointerdown', event => {
    if (connection.open && !connection.contains(event.target as Node)) connection.open = false;
  });
  const jumpToEnd = el<HTMLButtonElement>('agent-scroll-end');
  let atEnd = true;
  function updateScroll() {
    if (!output.clientHeight) {
      jumpToEnd.hidden = true;
      return;
    }
    atEnd = output.scrollHeight - output.clientHeight - output.scrollTop < 48;
    jumpToEnd.hidden = atEnd;
  }
  output.addEventListener('scroll', updateScroll, {passive:true});
  jumpToEnd.onclick = () => {
    output.scrollTop = output.scrollHeight;
    updateScroll();
  };
  new ResizeObserver(updateScroll).observe(output);
  if (!timeline) {
    new MutationObserver(() => {
      if (atEnd) output.scrollTop = output.scrollHeight;
      updateScroll();
    }).observe(output, {childList:true, subtree:true});
  }
  const db = new EvidenceDB();
  let projection: Awaited<ReturnType<typeof prepareRecording>> | undefined;
  let binding: string | null | undefined;
  const historyPage = document.getElementById('conversations') ? new ConversationHistory(async (application, id) => {
    if (!platform || !catalog.some(entry => entry.id === application)) return;
    if (pending) throw new Error('请等待当前消息确认后再切换会话。');
    const p = platform;
    const key = JSON.stringify(['agent-chat', p.origin, account, application]);
    const saved = id === undefined ? undefined : await chooseConversation(key, id);
    p.signal.throwIfAborted();
    applications.value = application;
    await selectApp(saved);
  }, async before => {
    if (platform && selection) await loadPage(platform, selection.signal, before, true);
  }) : undefined;
  if (historyPage) {
    const feedback = el('conversation-feedback');
    new MutationObserver(() => {
      feedback.textContent = status.textContent === '已连接' ? '' : status.textContent;
    }).observe(status, {childList:true, subtree:true});
  }
  let before: string | null = null;
  let unavailableRecording: string | null = null;
  let projecting: AbortController | undefined;
  function resetRecording() {
    projecting?.abort();
    showEvidence(false);
    before = null;
    older.hidden = true;
    older.disabled = false;
    unavailableRecording = null;
    projection = undefined;
    binding = undefined;
    share.hidden = true;
    share.disabled = false;
    preview.disabled = false;
    clear.hidden = true;
    choices.disabled = false;
    choices.replaceChildren();
    sample.hidden = true;
    sample.textContent = '';
    recordingStatus.textContent = '';
    recordingBox.hidden = true;
  }
  function showBinding() {
    const selected =
      binding === undefined
        ? history.recordingScope === app?.scope_ref
          ? history.recording
          : null
        : binding;
    clear.hidden = !selected;
    let label = '录制';
    if (selected) label = selected === unavailableRecording ? '录制已失效' : '已关联录制';
    el('agent-evidence-label').textContent = label;
    recordingStatus.textContent = selected
      ? '当前录制 ' +
        selected +
        (selected === unavailableRecording
          ? ' 已不可查询，请解除或重新选择录制。'
          : '，可在本会话连续提问。')
      : '当前为纯文字提问';
  }
  async function listRecordings(signal: AbortSignal) {
    const list = (await db.listRecordings()).filter(
      (r) => terminal(r.state) && r.saveState === 'saved',
    ).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
    signal.throwIfAborted();
    const previous = choices.value;
    choices.replaceChildren(
      new Option('选择已封存的录制', ''),
      ...list.map((r) => new Option(recordingLabel(r), r.recordingId)),
    );
    if (previous && list.some(r => r.recordingId === previous)) choices.value = previous;
    else if (previous) choices.dispatchEvent(new Event('change'));
    recordingBox.hidden = false;
    showBinding();
  }
  if (!frameTicket) window.addEventListener('hashchange', () => {
    if (!['#assistant', '#conversations'].includes(location.hash) || !app || !selection || recordingBox.hidden) return;
    const signal = selection.signal;
    void listRecordings(signal).catch(e => { if (!signal.aborted) recordingStatus.textContent = explain(e); });
  });
  choices.onchange = () => {
    projecting?.abort();
    projection = undefined;
    share.hidden = true;
    preview.disabled = false;
    sample.hidden = true;
    sample.textContent = '';
    showBinding();
  };
  clear.onclick = () => {
    if (frameTicket && binding) {
      void selectApp().catch(e => { status.textContent = explain(e); });
      return;
    }
    binding = null;
    showBinding();
  };
  preview.onclick = async () => {
    const p = platform,
      owner = selection,
      current = app;
    if (!p || !current || !owner || !choices.value) return;
    projecting?.abort();
    projecting = new AbortController();
    const signal = AbortSignal.any([owner.signal, projecting.signal]);
    projection = undefined;
    share.hidden = true;
    preview.disabled = true;
    try {
      const r = await db.getRecording(choices.value);
      if (!r) throw new Error('本地录制已删除');
      const result = await prepareRecording(db, r, p.origin, signal);
      signal.throwIfAborted();
      projection = result;
      const { coverage, parts } = result.manifest;
      const total = parts.reduce((v, x) => v + x.uncompressed_bytes, 0);
      recordingStatus.textContent =
        '请求 ' +
        coverage.requests.shareable +
        '/' +
        coverage.requests.saved +
        '，操作 ' +
        coverage.actions.shareable +
        '/' +
        coverage.actions.saved +
        '，排除平台流量 ' +
        (coverage.requests.platform_excluded +
          coverage.actions.platform_excluded) +
        ' 条，采集缺口 ' +
        coverage.gaps.reduce((sum, g) => sum + g.count, 0) +
        ' 项，待传 ' +
        total +
        ' 字节（压缩前）。';
      sample.textContent = result.samples.join('\n');
      sample.hidden = !result.samples.length;
      share.hidden = false;
    } catch (e) {
      if (!signal.aborted) recordingStatus.textContent = explain(e);
    } finally {
      if (!signal.aborted) preview.disabled = false;
    }
  };
  share.onclick = async () => {
    const prepared = projection,
      p = platform,
      current = app,
      owner = selection;
    if (!prepared || !p || !current || !owner || share.disabled) return;
    const signal = owner.signal,
      m = prepared.manifest;
    const key = JSON.stringify([
      'agent-upload',
      p.origin,
      account,
      current.id,
      current.scope_ref,
      m.local_recording_id,
      m.checkpoint,
      m.projection_version,
    ]);
    share.disabled = true;
    choices.disabled = true;
    preview.disabled = true;
    try {
      await navigator.locks.request(key, { signal }, async () => {
        const previous = (await chrome.storage.local.get(key))[key] as
          { attempt: string; manifest: typeof m } | undefined;
        if (
          previous &&
          canonicalManifest(previous.manifest) !== canonicalManifest(m)
        )
          throw new Error('当前投影与原清单不一致，请检查本地录制');
        const attempt = previous?.attempt ?? crypto.randomUUID();
        await chrome.storage.local.set({ [key]: { attempt, manifest: m } });
        signal.throwIfAborted();
        let rid: string;
        try {
          rid = await uploadRecording(
            prepared,
            current.id,
            current.scope_ref,
            attempt,
            p.request.bind(p),
            signal,
            (text) => {
              if (!signal.aborted) recordingStatus.textContent = text;
            },
          );
        } catch (e) {
          if (e instanceof PlatformError && e.code === 'upload_expired') {
            await chrome.storage.local.remove(key);
            throw new Error('暂存已到期，请重新确认共享以开始新上传');
          }
          throw e;
        }
        await chrome.storage.local.set({
          [key]: { attempt, manifest: m, recording_id: rid },
        });
        signal.throwIfAborted();
        if (frameTicket) {
          const draft = question.value;
          await selectApp(undefined, rid);
          if (!question.value) question.value = draft;
          return;
        }
        binding = rid;
        share.hidden = true;
        showBinding();
      });
    } catch (e) {
      if (!signal.aborted) recordingStatus.textContent = explain(e);
    } finally {
      if (!signal.aborted) {
        share.disabled = false;
        choices.disabled = false;
        preview.disabled = false;
      }
    }
  };
  let generation = 0;
  function reset() {
    el('agent-http-note').hidden = !/^http:\/\//i.test(input.value.trim());
    login.disabled = false;
    resetRecording();
    historyPage?.connect(undefined, []);
    generation++;
    streams.abort();
    platform?.controller.abort();
    selection?.abort();
    platform = undefined;
    account = '';
    app = undefined;
    pending = undefined;
    catalog = [];
    onWorkshop?.(null);
    el('agent-workshop').hidden = true;
    onEnvironments?.(null);
    originalQuestion = undefined;
    history = { conversation: '', jobs: [], awaiting: [] };
    applications.replaceChildren();
    if (timeline) timeline.clear(); else output.replaceChildren();
    send.disabled = true;
    question.value = '';
    status.textContent = '';
  }
  function follow(job: string, p: Platform, signal: AbortSignal) {
    const existing = Array.from(output.querySelectorAll('article')).find(
      (a) => a.dataset.job === job,
    );
    if (existing) return existing;
    const article = document.createElement('article'),
      state = document.createElement('small'),
      body = document.createElement('div');
    const retry = document.createElement('button');
    retry.textContent = '继续接收';
    retry.hidden = true;
    body.className = 'agent-markdown';
    article.dataset.job = job;
    const reply = document.createElement('section');
    reply.className = 'chat-reply';
    reply.setAttribute('aria-label', 'Agent 回复');
    const byline = document.createElement('div');
    byline.className = 'reply-byline';
    const duration = document.createElement('small');
    duration.className = 'reply-duration';
    byline.append('Agent', state, duration);
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'reply-copy';
    copy.title = '复制回复';
    copy.setAttribute('aria-label', '复制回复');
    copy.setAttribute('aria-live', 'polite');
    copy.hidden = true;
    const activity = new ActivityView();
    reply.append(byline, activity.element, body, copy, retry);
    article.append(reply);
    output.append(article);
    const run = async () => {
      retry.hidden = true;
      const updates = followActivity(job, p.request.bind(p), signal, (data, live) => activity.update(data, live));
      try {
        const source = await displayAnswer(job, p.request.bind(p), body, state, signal, (done, timing) => {
          updates.observe(done);
          if (timing?.time) {
            reply.dataset.messageTime = timing.time;
            reply.title = '回答时间 ' + timing.time;
          }
          duration.textContent = timing?.duration ? '· 用时 ' + timing.duration : '';
        });
        if (!signal.aborted && source.trim()) {
          reply.dataset.complete = 'true';
          copy.onclick = () => void copyReply(copy, source);
          copy.hidden = false;
        }
      } catch (e) {
        if (signal.aborted) return;
        updates.stop();
        activity.clear();
        state.textContent = explain(e);
        if (e instanceof PlatformError && [401, 403, 404].includes(e.status))
          article.querySelector('.agent-question')?.remove();
        if (e instanceof PlatformError && [401, 403, 404].includes(e.status))
          body.replaceChildren();
        retry.hidden =
          e instanceof PlatformError && [403, 404].includes(e.status);
      }
    };
    retry.onclick = () => void run();
    void run();
    return article;
  }
  function show(chat: Chat, p: Platform, signal: AbortSignal) {
    signal.throwIfAborted();
    if (history.conversation !== chat.conversation) {
      before = null;
      older.hidden = true;
      streams.abort();
      streams = new AbortController();
      if (timeline) timeline.clear(); else output.replaceChildren();
      history.jobs = [];
    }
    for (const job of chat.jobs) {
      if (history.jobs.includes(job)) continue;
      const streamSignal = AbortSignal.any([signal, streams.signal]);
      if (timeline) timeline.follow(job, p, streamSignal);
      else follow(job, p, streamSignal);
    }
    history = chat;
    historyPage?.current(app?.id ?? '', chat.conversation);
    if (!recordingBox.hidden) showBinding();
  }

  async function loadPage(p: Platform, signal: AbortSignal, cursor?: string, jump = false) {
    const conversation = history.conversation;
    if (!conversation) return;
    const page = await (
      await p.request(
        '/conversations/' +
          encodeURIComponent(conversation) +
          ((cursor || jump) ? '?limit=20' + (cursor ? '&before=' + encodeURIComponent(cursor) : '') : ''),
        { signal },
      )
    ).json();
    signal.throwIfAborted();
    if (
      history.conversation !== conversation ||
      page.conversation_id !== conversation
    )
      return;
    if (timeline) {
      for (const row of page.jobs) timeline.follow(row.job_id, p, AbortSignal.any([signal, streams.signal]));
      timeline.questions(page.jobs, Boolean(cursor));
    } else {
      const fragment = document.createDocumentFragment();
      for (const row of page.jobs) {
        const article = follow(
          row.job_id,
          p,
          AbortSignal.any([signal, streams.signal]),
        );
        let label = article.querySelector<HTMLElement>('.agent-question');
        if (!label) {
          label = document.createElement('p');
          label.className = 'agent-question chat-question';
          label.setAttribute('aria-label', '你发送的消息');
          article.prepend(label);
        }
        label.textContent = row.question;
        const time = messageTime(row.asked_at);
        if (time) {
          label.dataset.messageTime = time;
          label.title = '提问时间 ' + time;
          label.tabIndex = 0;
        }
        fragment.append(article);
      }
      if (cursor) output.prepend(fragment);
      else output.append(fragment);
    }
    historyPage?.pageLoaded(page.jobs, cursor);
    historyPage?.arrange();
    if (!jump) { before = page.next_before; older.hidden = !before; }
    unavailableRecording =
      page.recording_state === 'unavailable' ? page.recording_id : null;
    if (!cursor && app) {
      history.recording = page.recording_id;
      history.recordingScope = app.scope_ref;
    }
    if (!recordingBox.hidden) showBinding();
  }
  older.onclick = async () => {
    const p = platform,
      signal = selection?.signal;
    if (!before || !p || !signal) return;
    older.disabled = true;
    try {
      await loadPage(p, signal, before);
    } catch (e) {
      if (!signal.aborted) status.textContent = explain(e);
    } finally {
      if (!signal.aborted) older.disabled = false;
    }
  };

  async function lookup(
    p: Platform,
    path: string,
    ref: MessageRef,
    signal: AbortSignal,
  ): Promise<Receipt | undefined> {
    try {
      const res = await p.request(path + '/' + encodeURIComponent(ref.key), {
        signal,
      });
      return await res.json();
    } catch (e) {
      if (
        e instanceof PlatformError &&
        e.status === 404 &&
        e.code === 'not_found'
      )
        return;
      throw e;
    }
  }

  async function selectApp(chosen?: Chat, explicitRecording?: string) {
    resetRecording();
    binding = explicitRecording;
    selection?.abort();
    selection = new AbortController();
    const signal = selection.signal;
    pending = undefined;
    originalQuestion = undefined;
    streams.abort();
    streams = new AbortController();
    history = { conversation: '', jobs: [], awaiting: [] };
    if (timeline) timeline.clear(); else output.replaceChildren();
    before = null;
    older.hidden = true;
    send.disabled = true;
    question.value = '';
    const p = platform;
    app = catalog.find((a) => a.id === applications.value);
    historyPage?.current(app?.id ?? '', '');
    if (!p || !app) return;
    const current = app;
    const currentWorkshop=await showWorkshop(p,current,signal);
    signal.throwIfAborted();
    publishEnvironments(p, catalog);
    const key=chatKey(p,current,currentWorkshop,explicitRecording);
    storageKey = key;
    await chrome.storage.local.set({
      [JSON.stringify(['agent-app', p.origin, account])]: current.id,
    });
    const saved = chosen ?? await loadChat(key);
    signal.throwIfAborted();
    show(saved, p, signal);
    const path =
      '/applications/' + encodeURIComponent(current.id) + '/messages';
    for (const ref of saved.awaiting) {
      const receipt = await lookup(p, path, ref, signal);
      signal.throwIfAborted();
      if (receipt) show(await finishMessage(key, ref, receipt), p, signal);
      else if (!pending) pending = ref;
    }
    signal.throwIfAborted();
    await loadPage(p, signal);
    await listRecordings(signal);
    // An absent receipt may still be in flight. Check again on the next click.
    if (pending)
      status.textContent =
        '上一条问题的回执尚未确认。请重新输入原问题，点击发送时会先核对回执。';
    send.disabled = false;
  }
  applications.onchange = () =>
    void selectApp().catch((e) => {
      if (!(e instanceof DOMException && e.name === 'AbortError'))
        status.textContent = explain(e);
    });
  input.oninput = reset;
  function workshopClient(p: Platform, selected: App, signal: AbortSignal): WorkshopClient {
    const path = '/applications/' + encodeURIComponent(selected.id) + '/workshop-bindings';
    const headers = {'X-Application-Scope': selected.scope_ref, 'Content-Type': 'application/json'};
    return {
      destination:{origin:p.origin, account, app:selected.id, scopeRef:selected.scope_ref},
      key: JSON.stringify(['workshop-bindings', p.origin, account, selected.id]),
      name: selected.name, choices: selected.workshop_scopes ?? [],
      list: async () => (await p.request(path, {headers, signal})).json(),
      save: async (rule, scope, revision) => (await p.request(path, {method:'PUT', headers, signal,
        body:JSON.stringify({rule, environment_id:scope.environment_id, base_id:scope.base_id,
          workshop_id:scope.workshop_id, expected_revision:revision})})).json(),
      revoke: async b => { await p.request(path + '/' + encodeURIComponent(b.id) + '?expected_revision=' + b.revision,
        {method:'DELETE', headers, signal}); },
    };
  }
  function chatKey(p:Platform,current:App,bound?:WorkshopBinding,explicitRecording?:string) {
    const parts=['agent-chat',p.origin,account,current.id];
    if (frameTicket) parts.push(bound?.workshop_id ?? 'unbound-page');
    if (explicitRecording) parts.push('recording',explicitRecording);
    return JSON.stringify(parts);
  }
  let availableBindings: WorkshopBinding[] | undefined;
  let displayedBinding: WorkshopBinding | undefined;
  let workshopRequest = 0;
  async function showWorkshop(p: Platform, current: App, signal: AbortSignal) {
    const request = ++workshopRequest;
    const label = el('agent-workshop');
    const client = current.workshop_scopes ? workshopClient(p, current, signal) : null;
    await onWorkshop?.(client);
    if (!frameTicket) return;
    availableBindings = undefined;
    displayedBinding = undefined;
    if (!client) {
      availableBindings = [];
      return;
    }
    label.hidden = false;
    label.textContent = '正在核对页面车间';
    try {
      const bindings = await client.list();
      const result = await chrome.runtime.sendMessage({type:'float.workshop', ticket:frameTicket, bindings,destination:client.destination});
      signal.throwIfAborted();
      if (request !== workshopRequest) throw new DOMException('车间已重新核对', 'AbortError');
      if (!result?.ok) throw new Error('发送页已变化');
      availableBindings=bindings;
      displayedBinding=result.binding;
      const scope = client.choices.find(s => s.workshop_id === result?.binding?.workshop_id);
      label.textContent = (scope ? workshopLabel(scope) : '该页面尚未绑定车间') +
        (result?.captureState === 'paused' ? ' · 页面采集已暂停，请刷新或重新打开' : '');
      return result.binding as WorkshopBinding|undefined;
    } catch (error) {
      if (signal.aborted || request !== workshopRequest) throw error;
      label.textContent='页面车间暂不可用';
      throw new Error('未能核对发送页的车间，请重新连接后再发送');
    }
  }
  if (frameTicket) {
    const update = () => {
      const p=platform,current=app,signal=selection?.signal;
      if (p && current && signal && !signal.aborted) void showWorkshop(p,current,signal).then(bound=>{
        if (!signal.aborted && storageKey!==chatKey(p,current,bound,binding || undefined)) return selectApp();
      }).catch(()=>{});
    };
    chrome.runtime.onMessage.addListener(message => { if (message.type === 'float.pageChanged') update(); });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === 'local' && Object.keys(changes).some(key => key.startsWith('["workshop-bindings",'))) update();
    });
  }
  function publishEnvironments(p: Platform, apps: App[]) {
    const options = new Map(apps.flatMap(a => (a.environments ?? []).map(e => [e.code, e] as const)));
    onEnvironments?.({
      scope: JSON.stringify([p.origin, account]),
      options: [...options.values()].sort((a, b) => a.code.localeCompare(b.code)),
    });
  }
  async function connect(interactive: boolean) {
    reset();
    const started = generation;
    login.disabled = true;
    try {
      const url = new URL(input.value.trim());
      if (
        !['https:', 'http:'].includes(url.protocol) ||
        url.username ||
        url.password
      )
        throw new Error('请填写以 http:// 或 https:// 开头的系统网址');
      input.value = url.origin;
      const hosts = { origins: [url.protocol + '//' + url.hostname + '/*'] };
      const allowed = interactive && !frameTicket
        ? await chrome.permissions.request(hosts)
        : await chrome.permissions.contains(hosts);
      if (generation !== started) return;
      if (!allowed) throw new Error('未获得平台访问权限');
      const excluded = await chrome.runtime.sendMessage({
        type: 'agent.exclude_origin',
        ...(frameTicket ? {ticket: frameTicket} : {}),
        origin: url.origin,
      });
      if (!excluded?.ok) throw new Error('无法排除平台登录流量');
      if (generation !== started) return;
      const p = new Platform(url.origin);
      platform = p;
      p.signal.addEventListener(
        'abort',
        () => {
          if (generation === started) {
            resetRecording();
            selection?.abort();
            if (timeline) timeline.clear(); else output.replaceChildren();
            applications.replaceChildren();
            send.disabled = true;
            question.value = '';
            historyPage?.connect(undefined, []);
            onWorkshop?.(null);
            el('agent-workshop').hidden = true;
            onEnvironments?.(null);
            status.textContent = '账号已变更，请重新登录';
          }
        },
        { once: true },
      );
      const identity = await p.login(interactive);
      const apps: App[] = await (await p.request('/applications', {})).json();
      p.signal.throwIfAborted();
      account = JSON.stringify([identity.tenant_id, identity.user_id]);
      catalog = apps;
      connection.open = false;
      historyPage?.connect(p, apps);
      await chrome.storage.local.set({ agentOrigin: url.origin, agentActiveAccount: account });
      p.signal.throwIfAborted();
      applications.replaceChildren(
        ...catalog.map((a) => new Option(a.name, a.id)),
      );
      status.textContent = catalog.length
        ? '已连接'
        : '当前账号没有可用应用。应用须已启用浏览器插件入口，并授权给你。';
      const choice = (
        await chrome.storage.local.get(
          JSON.stringify(['agent-app', url.origin, account]),
        )
      )[JSON.stringify(['agent-app', url.origin, account])];
      p.signal.throwIfAborted();
      if (typeof choice === 'string' && catalog.some((a) => a.id === choice))
        applications.value = choice;
      await selectApp();
    } catch (e) {
      if (generation === started) {
        connection.open = true;
        status.textContent = explain(e);
      }
    } finally {
      if (generation === started) login.disabled = false;
    }
  }
  login.onclick = () => void connect(true);
  if (frameTicket) chrome.storage.onChanged.addListener((changes, area) => {
    const changed = changes.agentOrigin;
    if (area !== 'local' || !changed || changed.newValue === input.value) return;
    input.value = typeof changed.newValue === 'string' ? changed.newValue : '';
    if (input.value) void connect(false); else reset();
  });
  void chrome.storage.local.get('agentOrigin').then((v) => {
    if (!input.value && typeof v.agentOrigin === 'string') {
      input.value = v.agentOrigin;
      void connect(false);
    }
  });
  send.onclick = async () => {
    const p = platform,
      current = app,
      signal = selection?.signal,
      value = question.value;
    if (!p || !current || !signal || !value.trim() || send.disabled) return;
    send.disabled = true;
    const key = storageKey;
    const path =
      '/applications/' + encodeURIComponent(current.id) + '/messages';
    const ref:MessageRef = pending ?? {
      key: crypto.randomUUID(),
      conversation: history.conversation,
      scope: current.scope_ref,
      ...(binding !== undefined ? { recording: binding } : {}),
    };
    let submitting = false;
    try {
      if (frameTicket && !pending && binding==null) {
        if (!availableBindings) throw new Error('请等待当前页面的车间核对完成');
        const resolved=await chrome.runtime.sendMessage({type:'float.workshop',ticket:frameTicket,
          destination:workshopClient(p,current,signal).destination,bindings:availableBindings});
        if (!resolved?.ok || resolved.binding?.id !== displayedBinding?.id ||
            resolved.binding?.revision !== displayedBinding?.revision || chatKey(p,current,resolved.binding)!==key)
          throw new Error('发送页已变化，请核对当前车间后再发送');
        if (resolved.page) ref.page=resolved.page;
        ref.recording=null;
      }
      if (pending) {
        const receipt = await lookup(p, path, ref, signal);
        if (receipt) {
          if (!frameTicket && binding === ref.recording) binding = undefined;
          show(await finishMessage(key, ref, receipt), p, signal);
          if (value === originalQuestion) question.value = '';
          originalQuestion = undefined;
          pending = history.awaiting[0];
          status.textContent = '已恢复上一条问题的回答。';
          void historyPage?.refresh();
          await loadPage(p, signal);
          return;
        }
        if (ref.scope !== current.scope_ref) {
          show(await finishMessage(key, ref), p, signal);
          originalQuestion = undefined;
          pending = history.awaiting[0];
          status.textContent =
            '原应用范围已变更。请确认当前应用，再次点击发送。';
          return;
        }
        if (originalQuestion !== undefined && originalQuestion !== value) {
          status.textContent = '回执尚未确认，请恢复原问题后再发送。';
          return;
        }
      }
      pending = ref;
      originalQuestion = value;
      await rememberMessage(key, ref);
      signal.throwIfAborted();
      submitting = true;
      const result = await p.request(path, {
        method: 'POST',
        signal,
        headers: {
          'Content-Type': 'application/json',
          'X-Application-Scope': ref.scope,
        },
        body: JSON.stringify({
          question: value,
          client_message_id: ref.key,
          ...(ref.page ? {page:ref.page}:{}),
          ...(ref.conversation ? { conversation_id: ref.conversation } : {}),
          ...(ref.recording !== undefined
            ? { recording_id: ref.recording }
            : {}),
        }),
      });
      submitting = false;
      const receipt: Receipt = await result.json();
      signal.throwIfAborted();
      if (!frameTicket && binding === ref.recording) binding = undefined;
      show(await finishMessage(key, ref, receipt), p, signal);
      pending = history.awaiting[0];
      originalQuestion = undefined;
      if (question.value === value) question.value = '';
      status.textContent = '已连接';
      void historyPage?.refresh();
      await loadPage(p, signal);
    } catch (e) {
      if (signal.aborted) return;
      const admissionRejected = submitting && e instanceof PlatformError &&
        e.status === 409 && e.code === 'application_unavailable';
      if (
        e instanceof PlatformError &&
        ([403, 404, 410, 422].includes(e.status) ||
          admissionRejected ||
          ['scope_changed', 'message_conflict', 'conversation_scope_changed'].includes(e.code))
      ) {
        if (e.status === 410)
          unavailableRecording = ref.recording ?? history.recording ?? null;
        show(await finishMessage(key, ref), p, signal);
        pending = history.awaiting[0];
        originalQuestion = undefined;
      }
      status.textContent = admissionRejected
        ? '应用暂时无法接收问题。本次未创建任务，问题已保留，可稍后重发。如果持续出现，请管理员检查应用配置和 Agent Runtime 的就绪状态。'
        : explain(e);
    } finally {
      if (!signal.aborted) send.disabled = false;
    }
  };
  window.addEventListener(
    'pagehide',
    () => {
      selection?.abort();
      platform?.controller.abort();
    },
    { once: true },
  );
  return async function refreshEnvironments() {
    const p = platform;
    if (!p || !account || !onEnvironments) return;
    try {
      const apps: App[] = await (await p.request('/applications', {})).json();
      p.signal.throwIfAborted();
      const selected = apps.find(candidate => candidate.id === app?.id);
      if (selected && selection) {
        publishEnvironments(p, apps);
        await showWorkshop(p, selected, selection.signal);
      }
    } catch (error) {
      if (p === platform) onEnvironments(null);
      throw error;
    }
  };
}
