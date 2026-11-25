// 只处理实际应用的样式表。prefetch/preload 本身不参与布局。
export function inspectLayout(events) {
  const links = new Map(), refs = [], clicks = [];
  let base = events[0].data.href;
  function track(id, attributes, patch = attributes) {
    const previous = links.get(id);
    if (typeof patch._cssText === 'string') {
      if (previous?.ref && (!patch.href || previous.href === patch.href)) previous.ref.embedded = true;
      links.set(id, { ...attributes, _cssText:patch._cssText });
      return;
    }
    links.set(id, attributes);
    if (!String(attributes.rel || '').toLowerCase().split(/\s+/).includes('stylesheet') || !attributes.href) return;
    let url;
    try { url = new URL(attributes.href, base); } catch { return; }
    if (!['http:', 'https:'].includes(url.protocol)) return;
    const ref = {url:url.href, patch, embedded:false};
    refs.push(ref);
    links.set(id, {...attributes, ref});
  }
  function walk(node) {
    if (node.tagName === 'link') track(node.id, node.attributes);
    for (const child of node.childNodes || []) walk(child);
  }
  for (const event of events) {
    const d = event.data;
    if (event.type === 4) base = d.href;
    if (event.type === 2) { links.clear(); walk(d.node); }
    if (event.type !== 3) continue;
    if (d.source === 2 && d.type === 2 && d.id > 0) clicks.push({time:event.timestamp, id:d.id});
    if (d.source !== 0) continue;
    for (const add of d.adds || []) walk(add.node);
    for (const {id, attributes} of d.attributes || []) {
      if (!links.has(id) || !['rel','href','_cssText'].some(k => k in attributes)) continue;
      track(id, {...links.get(id), ...attributes}, attributes);
    }
  }
  return {refs:refs.filter(ref => !ref.embedded), clicks:clicks.sort((a,b) => a.time - b.time)};
}

// 相同部署路径和文件名才匹配。同路径在多个来源或版本下有歧义时跳过。
export async function readLocalStyles(files, views) {
  const byPath = new Map(), found = new Map();
  for (const view of views) for (const {url} of view.layout.refs) {
    let parts;
    try { parts = new URL(url).pathname.slice(1).split('/').map(decodeURIComponent); } catch { continue; }
    const path = JSON.stringify(parts);
    byPath.set(path, !byPath.has(path) || byPath.get(path) === url ? url : null);
  }
  let bytes = 0;
  for (const file of files) {
    if (!/\.css$/i.test(file.name)) continue;
    const relative = file.webkitRelativePath.split('/');
    const candidates = [relative, relative.slice(1)];
    const urls = new Set(candidates.map(parts => byPath.get(JSON.stringify(parts))).filter(Boolean));
    if (urls.size !== 1) continue;
    const [url] = urls;
    if (found.has(url)) { found.set(url, null); continue; }
    bytes += file.size;
    if (file.size > 16 * 1024 * 1024 || bytes > 64 * 1024 * 1024) throw new Error('匹配的样式文件超过本地读取预算。');
    found.set(url, file);
  }
  const result = new Map();
  for (const [url,file] of found) if (file) result.set(url, await file.text());
  return result;
}

// 用镜像节点 ID 标记最近一次点击。只在样式缺失的页面启用，保留录制坐标。
export function markLastClick(replayer, view, label) {
  const clicks = view.layout.clicks;
  let previous, marked, animation;
  return elapsed => {
    const time = view.start + Math.max(0, elapsed);
    let low = 0, high = clicks.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (clicks[mid].time <= time) low = mid + 1;
      else high = mid;
    }
    const click = clicks[low - 1];
    const target = click && replayer.getMirror().getNode(click.id);
    const node = target?.nodeType === 1 && target.isConnected ? target : null;
    if (previous === click && marked === node) return;
    animation?.cancel();
    previous = click;
    marked = node;
    label.textContent = '';
    if (!click) return;
    if (node) animation = node.animate([{outline:'3px solid #c04612', outlineOffset:'2px'}], {duration:0, fill:'forwards'});
    const at = ((click.time - view.start) / 1000).toFixed(1);
    label.textContent = '最近点击在 ' + at + ' 秒' + (node ? '，对应元素已用橙框标出。' : '，对应元素已离开当前画面。');
  };
}
