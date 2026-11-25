import { explain, type Platform } from './agent-panel';

type Entry = {conversation_id: string; application_id: string; title: string; activity_at: string};
type Turn = {job_id: string; question: string; answer_preview?: string};
type TurnPage = {jobs: Turn[]; next_before: string | null};
type Catalog = {id: string; name: string}[];
const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export class ConversationHistory {
  private platform?: Platform;
  private apps: Catalog = [];
  private application = '';
  private selected = '';
  private request?: AbortController;
  private next: string | null = null;
  private entries = new Map<string, Entry>();
  private readonly list = byId('conversation-list');
  private readonly hint = byId('conversation-status');
  private readonly rail = byId('conversation-rail');
  private readonly answers = byId('agent-answers');
  private readonly chat = byId('agent-thread');
  private readonly home = byId('agent-panel');
  private readonly appChoice = byId<HTMLSelectElement>('conversation-app');
  private readonly older = byId<HTMLButtonElement>('conversation-more');
  private readonly start = byId<HTMLButtonElement>('conversation-new');
  private readonly draft = byId<HTMLTextAreaElement>('agent-question');
  private turns: (Turn & {page?: string})[] = [];
  private indexRequest?: AbortController;
  private buttons = new Map<string, HTMLButtonElement>();
  private jumpId = 0;
  private target?: {job: string; top: number};
  private peek = document.createElement('div');

  constructor(select: (app: string, id?: string) => Promise<void>, private loadTurns: (before?: string) => Promise<void>) {
    this.peek.id = 'turn-preview-popup';
    this.peek.className = 'turn-preview';
    this.peek.hidden = true;
    this.peek.setAttribute('role','tooltip');
    this.peek.append(document.createElement('strong'), document.createElement('span'));
    byId('conversation-main').after(this.peek);
    this.rail.addEventListener('scroll', () => { this.peek.hidden = true; }, {passive:true});
    const pick = async (app: string, id?: string) => {
      const platform = this.platform;
      if (!platform || this.appChoice.disabled) return;
      this.appChoice.disabled = this.start.disabled = true;
      this.list.inert = true;
      this.hint.textContent = '';
      try {
        await select(app, id);
        if (id === '' && platform === this.platform) this.draft.focus({preventScroll:true});
      } catch (error) {
        if (platform === this.platform && !(error instanceof DOMException && error.name === 'AbortError')) {
          this.hint.textContent = explain(error);
        }
      } finally {
        if (platform === this.platform) {
          this.appChoice.value = this.application;
          this.appChoice.disabled = this.start.disabled = false;
          this.list.inert = false;
        }
      }
    };
    this.appChoice.onchange = () => void pick(this.appChoice.value);
    this.list.onclick = event => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-session]');
      const entry = this.entries.get(button?.dataset.session ?? '');
      if (entry && this.selected !== entry.conversation_id) void pick(entry.application_id, entry.conversation_id);
    };
    this.start.onclick = () => void pick(this.appChoice.value, '');
    this.older.onclick = () => void this.refresh(true);
    this.answers.addEventListener('scroll', () => this.highlight(), {passive:true});
    const sync = () => {
      const host = this.active ? byId('conversation-main') : this.home;
      if (this.chat.parentElement !== host) host.append(this.chat);
      if (this.active) { void this.index(); void this.refresh(); }
      else { this.request?.abort(); this.indexRequest?.abort(); this.peek.hidden = true; }
    };
    window.addEventListener('hashchange', sync);
    this.connect(undefined, []);
    sync();
  }

  private get active() { return location.hash === '#conversations'; }
  connect(platform: Platform | undefined, apps: Catalog) {
    this.request?.abort();
    this.platform = platform;
    this.indexRequest?.abort();
    this.apps = apps;
    this.application = '';
    this.entries.clear();
    this.next = null;
    this.selected = '';
    this.list.replaceChildren();
    this.rail.replaceChildren();
    this.turns = []; this.peek.hidden = true; this.target = undefined;
    this.buttons.clear();
    this.appChoice.replaceChildren(...apps.map(app => new Option(app.name, app.id)));
    this.appChoice.disabled = this.start.disabled = !apps.length;
    this.list.inert = false;
    this.older.hidden = true;
    this.hint.textContent = platform ? '' : '请先在「Agent 对话」中连接系统。';
    this.showHeading();
  }

  current(app: string, id: string) {
    const appChanged = this.application !== app;
    const changed = appChanged || this.selected !== id;
    if (appChanged) {
      this.request?.abort();
      this.application = app;
      this.entries.clear();
      this.next = null;
      this.list.replaceChildren();
      this.older.hidden = true;
      this.hint.textContent = '';
      if (this.active) void this.refresh();
    }
    this.selected = id;
    if (changed) {
      this.indexRequest?.abort();
      this.turns = []; this.buttons.clear(); this.peek.hidden = true; this.target = undefined; this.rail.replaceChildren();
      if (this.active) void this.index();
    }
    this.appChoice.value = app;
    this.showHeading();
    for (const button of this.list.querySelectorAll<HTMLButtonElement>('button')) {
      button.setAttribute('aria-current', String(button.dataset.session === id));
    }

  }

  private showHeading() {
    byId('conversation-heading').textContent = this.entries.get(this.selected)?.title || (this.selected ? '当前会话' : '新会话');
  }

  async refresh(append = false) {
    const platform = this.platform;
    if (!platform || !this.active || !this.application || (append && !this.next)) return;
    this.request?.abort();
    const request = this.request = new AbortController();
    this.older.disabled = true;
    try {
      const params = new URLSearchParams({application_id: this.application});
      if (append && this.next) params.set('before', this.next);
      const path = '/conversations?' + params;
      const page: {items: Entry[]; next_before: string | null} = await (await platform.request(path, {signal:request.signal})).json();
      request.signal.throwIfAborted();
      if (!append) this.entries.clear();
      for (const entry of page.items) this.entries.set(entry.conversation_id, entry);
      this.next = page.next_before;
      this.list.replaceChildren(...Array.from(this.entries.values(), entry => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.session = entry.conversation_id;
        button.setAttribute('aria-current', String(entry.conversation_id === this.selected));
        const title = document.createElement('span');
        title.textContent = entry.title; button.title = entry.title;
        const meta = document.createElement('small');
        const date = new Date(entry.activity_at);
        meta.textContent = [this.apps.find(app => app.id === entry.application_id)?.name,
          Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')].filter(Boolean).join(' · ');
        button.append(title, meta);
        return button;
      }));
      this.showHeading();
      this.older.hidden = !this.next;
      this.hint.textContent = this.entries.size ? '' : '还没有对话';
    } catch (error) {
      if (!request.signal.aborted) {
        this.entries.clear(); this.list.replaceChildren(); this.older.hidden = true;
        this.hint.textContent = explain(error);
      }
    } finally {
      if (!request.signal.aborted) this.older.disabled = false;
    }
  }

  private async index() {
    this.indexRequest?.abort();
    const platform = this.platform, id = this.selected;
    if (!id || !platform) return;
    const request = this.indexRequest = new AbortController();
    let cursor: string | undefined;
    const turns: typeof this.turns = [];
    try {
      do {
        const params = new URLSearchParams({limit:'20'});
        if (cursor) params.set('before', cursor);
        const page: TurnPage = await (await platform.request('/conversations/' + encodeURIComponent(id) + '?' + params,
          {signal:request.signal})).json();
        request.signal.throwIfAborted();
        turns.unshift(...page.jobs.map(row => ({...row, page:cursor})));
        cursor = page.next_before || undefined;
      } while (cursor);
      const ids = new Set(turns.map(row => row.job_id));
      this.turns = turns.concat(this.turns.filter(row => !ids.has(row.job_id)));
      this.renderRail();
    } catch (error) {
      if (!request.signal.aborted) {
        this.turns = []; this.buttons.clear(); this.peek.hidden = true; this.target = undefined; this.rail.replaceChildren();
        this.hint.textContent = explain(error);
      }
    }
  }

  pageLoaded(rows: Turn[], before?: string) {
    if (!this.active) return;
    const known = new Map(this.turns.map(row => [row.job_id, row]));
    const added: typeof this.turns = [];
    for (const row of rows) {
      const entry = known.get(row.job_id);
      if (entry) Object.assign(entry, row); else added.push({...row, page:before});
    }
    if (before) this.turns.unshift(...added); else this.turns.push(...added);
    this.renderRail();
  }

  arrange() {
    if (!this.active) return;
    const articles = this.articles();
    const order = this.turns.filter(turn => articles.has(turn.job_id));
    if (order.every((turn, index) => this.answers.children[index] === articles.get(turn.job_id))) return;
    for (const turn of order) {
      const node = articles.get(turn.job_id);
      if (node) this.answers.append(node);
    }
  }

  private articles() {
    return new Map(Array.from(this.answers.querySelectorAll<HTMLElement>('article[data-job]'), node => [node.dataset.job!, node]));
  }

  private renderRail() {
    const focused = this.rail.contains(document.activeElement)
      ? (document.activeElement as HTMLElement).dataset.turn : undefined;
    this.buttons.clear();
    const buttons = this.turns.map(turn => {
      const button = document.createElement('button');
      button.dataset.turn = turn.job_id;
      button.type = 'button'; button.setAttribute('aria-label', '跳到提问：' + turn.question.slice(0, 96));
      const preview = () => {
        this.peek.children[0]!.textContent = turn.question.slice(0,120);
        this.peek.children[1]!.textContent = (this.articles().get(turn.job_id)?.querySelector('.agent-markdown')?.textContent
          || turn.answer_preview || '').slice(0,150);
        const rect = button.getBoundingClientRect();
        this.peek.hidden = false;
        this.peek.style.left = Math.max(4,Math.min(rect.right + 2,innerWidth - this.peek.offsetWidth - 4)) + 'px';
        this.peek.style.top = Math.max(4,Math.min(rect.top - 6,innerHeight - this.peek.offsetHeight - 4)) + 'px';
        button.setAttribute('aria-describedby',this.peek.id);
      };
      const hide = () => { this.peek.hidden = true; button.removeAttribute('aria-describedby'); };
      button.onmouseenter = preview; button.onfocus = preview;
      button.onmouseleave = hide; button.onblur = hide;
      button.onkeydown = event => { if (event.key === 'Escape') hide(); };
      button.onclick = () => void this.jump(turn);
      this.buttons.set(turn.job_id, button);
      return button;
    });
    this.peek.hidden = true;
    this.rail.replaceChildren(...buttons);
    if (focused) this.buttons.get(focused)?.focus({preventScroll:true});
    this.highlight();
  }

  private async jump(turn: Turn & {page?: string}) {
    const id = ++this.jumpId, session = this.selected;
    try {
      if (!this.articles().has(turn.job_id)) await this.loadTurns(turn.page);
      if (this.selected !== session || id !== this.jumpId) return;
      const target = this.articles().get(turn.job_id);
      if (target) {
        this.answers.scrollTop += target.getBoundingClientRect().top - this.answers.getBoundingClientRect().top;
        this.target = {job:turn.job_id, top:this.answers.scrollTop};
        this.mark(turn.job_id);
      }
    } catch (error) {
      if (this.selected === session && id === this.jumpId) this.hint.textContent = explain(error);
    }
  }

  private mark(job?: string) {
    for (const [id,button] of this.buttons) button.setAttribute('aria-current', String(job === id));
  }
  private highlight() {
    if (!this.active || !this.turns.length) return;
    if (this.target && Math.abs(this.target.top - this.answers.scrollTop) < 1) {
      this.mark(this.target.job);
      return;
    }
    this.target = undefined;
    const articles = [...this.articles().values()];
    const top = this.answers.getBoundingClientRect().top + 20;
    const current = articles.filter(turn => turn.getBoundingClientRect().top <= top).at(-1);
    this.mark((current ?? articles[0])?.dataset.job);
  }
}
