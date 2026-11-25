import { openPackage, readViews } from './recording.js';
import { mountNetwork } from './network-panel.js';
import { inspectLayout, readLocalStyles, markLastClick } from './layout.js';

const zip = document.querySelector('#zip');
const folder = document.querySelector('#folder');
const stream = document.querySelector('#stream');
const streamsBar = document.querySelector('#streams');
const target = document.querySelector('#player');
const network = document.querySelector('#network');
const statusLine = document.querySelector('#status');
let activeImport = 0, views = [], player, readBody;
const stylePicker = document.querySelector('#styles-folder');
const styleResult = document.querySelector('#style-result');
const clickLabel = document.querySelector('#click-target');
const localStyles = new Map();
let styleImport = 0, elapsed = 0;

function closePlayer() {
  document.querySelector('#path-filter').oninput = null;
  if (player) {
    const previous = player;
    player = undefined;
    previous.pause();
    previous.$destroy();
  }
  target.replaceChildren();
  document.querySelector('#requests').replaceChildren();
  network.hidden = true;
  document.querySelector('#layout-note').hidden = true;
  clickLabel.textContent = '';
  styleResult.textContent = '';
}

function dimensions() {
  return {width:Math.max(280, target.clientWidth - 4), height:Math.max(230, Math.min(850, window.innerHeight - 245, target.clientWidth * 0.68))};
}

function showStream(position) {
  closePlayer();
  const view = views[Number(stream.value)];
  if (!view) return;
  const required = new Set(view.layout.refs.map(ref => ref.url));
  const missing = [...required].filter(url => !localStyles.has(url)).length;
  document.querySelector('#layout-note').hidden = !required.size;
  document.querySelector('#layout-message').textContent = missing
    ? '本页有 ' + missing + ' 个外部样式表缺少正文，离线布局可能与现场不同。'
    : '已补入本页引用的 ' + required.size + ' 个外部样式表。';
  for (const ref of view.layout.refs) if (localStyles.has(ref.url)) ref.patch._cssText = localStyles.get(ref.url);
  network.hidden = false;
  try {
    player = new rrwebPlayer({target, props:{
      ...dimensions(), events:view.events, autoPlay:false, skipInactive:false,
      // 拖动进度条时，点击的控件可能刚由前一条 DOM 变更插入。先更新真实镜像再回放点击。
      useVirtualDom:false, mouseTail:false, showWarning:false, showDebug:false, loadTimeout:0
    }});
    const instance = player;
    const firstSnapshot = Math.max(0, view.events[1].timestamp - view.start);
    const updateNetwork = mountNetwork(view, readBody, requestTime => {
      // rrweb 暂停定位时同步应用严格早于游标的事件。包含同一毫秒的页面变化。
      const frameTime = Math.max(firstSnapshot, requestTime - view.start);
      const position = Math.min(view.duration, frameTime) + 0.001;
      instance.goto(position, false);
      sync(position);
    });
    const mark = missing ? markLastClick(instance.getReplayer(), view, clickLabel) : null;
    function sync(time) {
      elapsed = time;
      updateNetwork(time);
      mark?.(time);
    }
    instance.addEventListener('ui-update-current-time', ({payload}) => {
      if (player === instance) sync(payload);
    });
    instance.getReplayer().on('finish', () => {
      if (player === instance) sync(view.duration);
    });
    const startAt = Math.min(view.duration, Math.max(firstSnapshot, position ?? firstSnapshot));
    instance.goto(startAt, false);
    sync(startAt);
  } catch {
    closePlayer();
    statusLine.textContent = '这个页面的录制无法还原，请尝试其他录制页面。';
  }
}

async function openRecording(input) {
  const files = Array.from(input.files);
  if (!files.length) return;
  input.value = '';
  const generation = ++activeImport;
  const current = () => activeImport === generation;
  views = [];
  localStyles.clear();
  styleImport++;
  document.querySelector('#path-filter').value = '';
  readBody = undefined;
  closePlayer();
  streamsBar.hidden = true;
  stream.replaceChildren();
  statusLine.textContent = '正在读取页面事件和接口索引…';
  try {
    const pkg = await openPackage(files, input === zip);
    if (!current()) return;
    const result = await readViews(pkg.chunks, current);
    if (!current()) return;
    views = result.views;
    for (const view of views) view.layout = inspectLayout(view.events);
    readBody = pkg.readBody;
    views.forEach((view,i) => stream.add(new Option(
      (i + 1) + ' · ' + view.host + ' · ' + (view.duration / 1000).toFixed(1) + ' 秒 · ' + view.eventCount + ' 个事件', i
    )));
    streamsBar.hidden = false;
    statusLine.textContent = '可回放 ' + views.length + ' 条页面录制。' +
      (result.skipped ? '另有 ' + result.skipped + ' 条缺少起始快照。' : '');
    showStream();
  } catch (error) {
    if (current()) statusLine.textContent = '读取失败。' + (error.message || '请检查录制包。');
  }
}
zip.addEventListener('change', () => openRecording(zip));
folder.addEventListener('change', () => openRecording(folder));
stream.addEventListener('change', () => showStream());
stylePicker.addEventListener('change', async () => {
  const files = Array.from(stylePicker.files);
  stylePicker.value = '';
  if (!files.length) return;
  const id = ++styleImport;
  try {
    const found = await readLocalStyles(files, views);
    if (id !== styleImport) return;
    if (!found.size) { styleResult.textContent = '目录中没有匹配的 CSS，请选择保留原路径和文件名的部署目录。'; return; }
    for (const [url, css] of found) localStyles.set(url, css || '/* empty stylesheet */');
    showStream(elapsed);
    styleResult.textContent = '所选目录匹配了 ' + found.size + ' 个样式表。';
  } catch (error) { if (id === styleImport) styleResult.textContent = error.message; }
});
window.addEventListener('resize', () => player?.$set(dimensions()));
