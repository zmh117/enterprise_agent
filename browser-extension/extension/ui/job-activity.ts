import { PlatformError, type PlatformFetch } from './agent-answer';

type Tool = {
  id: string; tool_name: string; status: string; created_at: string; duration_ms: number;
  summary: Record<string, unknown>;
};
export type Activity = { process: string; tools: Tool[]; unavailable?: boolean };

export function followActivity(job: string, call: PlatformFetch, signal: AbortSignal,
  update: (data: Activity, live: boolean) => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let request: AbortController | undefined;
  let started = false;
  let finished = false;
  const path = '/jobs/' + encodeURIComponent(job) + '/activity';
  async function read(live: boolean) {
    const turn = new AbortController();
    request = turn;
    const active = AbortSignal.any([signal, turn.signal]);
    try {
      const data: Activity = await (await call(path, {signal: active})).json();
      if (!active.aborted) update(data, live);
    } catch (error) {
      if (!active.aborted) {
        update({process: '', tools: [], unavailable: true}, false);
        if (error instanceof PlatformError && [401,403,404].includes(error.status)) finished = true;
      }
    } finally {
      if (!active.aborted && !finished) timer = setTimeout(() => void read(true), 1800);
    }
  }
  function stop() {
    finished = true;
    clearTimeout(timer);
    request?.abort();
  }
  signal.addEventListener('abort', stop, {once:true});
  return {
    observe(done: boolean) {
      if (signal.aborted) return;
      if (done) {
        stop();
        void read(started);
      } else if (!started) {
        started = true;
        void read(false);
      }
    },
    stop,
  };
}

const statusNames: Record<string, string> = {
  SUCCEEDED:'完成', SUCCESS:'完成', COMPLETED:'完成', FAILED:'失败', DENIED:'已拒绝',
  RUNNING:'运行中', STARTED:'运行中', PENDING:'等待中', CANCELLED:'已取消',
};

function toolSummary(tool: Tool) {
  const s = tool.summary;
  const parts = [];
  if (typeof s.error_code === 'string') parts.push('错误码 ' + s.error_code);
  if (typeof s.returned === 'number') parts.push('返回 ' + s.returned + ' 条');
  else if (typeof s.row_count === 'number') parts.push(s.row_count + ' 行');
  else if (typeof s.count === 'number') parts.push(s.count + ' 项');
  if (typeof s.total === 'number') parts.push('共 ' + s.total + ' 条');
  const bytes = s.content_bytes ?? s.size_bytes;
  if (typeof bytes === 'number') parts.push(bytes + ' 字节');
  if (s.truncated === true) parts.push('结果已截断');
  if (s.committed === true) parts.push('已提交');
  if (s.selected === true) parts.push('已选中');
  return parts.join(' · ');
}

function fold(title: string) {
  const box = document.createElement('details');
  const label = document.createElement('summary');
  label.textContent = title;
  box.append(label);
  return {box, label};
}

function reveal(node: HTMLElement, text: string, animate: boolean) {
  if (node.dataset.full === text) return;
  node.dataset.full = text;
  if (!animate || !node.closest('details')?.open || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    node.textContent = text;
    return;
  }
  node.textContent = '';
  const start = performance.now();
  const chars = Array.from(text);
  function tick(now: number) {
    if (node.dataset.full !== text || !node.isConnected) return;
    const fraction = Math.min(1, (now - start) / Math.min(650, chars.length * 16 || 1));
    node.textContent = chars.slice(0, Math.ceil(fraction * chars.length)).join('');
    if (fraction < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

export class ActivityView {
  readonly element = document.createElement('div');
  private process = fold('执行过程');
  private tools = fold('工具调用');
  private prose = document.createElement('div');
  private list = document.createElement('ol');
  private rows = new Map<string, HTMLLIElement>();
  private pending = new Set<HTMLElement>();
  constructor() {
    this.element.className = 'job-activity';
    this.prose.className = 'process-text';
    this.list.setAttribute('aria-label','工具调用时间线');
    this.process.box.append(this.prose);
    this.tools.box.append(this.list);
    this.tools.box.ontoggle = () => {
      if (!this.tools.box.open) return;
      for (const node of this.pending) {
        const text = node.dataset.full ?? '';
        delete node.dataset.full;
        reveal(node, text, true);
      }
      this.pending.clear();
    };
    this.element.append(this.process.box, this.tools.box);
    this.clear();
  }
  clear() {
    this.pending.clear();
    this.rows.clear();
    this.list.replaceChildren();
    this.prose.textContent = '';
    this.process.box.open = this.tools.box.open = false;
    this.element.hidden = true;
  }
  update(data: Activity, live: boolean) {
    this.element.hidden = !data.process && !data.tools.length && !data.unavailable;
    this.process.box.hidden = !data.process;
    this.prose.textContent = data.process;
    this.tools.box.hidden = !data.tools.length && !data.unavailable;
    this.tools.label.textContent = data.unavailable ? '工具记录暂不可用' : '工具调用 · ' + data.tools.length;
    const ids = new Set(data.tools.map(tool => tool.id));
    for (const [key, row] of this.rows) if (!ids.has(key)) { row.remove(); this.rows.delete(key); }
    for (const tool of data.tools) {
      let row = this.rows.get(tool.id);
      if (!row) {
        row = document.createElement('li');
        row.append(document.createElement('strong'), document.createElement('small'), document.createElement('p'));
        this.rows.set(tool.id,row);
        this.list.append(row);
      }
      const state = statusNames[tool.status.toUpperCase()] ?? tool.status;
      this.text(row.querySelector('strong')!, tool.tool_name, live);
      row.querySelector('small')!.textContent = state + (tool.duration_ms > 0 ? ' · ' + tool.duration_ms + ' ms' : '');
      this.text(row.querySelector('p')!, toolSummary(tool), live);
    }
  }
  private text(node: HTMLElement, text: string, live: boolean) {
    if (live && !this.tools.box.open && text && text !== node.dataset.full) this.pending.add(node);
    reveal(node, text, live);
  }

}
