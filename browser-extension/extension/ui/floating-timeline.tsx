import { useLayoutEffect, useRef } from 'react';
import { ActivityView, followActivity, type Activity } from './job-activity';
import { createRoot } from 'react-dom/client';
import { AssistantRuntimeProvider, MessagePrimitive, ThreadPrimitive, useAuiState,
  useExternalStoreRuntime, type ThreadMessageLike, type AppendMessage } from '@assistant-ui/react';
import { StreamdownTextPrimitive } from '@assistant-ui/react-streamdown';
import type { AgentTimeline } from './agent-panel';
import { copyReply } from './reply-copy';
import { explain } from './agent-panel';
import { messageTime, PlatformError, watchAnswer, type ReplyTiming } from './agent-answer';

function Markdown() {
  const running = useAuiState(s => s.message.status?.type === 'running');
  return <StreamdownTextPrimitive smooth={running} caret="block" controls={false} skipHtml
    remarkRehypeOptions={{allowDangerousHtml:false}}
    allowedElements={['p','h1','h2','h3','h4','h5','h6','em','strong','del','a','img','br','hr','blockquote','ul','ol','li','table','thead','tbody','tr','th','td','pre','code']}
    plugins={{code:false}} components={{
      strong: ({children}) => <strong>{children}</strong>,
      em: ({children}) => <em>{children}</em>,
      del: ({children}) => <del>{children}</del>,
      img: ({alt}) => <>{alt}</>,
      a: ({href, children}) => href && /^https?:\/\//i.test(href)
        ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <>{children}</>,
    }} />;
}
function UserMessage() {
  const time = useAuiState(s => s.message.metadata.custom.time as string | undefined);
  return <MessagePrimitive.Root className="question chat-question" aria-label="你发送的消息"
    data-message-time={time} title={time && '提问时间 ' + time} tabIndex={time ? 0 : undefined}><MessagePrimitive.Parts /></MessagePrimitive.Root>;
}
function ActivityBlock({data, live}: {data?: Activity; live: boolean}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<ActivityView | null>(null);
  useLayoutEffect(() => {
    if (!view.current) {
      view.current = new ActivityView();
      host.current!.append(view.current.element);
    }
    if (data) view.current.update(data, live); else view.current.clear();
  }, [data, live]);
  return <div ref={host} />;
}
function AssistantMessage() {
  const meta = useAuiState(s => s.message.metadata.custom);
  const text = useAuiState(s => s.message.content.find(part => part.type === 'text')?.text ?? '');
  const timing = meta.timing as ReplyTiming | undefined;
  return <MessagePrimitive.Root className="answer chat-reply" data-complete={meta.copyable === true} aria-label="Agent 回复"
    data-message-time={timing?.time} title={timing?.time && '回答时间 ' + timing.time}>
    <div className="reply-byline">Agent<small>{String(meta.label || '正在连接')}</small>
      {timing?.duration && <small className="reply-duration">· 用时 {timing.duration}</small>}</div>
    <ActivityBlock data={meta.activity as Activity | undefined} live={meta.live === true} />
    <div className="answer-body"><MessagePrimitive.Parts components={{Text:Markdown}} /></div>
    {meta.copyable === true && <button type="button" className="reply-copy" aria-label="复制回复"
      title="复制回复" aria-live="polite" onClick={e => void copyReply(e.currentTarget, text)} />}
    {typeof meta.retry === 'function' && <button onClick={() => (meta.retry as () => void)()}>继续接收</button>}
  </MessagePrimitive.Root>;
}
const convertMessage = (message: ThreadMessageLike) => message;
async function onNew(message: AppendMessage) {
  const question = document.querySelector<HTMLTextAreaElement>('#agent-question')!;
  const send = document.querySelector<HTMLButtonElement>('#agent-send')!;
  if (send.disabled) return;
  question.value = message.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
  send.click();
}
function Thread({messages}: {messages: ThreadMessageLike[]}) {
  const runtime = useExternalStoreRuntime({messages, convertMessage, onNew});
  return <AssistantRuntimeProvider runtime={runtime}>
    <ThreadPrimitive.Root><ThreadPrimitive.Messages components={{UserMessage, AssistantMessage}} /></ThreadPrimitive.Root>
  </AssistantRuntimeProvider>;
}

type Row = {job: string; question?: string; askedTime?: string; answer: string; timing?: ReplyTiming; state: string; done: boolean; activity?: Activity; live?: boolean; forbidden?: boolean; retry?: () => void};
export function createTimeline(element: HTMLElement): AgentTimeline {
  const content = document.createElement('div');
  element.append(content);
  const root = createRoot(content);
  const rows = new Map<string, Row>();
  let order: string[] = [];
  let atBottom = true;
  element.addEventListener('scroll', () => {
    atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
  });
  const observer = new ResizeObserver(() => {
    if (atBottom && element.clientHeight) element.scrollTop = element.scrollHeight;
  });
  // React owns the thread, the scroll container belongs to the extension.
  function render() {
    const messages: ThreadMessageLike[] = [];
    for (const id of order) {
      const row = rows.get(id)!;
      if (row.question && !row.forbidden) messages.push({id: id + '/user', role:'user', content:row.question, metadata:{custom:{time:row.askedTime}}});
      messages.push({id, role:'assistant', content:row.answer,
        status: row.done ? {type:'complete', reason:'stop'} : {type:'running'},
        metadata:{custom:{label:row.state, timing:row.timing, retry:row.retry, activity:row.activity, live:row.live, copyable:row.done && !row.retry && !!row.answer.trim()}}});
    }
    root.render(<Thread messages={messages} />);
  }
  observer.observe(content);
  return {
    clear() { rows.clear(); order = []; atBottom = true; render(); },
    questions(page, prepend) {
      for (const item of page) {
        const row = rows.get(item.job_id);
        if (row && !row.forbidden) {
          row.question = item.question;
          row.askedTime = messageTime(item.asked_at);
        }
      }
      const ids = page.map(row => row.job_id);
      order = prepend ? [...new Set([...ids, ...order])] : [...order.filter(id => !ids.includes(id)), ...ids];
      render();
    },
    follow(job, platform, signal) {
      if (rows.has(job)) return;
      const row: Row = {job, answer:'', state:'正在连接', done:false};
      rows.set(job, row); order.push(job);
      const run = async () => {
        row.retry = undefined; row.done = false; row.state = '正在连接'; render();
        const updates = followActivity(job, platform.request.bind(platform), signal, (activity, live) => {
          Object.assign(row, {activity, live}); render();
        });
        try {
          await watchAnswer(job, platform.request.bind(platform), signal, (answer, state, done, timing) => {
            updates.observe(done);
            Object.assign(row, {answer, state, done, timing}); render();
          });
        } catch (error) {
          updates.stop(); row.activity = undefined;
          if (signal.aborted) return;
          if (error instanceof PlatformError && [401,403,404].includes(error.status)) {
            row.forbidden = true; row.answer = ''; row.question = undefined;
          }
          row.state = explain(error); row.done = true;
          if (!(error instanceof PlatformError && [403,404].includes(error.status))) row.retry = run;
          render();
        }
      };
      void run();
    },
  };
}
