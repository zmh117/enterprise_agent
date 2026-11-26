import {
  observePage,
  projectPageEvent,
  sourceOf,
  matchesPage,
  keepsDocumentBinding,
  type QuestionPage,
  type LiveDocument,
} from '../../shared/live-page';
import { bytes } from '../../shared/contracts';
import { platformTraffic } from '../../shared/platform-traffic';
import type { WorkshopBinding } from '../../shared/workshop';
import type { Policy } from '../../shared/contracts';
import { Platform } from '../platform';
import { LiveDelivery } from './live-delivery';
import { LiveDB, result } from '../storage/live-evidence';
import { LiveNetwork, type NetworkPolicy } from './live-network';
import {
  recoverLiveRequests,
  saveLiveEvidence,
  type LiveDestination,
} from '../storage/live-evidence';
import { hostPattern, sites } from './float-sites';

interface LiveTab {
  id: string;
  browserId: number;
  doc?: LiveDocument;
  ticket?: string;
  baselineId?: string;
  error?: string;
  networkGap?: string;
  paused: string[];
}
interface Run {
  id: string;
  destination: LiveDestination;
  rules: WorkshopBinding[];
  tabs: LiveTab[];
  maxBytes: number;
  origins: string[];
  maxTabs: number;
  networkPolicy: NetworkPolicy;
}
const stateKey = 'liveWorkshopCapture';
export class LiveCapture {
  private run?: Run;
  private platform?: Platform;
  private network?: LiveNetwork;
  private db = new LiveDB();
  private delivery = new LiveDelivery(this.db, (d, path, body) => this.request(d, path, body));
  private timer?: ReturnType<typeof setTimeout>;
  private platformAccount?: string;
  private writing: Promise<void> = Promise.resolve();
  private pendingBytes = 0;
  private saving: Promise<void> = Promise.resolve();
  private rulesGeneration = 0;
  readonly ready: Promise<void>;
  constructor() {
    this.ready = chrome.storage.session.get(stateKey).then(async (value) => {
      const run = (this.run = value[stateKey] as Run | undefined);
      if (!run) return;
      this.setupNetwork(run);
      await recoverLiveRequests(this.db, run.id, run.destination, run.maxBytes).catch(() => {
        for (const t of run.tabs) this.fence(t, '存储恢复失败，请检查本地空间');
      });
      await Promise.all(
        run.tabs.filter((t) => t.ticket).map((t) => this.network?.attach(t.browserId, true)),
      );
      await this.save();
    });
  }
  async deliver() {
    const saved = await chrome.storage.local.get(['agentOrigin', 'agentActiveAccount']);
    if (typeof saved.agentOrigin === 'string' && typeof saved.agentActiveAccount === 'string')
      if (
        await this.delivery.flush({ origin: saved.agentOrigin, account: saved.agentActiveAccount })
      )
        this.notifyDelivery();
  }
  private notifyDelivery() {
    this.timer ??= setTimeout(() => {
      this.timer = undefined;
      void this.deliver().catch(() => {});
    }, 250);
  }
  get active() {
    return !!this.run;
  }
  private save() {
    const snapshot = this.run && structuredClone(this.run);
    const write = () =>
      snapshot
        ? chrome.storage.session.set({ [stateKey]: snapshot })
        : chrome.storage.session.remove(stateKey);
    return (this.saving = this.saving.then(write, write));
  }
  private setupNetwork(run: Run) {
    this.network = new LiveNetwork(
      run.networkPolicy,
      (id, ticket, url) => {
        const t = run.tabs.find((t) => t.browserId === id);
        if (
          this.run !== run ||
          !t ||
          t.ticket !== ticket ||
          t.doc?.state !== 'ready' ||
          !t.doc.binding ||
          !matchesPage(url, t.doc.binding, run.rules, run.destination.origin)
        )
          return;
        return sourceOf(t.id, t.doc);
      },
      (id, source, event, at) => {
        const t = run.tabs.find((t) => t.browserId === id);
        if (!t) return;
        const size = bytes(event);
        if (this.pendingBytes + size > run.networkPolicy.budgets.queueBytes) {
          this.fence(t, '本地写入队列已满，存在采集缺口');
          void this.save();
          return;
        }
        this.pendingBytes += size;
        this.writing = this.writing
          .then(() =>
            saveLiveEvidence(this.db, run.id, run.destination, source, event, run.maxBytes, at),
          )
          .catch(() => {
            this.fence(t, '网络证据保存失败，存在采集缺口');
            void this.save();
          })
          .finally(() => {
            this.pendingBytes -= size;
            this.notifyDelivery();
          });
      },
      (id, reason) => {
        const t = run.tabs.find((t) => t.browserId === id);
        if (t) {
          t.networkGap = reason;
          void this.save();
        }
      },
    );
  }
  debugEvent(sender: chrome.debugger.Debuggee, method: string, p: object) {
    this.network?.event(sender, method, p);
  }
  detached(id: number, reason: string) {
    const t = this.run?.tabs.find((t) => t.browserId === id);
    if (t && !t.networkGap) {
      t.networkGap = reason === 'canceled_by_user' ? '浏览器取消了调试连接' : '浏览器目标已断开';
      void this.save();
    }
    return this.network?.stop(id, true);
  }
  private async client(d: LiveDestination) {
    const saved = await chrome.storage.local.get(['agentOrigin', 'agentActiveAccount']);
    if (
      saved.agentOrigin !== d.origin ||
      saved.agentActiveAccount !== d.account ||
      !(await chrome.permissions.contains({ origins: [hostPattern(d.origin)] }))
    )
      throw new Error('请重新连接原采集账号');
    if (
      !this.platform ||
      this.platformAccount !== d.account ||
      this.platform.origin !== d.origin ||
      this.platform.signal.aborted
    ) {
      const candidate = new Platform(d.origin);
      const identity = await candidate.login(false);
      if (JSON.stringify([identity.tenant_id, identity.user_id]) !== d.account)
        throw new Error('采集账号已切换');
      this.platform = candidate;
      this.platformAccount = d.account;
    }
    return this.platform;
  }
  private async request(d: LiveDestination, suffix: string, body?: unknown) {
    const client = await this.client(d);
    return (
      await client.request('/applications/' + encodeURIComponent(d.app) + suffix, {
        method: body ? 'POST' : 'GET',
        headers: { 'X-Application-Scope': d.scopeRef, 'Content-Type': 'application/json' },
        ...(body ? { body: JSON.stringify(body) } : {}),
      })
    ).json();
  }
  async start(ids: number[], d: LiveDestination, policy: Policy) {
    const maxBytes = policy.budgets.hardBytes;
    if (this.run) throw new Error('已有持续采集');
    if (
      !d?.account ||
      !d.scopeRef ||
      !Array.isArray(ids) ||
      !ids.length ||
      ids.length > policy.budgets.hardTabs ||
      ids.some((id) => !Number.isSafeInteger(id)) ||
      !Number.isInteger(maxBytes) ||
      maxBytes < 1024 * 1024 ||
      maxBytes > 500 * 1024 * 1024
    )
      throw new Error('持续采集设置无效');
    this.platform = undefined;
    const rules: WorkshopBinding[] = await this.request(d, '/workshop-bindings');
    const allowedSites = await sites();
    const tabs: LiveTab[] = [];
    let hasPolicyPage = false;
    let hasPageAccess = false;
    for (const browserId of new Set(ids)) {
      const tab = await chrome.tabs.get(browserId);
      const top = await chrome.webNavigation.getFrame({ tabId: browserId, frameId: 0 });
      if (!top || !tab.url || tab.incognito || platformTraffic(top.url))
        throw new Error('请选择已授权的普通 MES 页面');
      const origin = new URL(top.url).origin;
      const inPolicy = policy.pageOrigins.includes(origin);
      const permitted = inPolicy && await chrome.permissions.contains({ origins: [hostPattern(origin)] });
      hasPolicyPage ||= inPolicy;
      hasPageAccess ||= permitted;
      const allowed = permitted && allowedSites.includes(origin);
      tabs.push({
        id: crypto.randomUUID(),
        browserId,
        paused: [],
        doc: observePage(undefined, top.documentId, top.url, allowed ? rules : [], d.origin),
      });
    }
    const apiRules = await Promise.all(
      policy.apiRules.map(async (r) =>
        !platformTraffic(r.origin) &&
        (await chrome.permissions.contains({ origins: [hostPattern(r.origin)] }))
          ? r
          : undefined,
      ),
    );
    const networkPolicy: NetworkPolicy = {
      apiRules: apiRules.flatMap((r) => r ?? []),
      requestTypes: policy.requestTypes,
      budgets: policy.budgets,
    };
    const run: Run = {
      networkPolicy,
      id: crypto.randomUUID(),
      destination: d,
      rules,
      tabs,
      maxBytes,
      origins: policy.pageOrigins,
      maxTabs: policy.budgets.hardTabs,
    };
    const pages = tabs.flatMap((t) => sourceOf(t.id, t.doc) ?? []);
    if (!pages.length) {
      if (!hasPolicyPage) throw new Error('采集范围未包含所选页面。请在「采集范围与权限」按所选站点重置。');
      if (!hasPageAccess) throw new Error('Chrome 未授予所选 MES 页面的访问权限。请允许站点访问后重试。');
      throw new Error('所选页面没有可采集的车间。请在「站点设置 → 页面车间」选择环境、基地和车间，点击「允许页面并绑定车间」。');
    }
    // Install the navigation fence before the first round trip for this run.
    this.run = run;
    this.setupNetwork(run);
    try {
      await this.save();
      await this.request(d, '/live-recordings', { recording_id: run.id, pages });
      await Promise.all(tabs.map((t) => this.activate(t)));
      return this.status();
    } catch (error) {
      if (this.run === run) await this.stop();
      throw error;
    }
  }
  async status() {
    const run = this.run;
    if (!run) return;
    const conn = await this.db.open();
    const tx = conn.transaction(['liveEvidence', 'liveRecordings']);
    const progress = tx.objectStore('liveEvidence').index('progress');
    const stats = result<{ released?: number } | undefined>(
      tx.objectStore('liveRecordings').get(run.id),
    );
    const [pending, acknowledged, verified] = await Promise.all(
      ['pending', 'acknowledged', 'verified'].map((state) =>
        result(progress.count([run.id, state])),
      ),
    );
    const confirmed = (verified ?? 0) + ((await stats)?.released ?? 0);
    return (
      this.run === run && {
        pending,
        acknowledged,
        verified: confirmed,
        id: this.run.id,
        tabs: this.run.tabs.map((t) => ({
          tabId: t.browserId,
          state: t.doc?.state,
          error: t.error,
          networkGap: t.networkGap,
          network: this.network?.status(t.browserId),
        })),
      }
    );
  }
  async add(browserId: number) {
    const run = this.run;
    if (!run || !Number.isSafeInteger(browserId) || run.tabs.length >= run.maxTabs)
      throw new Error('无法加入标签');
    if (run.tabs.some((t) => t.browserId === browserId)) return;
    const tab = await chrome.tabs.get(browserId);
    const top = await chrome.webNavigation.getFrame({ tabId: browserId, frameId: 0 });
    if (!top || tab.incognito || platformTraffic(top.url) || !/^https?:/.test(top.url))
      throw new Error('请选择普通 MES 页面');
    await this.refreshRules(run);
    const permitted =
      run.origins.includes(new URL(top.url).origin) &&
      (await sites()).includes(new URL(top.url).origin) &&
      (await chrome.permissions.contains({ origins: [hostPattern(top.url)] }));
    if (run !== this.run || run.tabs.some((t) => t.browserId === browserId)) return;
    const t: LiveTab = {
      browserId,
      id: crypto.randomUUID(),
      paused: [],
      doc: observePage(undefined, top.documentId, top.url, permitted ? run.rules : [], run.destination.origin),
    };
    run.tabs.push(t);
    await this.save();
    await this.activate(t);
  }
  questionPage(
    id: number,
    documentId: string,
    binding: WorkshopBinding,
    d: LiveDestination,
    asked: number,
  ): QuestionPage {
    const run = this.run;
    const tab = run?.tabs.find((t) => t.browserId === id);
    const doc = tab?.doc;
    const registered =
      run &&
      tab &&
      doc?.state === 'ready' &&
      doc.documentId === documentId &&
      doc.binding && keepsDocumentBinding(doc.binding, binding, run.rules) &&
      run.destination.origin === d.origin &&
      run.destination.account === d.account &&
      run.destination.app === d.app &&
      run.destination.scopeRef === d.scopeRef;
    return {
      binding_id: registered ? doc.binding!.id : binding.id,
      revision: registered ? doc.binding!.revision : binding.revision,
      document_id: documentId,
      recording_id: registered ? run.id : null,
      tab_id: registered ? tab.id : null,
      asked_ms: asked,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
  }
  tabState(id: number) {
    return this.run?.tabs.find((t) => t.browserId === id)?.doc?.state;
  }
  async stop() {
    const run = this.run;
    const network = this.network;
    this.network = undefined;
    this.run = undefined;
    await Promise.all((run?.tabs ?? []).map((t) => network?.stop(t.browserId)));
    await this.writing;
    this.platform?.controller.abort();
    this.platform = undefined;
    await this.save();
    await Promise.all((run?.tabs ?? []).map((t) => this.endTicket(t)));
  }
  private endTicket(t: LiveTab) {
    if (!t.ticket) return;
    const ticket = t.ticket;
    t.ticket = undefined;
    return chrome.tabs.sendMessage(t.browserId, { type: 'live.end', ticket }).catch(() => {});
  }
  async navigation(tabId: number, documentId: string, url: string, sameDocument: boolean) {
    const run = this.run,
      t = run?.tabs.find((x) => x.browserId === tabId);
    if (!run || !t) return;
    if (sameDocument && t.doc && t.doc.documentId !== documentId) return;
    let origin: string | undefined;
    try {
      origin = new URL(url).origin;
    } catch {
      /* Browser-internal pages remain unbound. */
    }
    const next = observePage(
      t.doc,
      documentId,
      url,
      origin && run.origins.includes(origin) ? run.rules : [],
      run.destination.origin,
    );
    if (next === t.doc) return;
    void this.endTicket(t);
    t.doc = next;
    t.error = undefined;
    t.baselineId = undefined;
    if (t.paused.includes(documentId)) next.state = 'paused';
    if (next.state === 'paused' && !t.paused.includes(documentId)) t.paused.push(documentId);
    await this.save();
    if (next.state === 'baseline') await this.activate(t);
  }
  private async activate(t: LiveTab) {
    const run = this.run,
      doc = t.doc,
      source = sourceOf(t.id, doc);
    if (!run || !doc?.binding || !source || t.ticket) return;
    const ticket = crypto.randomUUID();
    t.ticket = ticket;
    const current = () => this.run === run && t.ticket === ticket && doc === t.doc;
    try {
      const top = await chrome.webNavigation.getFrame({ tabId: t.browserId, frameId: 0 });
      if (!current()) return;
      if (
        !top ||
        top.documentId !== doc.documentId ||
        !matchesPage(top.url, doc.binding, run.rules, run.destination.origin) ||
        !(await sites()).includes(doc.binding.rule.origin) ||
        !(await chrome.permissions.contains({ origins: [hostPattern(top.url)] }))
      )
        throw new Error('scope_changed');
      await this.request(run.destination, '/live-recordings', {
        recording_id: run.id,
        pages: [source],
      });
      if (!current()) return;
      await this.save();
      await chrome.scripting.executeScript({
        target: { tabId: t.browserId, documentIds: [doc.documentId] },
        files: ['live-recorder.js'],
      });
      if (!current()) return;
      const reply = await chrome.tabs.sendMessage(
        t.browserId,
        { type: 'live.begin', ticket: { id: ticket, binding: doc.binding, platformOrigin: run.destination.origin,
          rules: run.rules.filter(b => b.rule.origin === doc.binding!.rule.origin) } },
        { documentId: doc.documentId },
      );
      if (!reply?.ok) throw new Error('recorder_unavailable');
      if (current()) await this.network?.attach(t.browserId);
    } catch {
      if (current()) {
        this.fence(t, '页面权限、绑定或采集器不可用，请检查后刷新');
        await this.save();
      }
    }
  }
  private fence(t: LiveTab, reason?: string) {
    if (!t.doc) return;
    void this.endTicket(t);
    t.doc.state = 'paused';
    t.error = reason;
    if (!t.paused.includes(t.doc.documentId)) t.paused.push(t.doc.documentId);
  }
  private async refreshRules(run: Run) {
    const turn = ++this.rulesGeneration;
    const rules: WorkshopBinding[] = await this.request(run.destination, '/workshop-bindings');
    if (this.run !== run || turn !== this.rulesGeneration) return;
    run.rules = rules;
    await Promise.all(run.tabs.map(async t => {
      const binding = t.doc?.binding, ticket = t.ticket;
      if (!binding || !ticket) return;
      if (!rules.some(r => r.enabled && r.id === binding.id && r.revision === binding.revision)) {
        this.fence(t);
        return;
      }
      // A newly configured child route can change ownership while the parent grant stays valid.
      await chrome.tabs.sendMessage(t.browserId, {type: 'live.rules', ticket,
        rules: rules.filter(r => r.rule.origin === binding.rule.origin)},
        {documentId: t.doc!.documentId}).catch(() => {});
    }));
    await this.save();
  }
  async changedRules(rules: WorkshopBinding[]) {
    const run = this.run;
    if (!run) return;
    // Local change notifications can invalidate an existing grant. Only the API can grant a new one.
    for (const t of run.tabs) {
      const old = t.doc?.binding;
      if (old && !rules.some((r) => r.enabled && r.id === old.id && r.revision === old.revision))
        this.fence(t);
    }
    const previous = run.rules;
    run.rules = [
      ...previous.map(r => rules.some(n => n.enabled && n.id === r.id && n.revision === r.revision)
        ? r : {...r, enabled: false}),
      ...rules.filter(n => !previous.some(r => r.id === n.id && r.revision === n.revision))
        .map(n => ({...n, enabled: false, reserved_paths: undefined})),
    ];
    await this.save();
    await this.refreshRules(run);
  }
  async settingsChanged(changes: Record<string, chrome.storage.StorageChange>) {
    const r = this.run;
    if (!r) return;
    const d = r.destination;
    if (
      (changes.agentOrigin && changes.agentOrigin.newValue !== d.origin) ||
      (changes.agentActiveAccount && changes.agentActiveAccount.newValue !== d.account)
    ) {
      await this.stop();
      return;
    }
    const key = JSON.stringify(['workshop-bindings', d.origin, d.account, d.app]);
    if (changes[key]) await this.changedRules((changes[key].newValue as WorkshopBinding[]) ?? []);
    if (changes.agentFloatSites) {
      const allowed = await sites();
      for (const t of r.tabs)
        if (t.doc?.binding && !allowed.includes(t.doc.binding.rule.origin)) this.fence(t);
      await this.save();
    }
  }
  async revoked(matches: (url: string) => boolean) {
    if (!this.run) return;
    if (matches(this.run.destination.origin)) {
      await this.stop();
      return;
    }
    const run = this.run;
    const apiRevoked = run.networkPolicy.apiRules.some((r) => matches(r.origin));
    for (const t of run.tabs) {
      if (t.doc?.binding && matches(t.doc.binding.rule.origin)) this.fence(t);
      if (apiRevoked || t.doc?.state === 'paused') {
        await this.network?.stop(t.browserId);
        t.networkGap = '主机权限已撤销';
      }
    }
    run.networkPolicy.apiRules = run.networkPolicy.apiRules.filter((r) => !matches(r.origin));
    await this.save();
  }
  async closed(tabId: number) {
    if (!this.run?.tabs.some((t) => t.browserId === tabId)) return;
    await this.network?.stop(tabId);
    this.run.tabs = this.run.tabs.filter((t) => t.browserId !== tabId);
    await this.save();
  }
  async message(
    sender: chrome.runtime.MessageSender,
    m: { type: string; ticket: string; baselineId?: string; event?: unknown },
  ) {
    const run = this.run,
      t = run?.tabs.find((x) => x.browserId === sender.tab?.id);
    const doc = t?.doc;
    if (
      !run ||
      !t ||
      !doc?.binding ||
      sender.frameId !== 0 ||
      sender.documentId !== doc.documentId ||
      !t.ticket ||
      m.ticket !== t.ticket
    )
      return { ok: false };
    if (m.type === 'live.pause' || m.type === 'live.gap') {
      this.fence(t, m.type === 'live.gap' ? '采集发生缺口，请刷新以建立新基线' : undefined);
      await this.save();
      return { ok: true };
    }
    const source = sourceOf(t.id, doc);
    if (!source || m.type !== 'live.event') return { ok: false };
    const top = await chrome.webNavigation.getFrame({ tabId: t.browserId, frameId: 0 });
    if (run !== this.run || !top || t.ticket !== m.ticket || top.documentId !== doc.documentId)
      return { ok: false };
    if (!matchesPage(top.url, doc.binding, run.rules, run.destination.origin)) {
      this.fence(t);
      await this.save();
      return { ok: false };
    }
    const event = projectPageEvent(m.event);
    if (
      !m.baselineId ||
      !(
        m.baselineId.startsWith(m.ticket + ':') &&
        /^[1-9][0-9]{0,12}$/.test(m.baselineId.slice(m.ticket.length + 1))
      ) ||
      (event.kind !== 'baseline' && (doc.state !== 'ready' || t.baselineId !== m.baselineId))
    )
      return { ok: false };
    try {
      await saveLiveEvidence(
        this.db,
        run.id,
        run.destination,
        source,
        { baseline_id: m.baselineId, ...event },
        run.maxBytes,
      );
    } catch {
      if (t.ticket === m.ticket) {
        this.fence(t, '本地存储失败，已记录采集缺口');
        await this.save();
      }
      return { ok: false };
    }
    if (event.kind === 'baseline' && t.ticket === m.ticket) {
      doc.state = 'ready';
      t.baselineId = m.baselineId;
      await this.save();
    }
    this.notifyDelivery();
    return { ok: true };
  }
}
