// Isolated content script. All account data, questions and answers live in the extension frame.
async function mount() {
  const state = globalThis as typeof globalThis & {mesFloatingMounted?: boolean};
  if (window !== top || state.mesFloatingMounted) return;
  state.mesFloatingMounted = true;
  const host = document.createElement('div');
  host.dataset.mesAgentHost = '';
  host.className = 'rr-block';
  const root = host.attachShadow({mode: 'closed'});
  const style = document.createElement('style');
  style.textContent = `
    :host{all:initial!important;position:fixed!important;z-index:2147483646!important;display:block!important;right:var(--mes-right,16px)!important;bottom:var(--mes-bottom,16px)!important;color-scheme:light}
    *{box-sizing:border-box}button{font:inherit;cursor:pointer}
    .launch{display:grid;place-items:center;width:50px;height:50px;border:1px solid #ffffff60;border-radius:50%;
      background:#242424;color:white;box-shadow:0 5px 18px #16161638}
    .launch{cursor:grab;touch-action:none;user-select:none}.launch:active{cursor:grabbing}
    .launch svg{width:25px;height:25px;pointer-events:none}.launch:hover, .launch:focus-visible{background:#404040}
    .card{width:min(402px,calc(100vw - 16px));height:min(540px,calc(100dvh - 16px));display:flex;flex-direction:column;
      border:1px solid #dddde2;background:white;border-radius:14px;overflow:hidden;box-shadow:0 10px 40px #15343638}
    header{display:flex;align-items:center;justify-content:space-between;min-height:45px;padding:0 9px 0 16px;
      background:#fff;color:#222;border-bottom:1px solid #ebebeb;font:600 15px/1.4 system-ui,sans-serif;cursor:grab;touch-action:none;user-select:none}
    header:active{cursor:grabbing}header button{background:none;color:#555;border:0;border-radius:6px;font-size:21px;width:32px;height:32px}
    header button:hover{background:#f0f0f0}iframe{display:block;flex:1;min-height:0;width:100%;border:0}
    [hidden]{display:none!important}
  `;
  const launcher = document.createElement('button');
  launcher.className = 'launch';
  launcher.title = '点击询问 采集助手，拖动可移动图标'; launcher.setAttribute('aria-label', '询问 采集助手');
  launcher.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 11.5a8.5 8.5 0 0 1-8.8 8.1c-1.5 0-2.6-.2-3.9-.8L3.5 20l1.3-4.4a7.3 7.3 0 0 1-1.4-4.1c0-4.6 3.9-8.1 8.8-8.1S21 6.9 21 11.5Z"/><path d="M8 11.5h8"/></svg>';
  const card = document.createElement('section');
  card.className = 'card'; card.hidden = true; card.setAttribute('aria-label','采集助手');
  const header = document.createElement('header');
  header.textContent = '采集助手'; header.title = '拖动标题栏以移动窗口';
  const close = document.createElement('button'); close.textContent = '−';
  close.title = '收起对话'; close.setAttribute('aria-label', close.title);
  header.append(close); card.append(header); root.append(style, card, launcher);
  let anchor = {right: 16, bottom: 16};
  let open = false;
  let frame: HTMLIFrameElement | undefined;
  const place = () => {
    const box = (open ? card : launcher).getBoundingClientRect();
    const right = Math.max(0, Math.min(anchor.right, innerWidth - box.width));
    const bottom = Math.max(0, Math.min(anchor.bottom, innerHeight - box.height));
    host.style.setProperty('--mes-right', right + 'px','important');
    host.style.setProperty('--mes-bottom', bottom + 'px','important');
  };
  const remove = () => {
    chrome.runtime.onMessage.removeListener(onMessage);
    window.removeEventListener('resize', place);
    host.remove(); state.mesFloatingMounted = false;
  };
  const onMessage = (m: {type?:string}) => { if (m.type === 'float.remove') remove(); };
  chrome.runtime.onMessage.addListener(onMessage);
  const auth = await chrome.runtime.sendMessage({type:'float.prepare'}).catch(() => null);
  if (!state.mesFloatingMounted || typeof auth?.ticket !== 'string') {remove(); return;}
  let launcherDragged = false;
  launcher.onclick = e => {
    if (launcherDragged && e.detail !== 0) return;
    if (!frame) {
      frame = document.createElement('iframe');
      frame.title = '采集助手对话';
      frame.src = chrome.runtime.getURL('floating.html') + '#' + auth.ticket;
      card.append(frame);
    }
    open = true; launcher.hidden = true; card.hidden = false;
    launcher.setAttribute('aria-expanded','true'); place(); close.focus();
  };
  close.onclick = () => {
    open = false; card.hidden = true; launcher.hidden = false;
    launcher.setAttribute('aria-expanded','false'); place(); launcher.focus({preventScroll:true});
  };
  launcher.setAttribute('aria-expanded','false');
  for (const handle of [launcher, header]) {
    let drag: {pointer: number; x: number; y: number; right: number; bottom: number; moved: boolean} | undefined;
    handle.onpointerdown = e => {
      if (e.target === close || e.button !== 0 || !e.isPrimary) return;
      if (handle === launcher) launcherDragged = false;
      const box = host.getBoundingClientRect();
      drag = {pointer:e.pointerId, x:e.clientX, y:e.clientY,
        right:innerWidth - box.right, bottom:innerHeight - box.bottom, moved:false};
      handle.setPointerCapture(e.pointerId);
    };
    handle.onpointermove = e => {
      if (!drag || drag.pointer !== e.pointerId) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 5) return;
      drag.moved = true;
      if (handle === launcher) launcherDragged = true;
      anchor = {right:drag.right - dx, bottom:drag.bottom - dy};
      place();
    };
    handle.onlostpointercapture = e => { if (drag?.pointer === e.pointerId) drag = undefined; };
  }
  document.documentElement.append(host); window.addEventListener('resize', place); place();
}
void mount();
