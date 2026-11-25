import assert from 'node:assert/strict';
import test from 'node:test';
import { displayAnswer, PlatformError } from '../extension/ui/agent-answer';

const job = 'job-1',
  attempt = 'attempt-1';
function frame(id: number, event: string, data: object, a = attempt) {
  return `id: ${id}\r\nevent: ${event}\r\ndata: ${JSON.stringify({ job_id: job, attempt_id: a, id, event, ...data })}\r\n\r\n`;
}
function stream(text: string) {
  const encoded = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let start = 0; start < encoded.length; start += 3)
          controller.enqueue(encoded.slice(start, start + 3));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } },
  );
}
function elements() {
  const body = { innerHTML: '' } as HTMLElement,
    state = { textContent: '' } as HTMLElement;
  return { body, state };
}
const snapshot = (cursor: number, draft: string) =>
  Response.json({
    job_id: job,
    through_cursor: cursor,
    attempt_id: attempt,
    state: 'analyzing',
    draft,
  });

test('UTF-8 分片、重复游标、reset、跨片 Markdown 和安全终态', async () => {
  const { body, state } = elements();
  const next = 'attempt-2';
  const final =
    '**通过**\n\n|列|\n|---|\n|行|\n\n```txt\n正文\n```\n\n<b>示例</b> [跳转](javascript:void) ![图片](https://example.invalid/x)';
  const events =
    frame(2, 'answer_delta', { text: '旧草稿' }) +
    frame(2, 'answer_delta', { text: '重复' }) +
    frame(3, 'reset', {}, next) +
    frame(4, 'answer_delta', { text: final.slice(0, 3) }, next) +
    frame(5, 'answer_delta', { text: final.slice(3) }, next) +
    frame(6, 'completed', { final_answer: final }, next);
  await displayAnswer(
    job,
    async (path) =>
      path.endsWith('/events') ? stream(events) : snapshot(1, ''),
    body,
    state,
    new AbortController().signal,
  );
  assert.match(body.innerHTML, /<strong>通过<\/strong>/);
  assert.match(body.innerHTML, /<table>/);
  assert.match(body.innerHTML, /<pre><code/);
  assert.match(body.innerHTML, /&lt;b&gt;/);
  assert.doesNotMatch(body.innerHTML, /旧草稿|重复|<img|<a\s/);
  assert.equal(state.textContent, '已完成');
});

test('游标失效时用一致快照续读，最终失败清除草稿', async () => {
  const { body, state } = elements();
  let reads = 0;
  const requested: number[] = [];
  await displayAnswer(
    job,
    async (path, options) => {
      if (!path.endsWith('/events'))
        return ++reads === 1 ? snapshot(2, '旧') : snapshot(7, '新');
      const cursor = Number(new Headers(options.headers).get('Last-Event-ID'));
      requested.push(cursor);
      if (cursor === 2) throw new PlatformError(409, 'cursor_invalid');
      return stream(frame(8, 'failed', { reason: 'timeout' }));
    },
    body,
    state,
    new AbortController().signal,
  );
  assert.deepEqual(requested, [2, 7]);
  assert.equal(body.innerHTML, '');
  assert.equal(state.textContent, '已超时');
});

test('半帧 EOF 只确认完整事件，按最后游标续读', async () => {
  const { body, state } = elements();
  const cursors: number[] = [];
  await displayAnswer(
    job,
    async (path, opts) => {
      if (!path.endsWith('/events')) return snapshot(1, '');
      cursors.push(Number(new Headers(opts.headers).get('Last-Event-ID')));
      return cursors.length === 1
        ? stream(
            frame(2, 'answer_delta', { text: '**合' }) +
              frame(3, 'answer_delta', { text: '成**' }).slice(0, -4),
          )
        : stream(
            frame(3, 'answer_delta', { text: '成**' }) +
              frame(4, 'completed', { final_answer: '**合成**' }),
          );
    },
    body,
    state,
    new AbortController().signal,
  );
  assert.deepEqual(cursors, [1, 2]);
  assert.equal(body.innerHTML.trim(), '<p><strong>合成</strong></p>');
  assert.equal(state.textContent, '已完成');
});
