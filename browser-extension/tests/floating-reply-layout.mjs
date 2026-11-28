import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build } from 'esbuild';
import { chromium } from 'playwright';

// Load the floating page and its production message renderer with a synthetic Job.
const ui = new URL('../extension/ui/', import.meta.url);
const source = name => readFile(new URL(name, ui), 'utf8');
const bundle = await build({
  stdin: {
    contents: "export {createTimeline} from './extension/ui/floating-timeline';",
    resolveDir: process.cwd(),
  },
  bundle: true, write: false, format: 'esm', target: 'chrome125',
  define: { 'process.env.NODE_ENV': '"production"' },
});
const resources = new Map([
  ['/floating.html', ['text/html', (await source('floating.html')).replace('<!-- agent-panel -->', await source('agent-panel.html'))]],
  ['/floating-page.css', ['text/css', await source('floating.css')]],
  ['/chat.css', ['text/css', await source('chat.css')]],
  ['/floating.js', ['text/javascript', bundle.outputFiles[0].text]],
]);
const rows = Array.from({length: 18}, (_, i) => `| ${i + 1} | 检查 | 这是一行用于验证自动换行的合成记录。 |`);
const fields = Array.from({length: 20}, (_, i) => '字段' + (i + 1));
const code = Array.from({length: 32}, (_, i) => `line ${i + 1}`);
const markdown = [
  '| 次序 | 动作 | 说明 |', '| --- | --- | --- |', ...rows,
  '', '表格结束。', '', '## 诊断详情', '', '- 检查代码输出', '',
  '```text', ...code, '```', '', '代码结束。', '',
  fields.join('|'), fields.map(() => '---').join('|'), fields.join('|'),
].join('\n');

const browser = await chromium.launch({executablePath: process.env.MES_TEST_CHROME});
try {
  const page = await browser.newPage({viewport: {width: 420, height: 620}});
  await page.route('https://layout.test/**', route => {
    const file = resources.get(new URL(route.request().url()).pathname);
    return file ? route.fulfill({contentType: file[0], body: file[1]}) : route.abort();
  });
  await page.goto('https://layout.test/floating.html');
  await page.evaluate(async () => {
    const {createTimeline} = await import('/floating.js');
    document.querySelector('#floating-view').hidden = false;
    document.querySelector('#agent-connection').open = false;
    const timeline = createTimeline(document.querySelector('#agent-answers'));
    const job = {job_id: 'layout', attempt_id: 'test'};
    const events = new ReadableStream({start(controller) {
      window.emitLayoutEvent = event => controller.enqueue(new TextEncoder().encode(
        `id: ${event.id}\nevent: ${event.event}\ndata: ${JSON.stringify({...job, ...event})}\n\n`
      ));
    }});
    timeline.follow(job.job_id, {request: async path => {
      if (path.endsWith('/activity')) return Response.json({process: '', tools: []});
      if (path.endsWith('/events')) return new Response(events, {headers: {'Content-Type': 'text/event-stream'}});
      return Response.json({...job, through_cursor: 0, state: 'analyzing', draft: ''});
    }}, new AbortController().signal, () => {});
  });
  const split = markdown.indexOf(rows[8]);
  await page.evaluate(text => window.emitLayoutEvent({id: 1, event: 'answer_delta', text}), markdown.slice(0, split));
  await page.locator('.chat-reply tbody tr:nth-child(8)').waitFor();
  for (const event of [
    {id: 2, event: 'answer_delta', text: markdown.slice(split)},
    {id: 3, event: 'completed', final_answer: markdown},
  ]) {
    await page.evaluate(event => window.emitLayoutEvent(event), event);
    const reply = page.locator(`.chat-reply[data-complete="${event.event === 'completed'}"]`);
    await reply.getByText('代码结束。', {exact: true}).waitFor();
    for (const width of [420, 320, 720]) {
      await page.setViewportSize({width, height: 620});
      const wideTable = reply.getByRole('table').nth(1);
      await wideTable.getByRole('columnheader', {name: '字段20', exact: true}).waitFor();
      const sizes = await wideTable.evaluate(table => {
        const wrapper = table.closest('[data-streamdown="table-wrapper"]');
        const answers = document.querySelector('#agent-answers');
        return {tableWidth: wrapper.scrollWidth, visibleWidth: wrapper.clientWidth,
          threadWidth: answers.scrollWidth, visibleThread: answers.clientWidth};
      });
      assert.ok(sizes.threadWidth <= sizes.visibleThread + 1, 'wide table overflows the conversation');
      if (width === 320) assert.ok(sizes.tableWidth > sizes.visibleWidth, 'wide table should scroll horizontally');
      for (const [selector, nextText] of [['tbody tr:last-child', '表格结束。'], ['pre', '代码结束。']]) {
        const next = reply.getByText(nextText, {exact: true});
        await next.scrollIntoViewIfNeeded();
        const gap = await next.evaluate((node, selector) =>
          node.getBoundingClientRect().top - node.closest('.chat-reply').querySelector(selector).getBoundingClientRect().bottom, selector);
        assert.ok(gap >= -1, `${event.event} / ${width}px / ${selector}: following text overlaps by ${-gap}px`);
      }
    }
  }
  console.log('浮窗长表格、代码块与后文在流式及完成状态下均无重叠（320 / 420 / 720px）');
} finally {
  await browser.close();
}
