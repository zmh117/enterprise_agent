import MarkdownIt from 'markdown-it';
import { createParser } from 'eventsource-parser';

const markdown = new MarkdownIt({ html: false, linkify: false });
const validLink = markdown.validateLink.bind(markdown);
markdown.validateLink = (url) => /^https?:\/\//i.test(url) && validLink(url);
markdown.renderer.rules.image = (tokens, index) =>
  markdown.utils.escapeHtml(tokens[index]!.content);
markdown.renderer.rules.link_open = (
  tokens,
  index,
  options,
  _env,
  renderer,
) => {
  tokens[index]!.attrSet('target', '_blank');
  tokens[index]!.attrSet('rel', 'noopener noreferrer');
  return renderer.renderToken(tokens, index, options);
};

import { PlatformError } from '../platform';
export { PlatformError } from '../platform';

export type PlatformFetch = (
  path: string,
  options: RequestInit,
) => Promise<Response>;

const statuses: Record<string, string> = {
  queued: '排队中',
  analyzing: '回答中',
  retrying: '正在重试',
  completed: '已完成',
  failed: '回答失败',
  cancelled: '已取消',
  timeout: '已超时',
};

function statusLabel(value: unknown): string {
  if (typeof value !== 'string' || !Object.hasOwn(statuses, value))
    throw new Error('回答状态无效');
  return statuses[value]!;
}

const localTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

export function messageTime(value: unknown): string | undefined {
  if (typeof value !== 'string') return;
  const time = Date.parse(value);
  return Number.isFinite(time) ? localTime.format(time) : undefined;
}

function taskDuration(ms: unknown): string | undefined {
  if (typeof ms !== 'number' || !Number.isSafeInteger(ms) || ms < 0) return;
  const seconds = Math.floor(ms / 1000);
  if (!seconds) return '不足 1 秒';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const parts = [];
  if (hours) parts.push(hours + ' 小时');
  if (minutes) parts.push(minutes + ' 分');
  if (seconds % 60) parts.push(seconds % 60 + ' 秒');
  return parts.join(' ');
}

export type ReplyTiming = {time?: string; duration?: string};

function textField(value: unknown, max = 524288): string {
  if (typeof value !== 'string' || value.length > max * 2)
    throw new Error('回答数据无效');
  return value;
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const stop = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', stop);
      resolve();
    }, ms);
    signal.addEventListener('abort', stop, { once: true });
  });
}

export async function displayAnswer(
  job: string,
  call: PlatformFetch,
  body: HTMLElement,
  label: HTMLElement,
  signal: AbortSignal,
  onStatus?: (done: boolean, timing?: ReplyTiming) => void,
): Promise<string> {
  let finalAnswer = '';
  await watchAnswer(job, call, signal, (source, status, done, timing) => {
    onStatus?.(done, timing);
    if (done) finalAnswer = source;
    label.textContent = status;
    body.innerHTML = markdown.render(source);
  });
  return finalAnswer;
}

