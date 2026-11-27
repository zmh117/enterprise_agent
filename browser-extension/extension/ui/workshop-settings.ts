import {
  bindingForPage,
  describeRule,
  ruleForPage,
  sameRule,
  type WorkshopBinding,
  type WorkshopClient,
} from '../../shared/workshop';
import { hostPattern } from '../background/float-sites';
import { platformTraffic } from '../../shared/platform-traffic';

export function workshopSettings() {
  const select = (id: string) => document.querySelector<HTMLSelectElement>('#' + id)!;
  const range = select('workshop-range'), page = select('workshop-page'),
    env = select('workshop-environment'),
    base = select('workshop-base'),
    shop = select('workshop-choice');
  const keys = document.querySelector<HTMLInputElement>('#workshop-keys')!;
  const status = document.getElementById('workshop-status')!,
    preview = document.getElementById('workshop-url')!;
  const save = document.querySelector<HTMLButtonElement>('#workshop-save')!;
  const revoke = document.querySelector<HTMLButtonElement>('#workshop-revoke')!;
  const connectFirst = '请在「Agent 对话」连接平台并选择业务应用。';
  const noWorkshops = (name: string) => `当前账号在「${name}」没有可采集的车间。请在「页面车间」切换业务应用，或联系管理员。`;
  let client: WorkshopClient | null = null,
    bindings: WorkshopBinding[] = [];
  let pages: { id: number; url: string }[] = [],
    busy = false,
    generation = 0;
  const choices = () => client?.choices ?? [];
  const address = () => pages.find((p) => String(p.id) === page.value)?.url;
  function rule() {
    const url = address();
    if (!url) throw new Error('请先选择页面');
    if (range.value === 'site') return ruleForPage(new URL(url).origin);
    return ruleForPage(
      url,
      keys.value
        .trim()
        .split(/[，,\s]+/)
        .filter(Boolean),
    );
  }
  function options(el: HTMLSelectElement, entries: [string, string][], value = '') {
    el.replaceChildren(
      new Option('请选择', ''),
      ...Array.from(new Map(entries), ([id, name]) => new Option(name, id)),
    );
    el.value = value;
  }
  function loadShop(value = '') {
    options(
      shop,
      choices()
        .filter((s) => s.environment_id === env.value && s.base_id === base.value)
        .map((s) => [s.workshop_id, s.workshop_name]),
      value,
    );
  }
  function loadBase(baseValue = '', shopValue = '') {
    options(
      base,
      choices()
        .filter((s) => s.environment_id === env.value)
        .map((s) => [s.base_id, s.base_name]),
      baseValue,
    );
    loadShop(shopValue);
  }
  function render(match?: WorkshopBinding) {
    options(
      env,
      choices().map((s) => [s.environment_id, s.environment_name]),
      match?.environment_id,
    );
    loadBase(match?.base_id, match?.workshop_id);
    refreshButtons();
  }
  function refreshButtons() {
    const canEdit = !!client && !busy;
    save.disabled = true;
    revoke.disabled = true;
    if (!address()) {
      preview.textContent = '';
      return;
    }
    try {
      const r = rule();
      preview.textContent = describeRule(r);
      save.disabled = !canEdit || !shop.value;
      revoke.disabled = !canEdit || !bindings.some((b) => b.enabled && sameRule(r, b.rule));
    } catch (e) {
      preview.textContent = e instanceof Error ? e.message : '规则无效';
    }
  }
  function selectPage() {
    const url = address();
    const site = range.value === 'site';
    const match = url && bindingForPage(site ? new URL(url).origin : url, bindings, client?.destination.origin);
    keys.disabled = site;
    keys.value = match ? Object.keys(match.rule.query).join(', ') : '';
    const inherited = document.getElementById('workshop-inherited')!;
    inherited.hidden = !(match && !sameRule(rule(), match.rule));
    inherited.textContent = !inherited.hidden && match ? '当前页面继承 ' + describeRule(match.rule) : '';
    render(match || undefined);
  }
  page.onchange = selectPage;
  range.onchange = selectPage;
  env.onchange = () => {
    loadBase();
    refreshButtons();
  };
  base.onchange = () => {
    loadShop();
    refreshButtons();
  };
  shop.onchange = refreshButtons;
  keys.oninput = refreshButtons;
  async function persist(remove: boolean) {
    const current = client;
    if (!current || busy) return;
    const turn = generation;
    try {
      const r = rule(), selectedPage = ruleForPage(address()!, Object.keys(r.query)),
        id = Number(page.value);
      const target = choices().find((s) => s.workshop_id === shop.value);
      busy = true;
      refreshButtons();
      if (!remove && !(await chrome.permissions.request({ origins: [hostPattern(r.origin)] })))
        throw new Error('未获得页面访问权限');
      if (turn !== generation) return;
      const tab = await chrome.tabs.get(id);
      if (!tab.url || !sameRule(selectedPage, ruleForPage(tab.url, Object.keys(r.query))))
        throw new Error('页面已变化，请刷新后重试');
      const old = bindings.find((b) => sameRule(b.rule, r));
      if (remove && old) await current.revoke(old);
      if (!remove) {
        if (!target || turn !== generation) return;
        await current.save(r, target, old?.revision ?? 0);
        if (turn !== generation) return;
        const res = await chrome.runtime.sendMessage({
          type: 'float.sites.update',
          add: [r.origin],
          remove: [],
        });
        if (!res?.ok) throw new Error('请刷新并检查站点访问权限');
      }
      const updated = await current.list();
      if (turn !== generation) return;
      bindings = updated;
      status.textContent = remove ? '已撤销页面绑定' : '已保存页面车间';
      await chrome.storage.local.set({ [current.key]: updated });
      selectPage();
    } catch (e) {
      if (turn === generation)
        status.textContent = e instanceof Error ? e.message : '保存失败，请刷新';
    } finally {
      if (turn === generation) {
        busy = false;
        refreshButtons();
      }
    }
  }
  save.onclick = () => void persist(false);
  revoke.onclick = () => void persist(true);
  return {
    destination() {
      if (!client) throw new Error(status.textContent || connectFirst);
      if (!client.choices.length) throw new Error(noWorkshops(client.name));
      return client.destination;
    },
    selectTab(id: number) {
      if (pages.some(p => p.id === id)) {
        page.value = String(id);
        selectPage();
      }
    },
    pages(next: { id?: number; url: string }[]) {
      const selected = page.value;
      pages = next.flatMap((t) => {
        if (t.id === undefined || platformTraffic(t.url)) return [];
        try {
          ruleForPage(t.url);
          return [{ id: t.id, url: t.url }];
        } catch {
          return [];
        }
      });
      options(
        page,
        pages.map((p) => [String(p.id), describeRule(ruleForPage(p.url))]),
        selected,
      );
      if (!page.value && pages.length) page.value = String(pages[0]!.id);
      selectPage();
    },
    async client(next: WorkshopClient | null) {
      const turn = ++generation;
      client = null;
      bindings = [];
      busy = false;
      selectPage();
      status.textContent = next ? '正在读取页面车间绑定，请稍后重试。' : connectFirst;
      if (!next) return;
      try {
        const updated = await next.list();
        if (turn !== generation) return;
        await chrome.storage.local.set({[next.key]: updated});
        if (turn !== generation) return;
        client = next;
        bindings = updated;
        selectPage();
        status.textContent = next.choices.length ? '' : noWorkshops(next.name);
      } catch {
        if (turn === generation) status.textContent = '车间绑定暂不可用，请在「站点设置」点击「刷新站点」。';
      }
    },
  };
}
