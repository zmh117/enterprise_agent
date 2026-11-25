const reasons = {
  captured:'已保存', empty:'正文为空', not_applicable:'不适用', truncated:'仅保存了部分正文',
  excluded_by_policy:'采集策略排除了正文', unavailable:'正文不可用',
  incomplete_target_closed:'页面关闭时尚未采集完成', incomplete_session_stopped:'录制结束时尚未采集完成',
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function offset(ms) {
  const value = Math.round(Math.abs(ms) / 100);
  return (ms < 0 ? '−' : '') + String(Math.floor(value / 600)).padStart(2, '0') + ':' +
    ((value % 600) / 10).toFixed(1).padStart(4, '0');
}

function statusAt(req, now) {
  if (now < req.start) return '尚未发起';
  const {record, response, end} = req;
  const parts = [];
  if (record.response.httpStatus !== 'unknown' && record.response.httpStatus != null &&
      (!Number.isFinite(response) || now >= response)) {
    parts.push('HTTP ' + record.response.httpStatus);
    if (!Number.isFinite(response)) parts.push('响应时间未知');
  }
  if (Number.isFinite(end) && now >= end && record.networkOutcome === 'failed') parts.push('请求失败');
  if (parts.length) return parts.join(' · ');
  if (now < response || now < end) return '等待响应';
  return record.networkOutcome === 'incomplete' ? '记录不完整' : '状态未知';
}

function field(parent, title, text) {
  parent.append(element('h3', title));
  const pre = element('pre', text);
  parent.append(pre);
  return pre;
}

function parameters(params) {
  return Array.from(params, ([key, value]) => key + ' = ' + value).join('\n');
}

function body(parent, title, side, readBody, asForm = false) {
  const message = reasons[side.bodyCaptureStatus] || '采集状态未知';
  const pre = field(parent, title, message + (side.bodyCaptureReason ? '（' + side.bodyCaptureReason + '）' : ''));
  if (!side.bodyRef) return;
  pre.textContent = '正在读取…';
  // 捕获具体 DOM 节点，快速切换请求或回退进度时不会写到别的详情上。
  Promise.resolve().then(() => readBody(side.bodyRef)).then(text => {
    const truncated = side.bodyCaptureStatus === 'truncated' ? '【仅保存部分正文】\n' : '';
    pre.textContent = truncated + (text || '正文为空');
    if (asForm && text) field(parent, '表单参数', parameters(new URLSearchParams(text)));
  }).catch(error => { pre.textContent = '正文读取失败：' + error.message; });
}

function pathInfo(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch {}
  const path = url?.pathname ?? rawUrl.split(/[?#]/, 1)[0];
  let decoded = path;
  try { decoded = decodeURIComponent(path); } catch {}
  return {url, path:path.toLowerCase(), decoded:decoded.toLowerCase()};
}

function requestRow(req, view, url, readBody, seek) {
  const {record} = req;
  const {request, response} = record;
  const entry = element('div', undefined, 'request-entry');
  const details = element('details');
  const summary = element('summary', '详情');
  const button = element('button', undefined, 'seek-request');
  button.type = 'button';
  button.title = '跳到请求发起时的画面并暂停';
  const time = offset(req.start - view.start);
  const endpoint = url ? url.host + url.pathname : request.url;
  button.setAttribute('aria-label', '定位到 ' + time + ' 的 ' + request.method + ' ' + endpoint);
  summary.setAttribute('aria-label', request.method + ' ' + endpoint + ' 的详情');
  const code = element('span', '', 'code');
  button.append(element('span', time, 'offset'), element('span', request.method, 'method'),
    element('span', endpoint, 'endpoint'), code);
  button.addEventListener('click', () => {
    seek(req.start);
    details.open = true;
  });
  details.append(summary);
  entry.append(button, details);
  let now = req.start, info, responseInfo;
  function updateResponse() {
    if (!responseInfo) return;
    responseInfo.replaceChildren();
    field(responseInfo, '响应状态', statusAt(req, now));
    if (now < req.start || now < req.end || now < req.response) {
      field(responseInfo, '响应正文', '回放尚未到达响应完成时间。');
    } else {
      if (record.error) field(responseInfo, '网络错误', record.error);
      body(responseInfo, '响应正文', response, readBody);
    }
  }
  details.addEventListener('toggle', () => {
    info?.remove();
    info = responseInfo = undefined;
    if (!details.open) return;
    info = element('div', undefined, 'request-info');
    details.append(info);
    if (req.start < view.events[1].timestamp) info.append(element('p', '请求早于首个页面快照，定位时显示最早可用的画面。'));
    field(info, '请求 URL', request.url);
    field(info, '查询参数', url?.search ? parameters(url.searchParams) : '无');
    const form = (request.headers?.['content-type'] || '').toLowerCase().includes('application/x-www-form-urlencoded');
    const requestInfo = element('div');
    info.append(requestInfo);
    body(requestInfo, '请求正文', request, readBody, form);
    responseInfo = element('div');
    info.append(responseInfo);
    updateResponse();
  });
  return {node:entry, update(time) {
    now = time;
    code.textContent = statusAt(req, now);
    updateResponse();
  }};
}

export function mountNetwork(view, readBody, seek) {
  const list = document.querySelector('#requests'), count = document.querySelector('#count');
  const empty = document.querySelector('#network-empty');
  const filter = document.querySelector('#path-filter');
  const paths = new Map(view.requests.map(req => [req, pathInfo(req.record.request.url)]));
  const changes = [];
  for (const req of view.requests) {
    changes.push({time:req.start, req});
    if (Number.isFinite(req.response)) changes.push({time:req.response, req});
    if (Number.isFinite(req.end)) changes.push({time:req.end, req});
  }
  changes.sort((a,b) => a.time - b.time);
  const visible = new Map();
  let cursor = 0, now = view.start, query, matches;
  function updateRow(req, parent) {
    let row = visible.get(req);
    if (req.start > now && !query) {
      row?.node.remove();
      visible.delete(req);
      return;
    }
    if (!row) {
      row = requestRow(req, view, paths.get(req).url, readBody, seek);
      visible.set(req, row);
      parent.prepend(row.node);
    }
    row.update(now);
  }
  function updateCount() {
    count.textContent = query ? '匹配 ' + matches.size + ' 条' : visible.size + ' / ' + view.requests.length + ' 条';
    empty.hidden = visible.size > 0;
    if (!view.requests.length) empty.textContent = '这段页面录制没有采集到接口请求。';
    else if (query) empty.textContent = '没有匹配的接口路径。';
    else empty.textContent = '首条请求出现在 ' + offset(view.requests[0].start - view.start) + '。';
  }
  function applyFilter() {
    const nextQuery = filter.value.trim().toLowerCase();
    if (nextQuery === query) return;
    query = nextQuery;
    matches = new Set();
    visible.clear();
    const fragment = document.createDocumentFragment();
    for (const [req, {path, decoded}] of paths) {
      if (query && !path.includes(query) && !decoded.includes(query)) continue;
      matches.add(req);
      updateRow(req, fragment);
    }
    list.replaceChildren(fragment);
    updateCount();
  }
  function sync(elapsed) {
    now = view.start + Math.min(view.duration, Math.max(0, elapsed));
    const touched = new Set();
    while (cursor < changes.length && changes[cursor].time <= now) touched.add(changes[cursor++].req);
    while (cursor > 0 && changes[cursor - 1].time > now) touched.add(changes[--cursor].req);
    if (!touched.size) return;
    for (const req of touched) if (matches.has(req)) updateRow(req, list);
    updateCount();
  }
  filter.oninput = applyFilter;
  applyFilter();
  sync(0);
  return sync;
}
