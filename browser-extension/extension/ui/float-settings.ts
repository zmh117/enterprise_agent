import { hostPattern, sitesKey, bindingsKey, storedBindings } from '../background/float-sites';
import type { EnvironmentCatalog, SiteEnvironments } from '../../shared/recording-environment';

export function floatSettings(onChange: () => void) {
  const group = document.querySelector<HTMLFieldSetElement>('#float-sites')!;
  const list = document.getElementById('float-site-list')!;
  const save = document.querySelector<HTMLButtonElement>('#float-save')!;
  const status = document.getElementById('float-site-status')!;
  let available: string[] = [];
  let enabled = new Set<string>();
  let bindings: SiteEnvironments = {};
  let catalog: EnvironmentCatalog | null = null;
  const visibilityEdits = new Map<string, boolean>();
  const bindingEdits = new Map<string, string>();
  let loading = false, saving = false, revision = 0;

  function buttons() {
    group.disabled = saving || loading;
    save.disabled = saving || loading || !(visibilityEdits.size || bindingEdits.size);
  }
  function activeBindings(): SiteEnvironments {
    return Object.fromEntries([...enabled].filter(site =>
      catalog?.options.some(e => e.code === bindings[site])).map(site => [site, bindings[site]!]));
  }
  function render() {
    const choices = [...new Set([...available, ...enabled, ...visibilityEdits.keys()])].sort();
    list.replaceChildren(...choices.map(site => {
      const row = document.createElement('div');
      row.className = 'site-row';
      const label = document.createElement('label');
      label.className = 'check';
      const box = document.createElement('input');
      box.type = 'checkbox'; box.value = site;
      box.checked = visibilityEdits.get(site) ?? enabled.has(site);
      const select = document.createElement('select');
      select.setAttribute('aria-label', site + ' 的关联环境');
      select.add(new Option('未关联环境', ''));
      for (const env of catalog?.options ?? []) select.add(new Option(env.name && env.name !== env.code ? env.name + ' · ' + env.code : env.code, env.code));
      const saved = bindings[site] ?? '';
      const value = bindingEdits.get(site) ?? saved;
      if (value && !catalog?.options.some(e => e.code === value)) {
        const stale = new Option('原环境已不可用', value); stale.disabled = true; select.add(stale);
      }
      select.value = value;
      select.disabled = !catalog || !box.checked;
      box.onchange = () => {
        if (enabled.has(site) === box.checked) visibilityEdits.delete(site);
        else visibilityEdits.set(site, box.checked);
        if (!box.checked) bindingEdits.delete(site);
        select.disabled = !catalog || !box.checked;
        if (!box.checked) select.value = saved;
        status.textContent = ''; buttons();
      };
      select.onchange = () => {
        if (select.value === saved) bindingEdits.delete(site);
        else bindingEdits.set(site, select.value);
        status.textContent = ''; buttons();
      };
      label.append(box, document.createTextNode(site)); row.append(label, select); return row;
    }));
    if (!choices.length) list.textContent = '暂无可选站点，打开网页后刷新。';
    document.getElementById('env-source')!.textContent = !catalog ? '连接系统后可关联环境。' :
      !catalog.options.length ? '当前账号没有可关联的环境。' : '环境来自当前系统账号可访问的业务应用。';
    buttons(); onChange();
  }
  async function refresh(origins = available) {
    available = origins;
    const turn = ++revision;
    const key = catalog && bindingsKey(catalog.scope);
    loading = true; buttons();
    try {
      const stored = await chrome.storage.local.get(key ? [sitesKey, key] : [sitesKey]);
      if (turn !== revision) return;
      enabled = new Set(Array.isArray(stored[sitesKey]) ? stored[sitesKey] : []);
      bindings = storedBindings(key && stored[key]);
      render();
    } finally { if (turn === revision) { loading = false; buttons(); } }
  }
  function setCatalog(next: EnvironmentCatalog | null) {
    if (catalog?.scope !== next?.scope) { bindings = {}; bindingEdits.clear(); }
    revision++; catalog = next;
    render(); void refresh().catch(e => { status.textContent = String(e); });
  }
  save.onclick = async () => {
    if (save.disabled) return;
    saving = true; buttons();
    const add: string[] = [], remove: string[] = [];
    for (const [site, checked] of visibilityEdits) (checked ? add : remove).push(site);
    const binding = catalog && { scope: catalog.scope, values: Object.fromEntries(bindingEdits) };
    try {
      const origins = [...new Set(add.map(hostPattern))];
      if (origins.length && !await chrome.permissions.request({origins})) throw new Error('未获得站点权限，设置未保存');
      const result = await chrome.runtime.sendMessage({type:'float.sites.update', add, remove, binding});
      if (!result?.ok) throw new Error(result?.error ?? '站点设置失败');
      visibilityEdits.clear(); bindingEdits.clear(); await refresh(); status.textContent = '站点设置已保存。';
    } catch (e) { status.textContent = e instanceof Error ? e.message : '站点设置失败'; }
    finally { saving = false; buttons(); }
  };
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && (changes[sitesKey] || (catalog && changes[bindingsKey(catalog.scope)]))) {
      void refresh().catch(e => { status.textContent = String(e); });
    }
  });
  return { refresh, setCatalog, activeBindings };
}
