import {bindingForPage, describeRule, ruleForPage, sameRule, workshopLabel,
  type WorkshopClient} from '../../shared/workshop';
import {platformTraffic} from '../../shared/platform-traffic';
import type {SiteCatalog, SiteRule} from '../site-rules';
import {hostPattern} from '../background/float-sites';

export function workshopSettings(onChange: () => void, refresh: () => Promise<void>) {
  const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const select = (id: string) => el<HTMLSelectElement>(id);
  const app = select('site-app'), env = select('workshop-environment'), base = select('workshop-base'),
    shop = select('workshop-choice'), tabs = select('workshop-page');
  const address = el<HTMLInputElement>('site-address'), floating = el<HTMLInputElement>('site-floating');
  const form = el<HTMLFormElement>('site-form'), status = el('workshop-status');
  let clients: WorkshopClient[] = [], catalog: SiteCatalog | undefined, editing: SiteRule | undefined;
  let pages: {id: number; url: string}[] = [], busy = false, dirty = false, generation = 0;
  let params = new Set<string>();

  const client = () => clients.find(c => c.destination.app === app.value);
  const choices = () => client()?.choices ?? [];
  function scopeFor(row: SiteRule) {
    return clients.find(c => c.destination.app === row.app)?.choices.find(s =>
      s.environment_id === row.environment_id && s.base_id === row.base_id && s.workshop_id === row.workshop_id);
  }
  function target() {
    return choices().find(s => s.environment_id === env.value && s.base_id === (base.value || null) &&
      s.workshop_id === (shop.value || null));
  }
  function options(box: HTMLSelectElement, entries: [string, string][], prompt: string, value = '') {
    box.replaceChildren(new Option(prompt, ''), ...Array.from(new Map(entries), ([id,name]) => new Option(name,id)));
    box.value = value;
    if (box.selectedIndex < 0) box.selectedIndex = 0;
  }
  function levels(level: 'environment'|'base'|'workshop', selected?: SiteRule) {
    const all = choices();
    if (level === 'environment')
      options(env, all.map(s => [s.environment_id,s.environment_name]), '选择环境', selected?.environment_id);
    if (level !== 'workshop') {
      options(base, all.filter(s => s.environment_id === env.value && s.base_id)
        .map(s => [s.base_id!, s.base_name!]), '不选基地', selected?.base_id ?? '');
      base.disabled = !env.value || base.options.length === 1;
    }
    options(shop, all.filter(s => s.environment_id === env.value && s.base_id === base.value && s.workshop_id)
      .map(s => [s.workshop_id!, s.workshop_name!]), '不选车间', selected?.workshop_id ?? '');
    shop.disabled = !base.value || shop.options.length === 1;
  }
  function rule() {
    const url = address.value.trim();
    if (platformTraffic(url, catalog?.origin)) throw new Error('请选择业务页面');
    return ruleForPage(url, [...params]);
  }
  function refreshParams() {
    const group = el('site-params');
    group.replaceChildren();
    const allowed = new Set<string>();
    try {
      const url = new URL(address.value);
      const hashQuery = url.hash.startsWith('#/') ? url.hash.split('?')[1] : '';
      for (const key of new Set([...url.searchParams.keys(), ...new URLSearchParams(hashQuery).keys()])) {
        try { ruleForPage(url.href,[key]); } catch { continue; }
        allowed.add(key);
        const label = document.createElement('label'), box = document.createElement('input');
        label.className = 'check'; box.type = 'checkbox'; box.checked = params.has(key);
        box.onchange = () => { if (box.checked) params.add(key); else params.delete(key); changed(); };
        label.append(box, '匹配参数 ' + key); group.append(label);
      }
    } catch { /* The input may still be incomplete. */ }
    params = new Set([...params].filter(key => allowed.has(key)));
  }
  function buttons() {
    const editor = el<HTMLFieldSetElement>('workshop-editor'); editor.disabled = busy || !catalog;
    el('site-dirty').hidden = !dirty;
    el<HTMLButtonElement>('site-revert').disabled = !dirty || busy;
    el<HTMLButtonElement>('site-new').disabled = busy || !catalog;
    el<HTMLButtonElement>('workshop-revoke').hidden = !editing;
    el<HTMLButtonElement>('workshop-revoke').disabled = busy;
    const save = el<HTMLButtonElement>('workshop-save'); save.disabled = true;
    const hint = el('workshop-url'); hint.textContent = '';
    if (!address.value.trim()) return;
    try {
      const r = rule();
      hint.textContent = '匹配 ' + describeRule(r) + ' 及其子页面';
      if (env.value && !target()) hint.textContent += ' · 请选择账号已获授权的基地或车间';
      save.disabled = busy || !catalog || !target() || !dirty;
    } catch (e) { hint.textContent = e instanceof Error ? e.message : 'URL 无效'; }
  }
  function changed() { dirty = true; status.textContent = ''; buttons(); }
  function renderList() {
    const list = el('site-rules'); list.replaceChildren();
    const groups = new Map<string, SiteRule[]>();
    for (const row of catalog?.rules ?? []) if (row.enabled) {
      const group = groups.get(row.rule.origin) ?? []; group.push(row); groups.set(row.rule.origin,group);
    }
    if (!groups.size) {
      const empty = document.createElement('p'); empty.className = 'site-empty muted';
      empty.textContent = catalog ? '暂无地址规则' : '请先连接系统'; list.append(empty);
    }
    for (const [origin, rows] of [...groups].sort(([a],[b]) => a.localeCompare(b))) {
      const group = document.createElement('div'), title = document.createElement('strong');
      group.className = 'site-group'; title.textContent = origin; group.append(title);
      for (const row of rows.sort((a,b) => describeRule(a.rule).localeCompare(describeRule(b.rule)))) {
        const btn = document.createElement('button'), detail = document.createElement('small'), scope = scopeFor(row);
        btn.type = 'button'; btn.disabled = busy; btn.dataset.bindingId = row.id;
        if (row.id === editing?.id) btn.setAttribute('aria-current','true');
        detail.textContent = [clients.find(c => c.destination.app === row.app)?.name, scope && workshopLabel(scope)].filter(Boolean).join(' · ');
        btn.append(describeRule(row.rule).slice(origin.length),detail);
        btn.onclick = () => { if (!busy && discard()) open(row); }; group.append(btn);
      }
      list.append(group);
    }
  }
  const discard = () => !dirty || confirm('放弃尚未保存的修改？');
  function open(row?: SiteRule, url = '') {
    editing = row; dirty = false;
    el('site-title').textContent = row ? '编辑规则' : '新增规则';
    address.value = row ? describeRule(row.rule) : url;
    params = new Set(Object.keys(row?.rule.query ?? {}));
    options(app, clients.map(c => [c.destination.app,c.name]), '选择业务应用', row?.app ?? (clients.length === 1 ? clients[0]!.destination.app : ''));
    floating.checked = row?.floating !== false; tabs.value = '';
    levels('environment',row); refreshParams(); renderList(); buttons();
  }
  function setCatalog(next: WorkshopClient[], fresh?: SiteCatalog) {
    const same = fresh && fresh.origin === catalog?.origin && fresh.account === catalog?.account;
    clients = next; catalog = fresh;
    if (!same || !dirty) open(fresh?.rules.find(r => r.enabled && r.id === editing?.id) ?? fresh?.rules.find(r => r.enabled));
    else { renderList(); buttons(); }
    if (!fresh) { ++generation; busy = false; open(); }
    status.textContent = fresh ? '' : '请先在「系统连接」登录平台。'; onChange();
  }
  function match(url: string) { return catalog && bindingForPage(url,catalog.rules,catalog.origin); }
  function selectTab(id: number) {
    const page = pages.find(p => p.id === id);
    if (!page) return;
    address.value = page.url; params.clear(); refreshParams(); changed();
  }
  tabs.onchange = () => { if (tabs.value) selectTab(Number(tabs.value)); };
  address.oninput = () => { tabs.value = ''; refreshParams(); changed(); };
  app.onchange = () => { levels('environment'); changed(); };
  env.onchange = () => { levels('base'); changed(); };
  base.onchange = () => { levels('workshop'); changed(); };
  shop.onchange = floating.onchange = changed;
  el('site-new').onclick = () => { if (discard()) { open(); address.focus(); } };
  el('site-revert').onclick = () => open(editing);

  async function persist(remove: boolean) {
    const c = client(), original = editing, turn = generation;
    if (!c || busy || !catalog) return;
    if (remove && (!original || !confirm('删除这条站点规则？'))) return;
    busy = true; buttons();
    let saved: SiteRule | undefined, written = false;
    try {
      if (remove && original) {
        await clients.find(item => item.destination.app === original.app)!.revoke(original);
      } else {
        const r = rule(), scope = target();
        if (!scope) throw new Error('请选择已获授权的范围');
        if (!await chrome.permissions.request({origins:[hostPattern(r.origin)]})) throw new Error('未获得站点访问权限');
        if (turn !== generation) return;
        const revoked = catalog.rules.find(b => !b.enabled && b.app === app.value && sameRule(b.rule,r));
        const result = await c.save(r,scope,original?.revision ?? revoked?.revision ?? 0,floating.checked,original?.id);
        saved = {...result, app:c.destination.app};
      }
      written = true;
      if (turn !== generation) return;
      dirty = false; editing = saved;
      await refresh();
      if (turn === generation) { open(saved && catalog.rules.find(r => r.id === saved?.id && r.enabled)); status.textContent = remove ? '规则已删除' : '规则已保存到平台'; }
    } catch (e) {
      if (turn === generation) status.textContent = written ? '平台已保存，规则列表刷新失败，请点击刷新。' :
        (e instanceof Error ? e.message : '保存失败，请刷新规则后重试');
    } finally { if (turn === generation) { busy = false; buttons(); renderList(); } }
  }
  form.onsubmit = event => { event.preventDefault(); void persist(false); };
  el('workshop-revoke').onclick = () => void persist(true);
  open();
  return {
    setCatalog,
    selectTab(id: number) { if (discard()) { open(); selectTab(id); } },
    pages(next: {id?: number; url: string}[]) {
      pages = next.flatMap(t => {
        if (t.id === undefined || platformTraffic(t.url,catalog?.origin)) return [];
        try { ruleForPage(t.url); return [{id:t.id,url:t.url}]; } catch { return []; }
      });
      options(tabs,pages.map(p => [String(p.id), describeRule(ruleForPage(p.url))]),'选取标签页',tabs.value);
    },
    destination(ids: number[]) {
      const apps = new Set(ids.map(id => match(pages.find(p => p.id === id)?.url ?? '')?.app));
      if (!catalog || apps.has(undefined)) throw new Error('所选页面尚未绑定可采集的范围，请在「站点设置」保存规则。');
      if (apps.size !== 1) throw new Error('一次持续采集只能包含同一业务应用的标签页。');
      return clients.find(c => apps.has(c.destination.app))!.destination;
    },
    activeBindings(ids: Iterable<number>) {
      const result: Record<string,string> = {};
      for (const id of ids) {
        const page = pages.find(p => p.id === id);
        if (!page) continue;
        const row = match(page.url), origin = new URL(page.url).origin;
        const code = row && scopeFor(row)?.environment_code || '';
        result[origin] = origin in result && result[origin] !== code ? '' : code;
      }
      return result;
    },
  };
}