export async function watchAnswer(
  job: string, call: PlatformFetch, signal: AbortSignal,
  update: (source: string, status: string, done: boolean, timing?: ReplyTiming) => void,
): Promise<void> {
  let status = '';
  let timing: ReplyTiming | undefined;
  const path = '/jobs/' + encodeURIComponent(job);
  let source = '',
    cursor = 0,
    attempt: string | null = null,
    done = false,
    recover = true;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dirty = false;
  function render() {
    clearTimeout(timer);
    timer = undefined;
    if (!dirty || signal.aborted) return;
    update(source, status, done, timing);
    dirty = false;
  }
  function changed() {
    dirty = true;
    if (timer === undefined) timer = setTimeout(render, 40);
  }
  function apply(event: Record<string, unknown>, snapshot: boolean) {
    const id = snapshot ? event.through_cursor : event.id;
    if (
      event.job_id !== job ||
      typeof id !== 'number' ||
      !Number.isSafeInteger(id) ||
      id < (snapshot ? 0 : 1)
    )
      throw new Error('回答游标无效');
    if (!snapshot && id <= cursor) return;
    const nextAttempt = event.attempt_id;
    if (typeof nextAttempt !== 'string' && nextAttempt !== null)
      throw new Error('回答尝试无效');
    if (snapshot) {
      source = '';
      attempt = nextAttempt;
    } else if (
      event.event !== 'reset' &&
      attempt !== null &&
      nextAttempt !== attempt
    ) {
      throw new Error('回答尝试不匹配');
    }
    const kind = snapshot ? event.state : event.event;
    switch (kind) {
      case 'reset':
        attempt = nextAttempt;
        source = '';
        status = statuses.retrying!;
        break;
      case 'status':
        attempt = nextAttempt;
        status = statusLabel(event.status);
        break;
      case 'answer_delta':
        if (!nextAttempt) throw new Error('回答尝试缺失');
        attempt = nextAttempt;
        if (event.replace === true) source = '';
        source += textField(event.text, 32768);
        if (source.length > 1048576) throw new Error('回答超过容量');
        status = statuses.analyzing!;
        break;
      case 'failed':
        source = '';
        status = statusLabel(event.reason);
        done = true;
        break;
      case 'completed':
        source = textField(event.final_answer);
        timing = {time: messageTime(event.answered_at), duration: taskDuration(event.duration_ms)};
        status = statuses.completed!;
        done = true;
        break;
      case 'queued':
      case 'retrying':
      case 'analyzing':
        if (!snapshot) throw new Error('回答事件无效');
        source = textField(event.draft);
        status = statusLabel(kind);
        break;
      default:
        throw new Error('回答事件无效');
    }
    cursor = id;
    changed();
    if (snapshot || done || kind === 'reset') render();
  }

  let retries = 0;
  try {
    while (!done) {
      signal.throwIfAborted();
      const before = cursor;
      try {
        if (recover) {
          const res = await call(path, { signal });
          const snap = await res.json();
          signal.throwIfAborted();
          apply(snap, true);
          recover = false;
          if (done) break;
        }
        const res = await call(path + '/events', {
          signal,
          headers: {
            Accept: 'text/event-stream',
            'Last-Event-ID': String(cursor),
          },
        });
        if (
          res.headers.get('content-type')?.split(';')[0] !==
            'text/event-stream' ||
          !res.body
        )
          throw new Error('平台未返回回答流');
        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8', { fatal: true });
        const parser = createParser({
          maxBufferSize: 8 * 1024 * 1024,
          onError(error) {
            throw error;
          },
          onEvent(frame) {
            if (done) return;
            const event = JSON.parse(frame.data);
            if (frame.event !== event.event || frame.id !== String(event.id))
              throw new Error('回答事件标识不一致');
            apply(event, false);
          },
        });
        try {
          while (!done) {
            const bytes = await reader.read();
            signal.throwIfAborted();
            if (bytes.done) break;
            parser.feed(decoder.decode(bytes.value, { stream: true }));
          }
        } finally {
          await reader.cancel().catch(() => {});
          reader.releaseLock();
          render(); // Confirm the displayed Markdown before resuming from its cursor.
        }
      } catch (error) {
        signal.throwIfAborted();
        if (error instanceof PlatformError) {
          if (error.status === 409 && error.code === 'cursor_invalid')
            recover = true;
          else if (error.status < 500) throw error;
        } else if (!(error instanceof TypeError)) {
          // Recover a malformed or incomplete stream from a consistent server snapshot.
          recover = true;
        }
      }
      if (!done) {
        retries = cursor > before ? 1 : retries + 1;
        if (retries > 6) throw new Error('连接中断，请点击继续接收');
        status = '连接中断，正在续读…';
        dirty = true;
        render();
        await delay(Math.min(5000, 200 * 2 ** (retries - 1)), signal);
      }
    }
  } finally {
    clearTimeout(timer);
  }
}
