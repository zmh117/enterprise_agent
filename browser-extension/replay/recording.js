import { strFromU8, unzipSync } from 'fflate';

const chunkPath = /^(.*\/)?((?:rrweb|events|network)\/(?:\d+|index-\d+)\.ndjson)$/;
const bodyPath = /^bodies\/[a-zA-Z0-9-]+\.(json|txt)$/;
const MiB = 1024 * 1024;

function checkBody(path, size) {
  if (!bodyPath.test(path)) throw new Error('附件路径无效');
  if (size > 16 * MiB) throw new Error('正文超过 16 MiB 读取上限');
}

export async function openPackage(files, zipped) {
  const chunks = [];
  let root, total = 0;
  function include(path, size) {
    const match = chunkPath.exec(path);
    if (!match) return false;
    const prefix = match[1] || '';
    if (root !== undefined && root !== prefix) throw new Error('请选择单个录制包。');
    root = prefix;
    total += size;
    if (total > 192 * MiB) throw new Error('页面事件和接口索引超过 192 MiB 读取上限。');
    return true;
  }
  if (zipped) {
    if (files[0].size > 512 * MiB) throw new Error('请先解压这个 ZIP，再选择录制文件夹。');
    const bytes = new Uint8Array(await files[0].arrayBuffer());
    const entries = unzipSync(bytes, { filter: entry => include(entry.name, entry.originalSize) });
    for (const [path, data] of Object.entries(entries)) {
      chunks.push({ path: path.slice(root.length), text: () => strFromU8(data) });
    }
    return { chunks, readBody(path) {
      checkBody(path, 0);
      const name = root + path;
      const entry = unzipSync(bytes, { filter(item) {
        if (item.name !== name) return false;
        checkBody(path, item.originalSize);
        return true;
      } })[name];
      if (!entry) throw new Error('包内缺少正文附件');
      return strFromU8(entry);
    } };
  }
  const byPath = new Map(files.map(file => [file.webkitRelativePath, file]));
  for (const [path, file] of byPath) {
    if (include(path, file.size)) chunks.push({ path: path.slice(root.length), text: () => file.text() });
  }
  return { chunks, async readBody(path) {
    const file = byPath.get(root + path);
    if (!file) throw new Error('包内缺少正文附件');
    checkBody(path, file.size);
    return file.text();
  } };
}

// wallTime 是 Unix 秒。CDP 的 timestamp 是单调时钟，只在同一次请求内计算差值。
function requestTimes(record, marks = {}) {
  const observed = marks['network.request_observed'];
  const wall = observed?.payload.wallTime;
  const start = Number.isFinite(wall) && wall > 0 ? wall * 1000 : Date.parse(record.startedAt);
  function at(event) {
    if (!event) return NaN;
    const base = observed?.payload.timestamp ?? record.sourceTime;
    const tick = event.payload.timestamp;
    if (Number.isFinite(base) && Number.isFinite(tick)) return start + (tick - base) * 1000;
    return Date.parse(event.observedAt);
  }
  let end = at(marks['network.loading_finished']);
  if (!Number.isFinite(end)) end = Date.parse(record.endedAt);
  let response = at(marks['network.response_observed']);
  if (!Number.isFinite(response)) response = end;
  if (Number.isFinite(response)) response = Math.max(start, response);
  if (Number.isFinite(end)) end = Math.max(start, end, Number.isFinite(response) ? response : start);
  return {record, start, response, end};
}

export async function readViews(chunks, current) {
  const groups = new Map(), marks = new Map(), records = [];
  for (const chunk of chunks) {
    const text = await chunk.text();
    if (!current()) return [];
    const index = chunk.path.startsWith('network/index-');
    for (const line of text.split('\n')) {
      if (!line.trim()) continue;
      let row;
      try { row = JSON.parse(line); }
      catch { throw new Error('事件文件含有不完整的 JSON 行：' + chunk.path); }
      if (index) { records.push(row); continue; }
      if (row.kind === 'rrweb.event') {
        const event = row.payload.rrwebEvent;
        if (!row.recorderStreamId || !Number.isInteger(row.sourceSeq) ||
            !Number.isFinite(event?.timestamp) || !Number.isInteger(event.type)) throw new Error('录制包含无法识别的 rrweb 事件。');
        const key = JSON.stringify([row.recordingId, row.tabInstanceId, row.recorderStreamId]);
        if (!groups.has(key)) groups.set(key, {tab:JSON.stringify([row.recordingId, row.tabInstanceId]), doc:row.emitterContext?.documentId, rows:[]});
        groups.get(key).rows.push({seq:row.sourceSeq, event});
      } else if (['network.request_observed','network.response_observed','network.loading_finished'].includes(row.kind)) {
        const key = row.payload.requestKey;
        if (!marks.has(key)) marks.set(key, {});
        marks.get(key)[row.kind] = {observedAt:row.observedAt, payload:{wallTime:row.payload.wallTime, timestamp:row.payload.timestamp}};
      }
    }
  }
  if (!groups.size) throw new Error('没有找到 rrweb 页面事件。请选择插件导出的录制 ZIP 或整个录制文件夹。');
  const views = [];
  for (const group of groups.values()) {
    const all = group.rows.sort((a,b) => a.seq - b.seq).map(row => row.event);
    const full = all.findIndex(event => event.type === 2);
    if (full < 0) continue;
    const meta = all.slice(0, full).findLast(event => event.type === 4);
    if (!meta) continue;
    const events = [meta, ...all.slice(full)];
    let host = '页面';
    try { host = new URL(meta.data.href).hostname || host; } catch {}
    views.push({events, eventCount:events.length, host, tab:group.tab, doc:group.doc, start:meta.timestamp, end:events.at(-1).timestamp, requests:[]});
  }
  if (!views.length) throw new Error('缺少页面元信息或完整快照，无法重建画面。');
  const tabs = new Map();
  for (const view of views.toSorted((a,b) => a.start - b.start)) {
    if (!tabs.has(view.tab)) tabs.set(view.tab, []);
    tabs.get(view.tab).push(view);
  }
  for (const record of records) {
    const tab = tabs.get(JSON.stringify([record.recordingId, record.tabInstanceId]));
    if (!tab || !record.request || !record.response) continue;
    const req = requestTimes(record, marks.get(record.requestKey));
    if (!Number.isFinite(req.start)) continue;
    const matches = record.documentId ? tab.filter(view => view.doc === record.documentId) : [];
    if (record.chromeFrameId === 0 && record.documentId && !matches.length && tab.every(view => view.doc)) continue;
    const candidates = matches.length ? matches : tab;
    const view = candidates.findLast(view => view.start <= req.start) || candidates[0];
    view.requests.push(req);
    view.end = Math.max(view.end, req.start, Number.isFinite(req.response) ? req.response : req.start, Number.isFinite(req.end) ? req.end : req.start);
  }
  for (const view of views) {
    view.requests.sort((a,b) => a.start - b.start);
    // 保留最后一次画面，直到本页最后一条请求结束。原始录制不变。
    if (view.end > view.events.at(-1).timestamp) view.events.push({type:5, timestamp:Math.ceil(view.end), data:{tag:'network-timeline-end',payload:{}}});
    view.duration = view.events.at(-1).timestamp - view.start;
  }
  return { views:views.sort((a,b) => b.duration - a.duration || b.eventCount - a.eventCount), skipped:groups.size - views.length };
}
