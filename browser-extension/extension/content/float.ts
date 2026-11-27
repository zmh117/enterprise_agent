import { captureMenu } from './float-capture-menu';

// Isolated content script. All account data, questions and answers live in the extension frame.
async function mount() {
  const state = globalThis as typeof globalThis & { mesFloatingMounted?: boolean };
  if (window !== top || state.mesFloatingMounted) return;
  state.mesFloatingMounted = true;
  const host = document.createElement('div');
  host.dataset.mesAgentHost = '';
  host.className = 'rr-block';
  const root = host.attachShadow({ mode: 'closed' });
  const style = document.createElement('style');
  style.textContent = `
    :host{all:initial!important;position:fixed!important;z-index:2147483646!important;display:block!important;right:var(--mes-right,16px)!important;bottom:var(--mes-bottom,16px)!important;color-scheme:light}
    *{box-sizing:border-box}button{font:inherit;cursor:pointer}
    .launch{display:grid;place-items:center;width:50px;height:50px;border:1px solid #ffffff60;border-radius:50%;
      position:relative;background:#5947c1;color:white;box-shadow:0 5px 18px #352a6538}
    .launch{cursor:grab;touch-action:none;user-select:none}.launch:active{cursor:grabbing}
    .launch svg{width:25px;height:25px;pointer-events:none}.launch:hover, .launch:focus-visible{background:#4937a9}
    .capture-badge{position:absolute;bottom:-4px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:3px;
      padding:2px 5px;border:1px solid #ddd;border-radius:10px;background:white;color:#292830;white-space:nowrap;font:11px/1.2 system-ui,sans-serif;font-variant-numeric:tabular-nums;pointer-events:none}
    .capture-badge.recording::before{content:'';width:6px;height:6px;background:#be384c;border-radius:50%}
    .capture-menu{position:fixed;inset:auto;margin:0;width:min(218px,calc(100vw - 8px));padding:14px;border:1px solid #dddde2;
      background:white;color:#25242e;border-radius:12px;box-shadow:0 8px 28px #241f3b25;font:14px/1.5 system-ui,sans-serif}
    .capture-menu span{display:block;margin:3px 0 10px;color:#616071;overflow-wrap:anywhere;font-size:13px}
    .capture-menu button{width:100%;min-height:44px;text-align:left;padding:8px 10px;border:0;border-radius:8px;background:#efecff;color:#4836a4;font-weight:600}
    .capture-menu button.stop{background:#fff0f1;color:#92333e}.capture-menu button:disabled{opacity:.65}
    .visually-hidden{position:absolute;clip-path:inset(50%);width:1px;height:1px;overflow:hidden}
    .card{position:fixed;width:min(520px,calc(100vw - 16px));height:min(640px,calc(100dvh - 80px));display:flex;flex-direction:column;
      border:1px solid #dddde2;background:white;border-radius:14px;overflow:hidden;box-shadow:0 10px 40px #15343638}
    header{display:flex;align-items:center;justify-content:space-between;min-height:45px;padding:0 9px 0 16px;
      background:#fff;color:#222;border-bottom:1px solid #ebebeb;font:600 15px/1.4 system-ui,sans-serif;cursor:grab;touch-action:none;user-select:none}
    header:active{cursor:grabbing}header button{background:none;color:#555;border:0;border-radius:6px;font-size:21px;width:36px;height:36px}
    header strong{margin-right:auto}header{gap:4px}
    @media(pointer:coarse){header button{width:44px;height:44px}}
    header button:hover{background:#f0f0f0}iframe{display:block;flex:1;min-height:0;width:100%;border:0}
    [hidden]{display:none!important}
  `;
  const launcher = document.createElement('button');
  launcher.className = 'launch';
  launcher.setAttribute('aria-keyshortcuts', 'Shift+F10');
  launcher.setAttribute(
    'aria-description',
    '单击切换阅读浮窗，右键或长按半秒打开本页采集菜单，拖动可移动图标',
  );
  launcher.title = '点击询问 采集助手，拖动可移动图标';
  launcher.setAttribute('aria-label', '询问 采集助手');
  launcher.innerHTML =
    '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 11.5a8.5 8.5 0 0 1-8.8 8.1c-1.5 0-2.6-.2-3.9-.8L3.5 20l1.3-4.4a7.3 7.3 0 0 1-1.4-4.1c0-4.6 3.9-8.1 8.8-8.1S21 6.9 21 11.5Z"/><path d="M8 11.5h8"/></svg>';
  const card = document.createElement('section');
  card.className = 'card';
  card.hidden = true;
  card.setAttribute('aria-label', '采集助手');
  const header = document.createElement('header');
  const heading = document.createElement('strong');
  heading.textContent = '采集助手';
  header.title = '拖动标题栏以移动窗口';
  const more = document.createElement('button');
  more.textContent = '···';
  more.title = '本页采集菜单';
  more.setAttribute('aria-label', more.title);
  more.setAttribute('aria-haspopup', 'menu');
  more.setAttribute('aria-expanded', 'false');
  const close = document.createElement('button');
  close.textContent = '−';
  close.title = '收起对话';
  close.setAttribute('aria-label', close.title);
  header.append(heading, more, close);
  card.append(header);
  root.append(style, card, launcher);
  let anchor = { right: 16, bottom: 16 };
  let open = false;
  let frame: HTMLIFrameElement | undefined;
  let menu: ReturnType<typeof captureMenu> | undefined;
  let panelPosition: { x: number; y: number } | undefined;
  const events = new AbortController();
  let cancelGesture: (() => void) | undefined;
  const place = () => {
    const box = launcher.getBoundingClientRect();
    const right = Math.max(4, Math.min(anchor.right, innerWidth - box.width - 4));
    const bottom = Math.max(6, Math.min(anchor.bottom, innerHeight - box.height - 6));
    host.style.setProperty('--mes-right', right + 'px', 'important');
    host.style.setProperty('--mes-bottom', bottom + 'px', 'important');
    if (open) {
      const icon = launcher.getBoundingClientRect();
      const left = panelPosition?.x ?? icon.right - card.offsetWidth;
      const top =
        panelPosition?.y ??
        (icon.top >= card.offsetHeight + 12 || icon.top > innerHeight / 2
          ? icon.top - card.offsetHeight - 8
          : icon.bottom + 8);
      card.style.left = Math.max(4, Math.min(left, innerWidth - card.offsetWidth - 4)) + 'px';
      card.style.top = Math.max(4, Math.min(top, innerHeight - card.offsetHeight - 4)) + 'px';
    }
    menu?.place();
  };
  const remove = () => {
    chrome.runtime.onMessage.removeListener(onMessage);
    events.abort();
    cancelGesture?.();
    menu?.dispose();
    host.remove();
    state.mesFloatingMounted = false;
  };
  const onMessage = (m: { type?: string }) => {
    if (m.type === 'float.remove') remove();
    if (m.type === 'float.captureChanged' || m.type === 'float.pageChanged') void menu?.read();
  };
  chrome.runtime.onMessage.addListener(onMessage);
  const auth = await chrome.runtime.sendMessage({ type: 'float.prepare' }).catch(() => null);
  if (!state.mesFloatingMounted || typeof auth?.ticket !== 'string') {
    remove();
    return;
  }
  menu = captureMenu(root, launcher, more, auth.ticket);
  let suppressClick = false;
  function collapse() {
    menu?.close();
    open = false;
    card.hidden = true;
    panelPosition = undefined;
    launcher.setAttribute('aria-expanded', 'false');
    place();
    launcher.focus({ preventScroll: true });
  }
  launcher.onclick = (e) => {
    if (!e.isTrusted || suppressClick || e.ctrlKey) return;
    if (open) {
      collapse();
      return;
    }
    menu?.close();
    if (!frame) {
      frame = document.createElement('iframe');
      frame.title = '采集助手对话';
      frame.src = chrome.runtime.getURL('floating.html') + '#' + auth.ticket;
      card.append(frame);
    }
    open = true;
    card.hidden = false;
    launcher.setAttribute('aria-expanded', 'true');
    place();
    close.focus();
  };
  close.onclick = collapse;
  launcher.setAttribute('aria-expanded', 'false');
  // Chrome may synthesize contextmenu during a touch hold. Only our timer
  // and a real secondary-button release can open the pointer menu.
  launcher.oncontextmenu = (e) => e.preventDefault();
  launcher.onkeydown = (e) => {
    if (!e.isTrusted) return;
    if ((e.shiftKey && e.key === 'F10') || e.key === 'ContextMenu') {
      e.preventDefault();
      suppressClick = true;
      menu?.open(launcher);
    } else if (e.key === 'Enter' || e.key === ' ') suppressClick = false;
  };
  for (const handle of [launcher, header]) {
    let drag:
      | {
          pointer: number;
          x: number;
          y: number;
          left: number;
          top: number;
          moved: boolean;
          held: boolean;
          secondary: boolean;
        }
      | undefined;
    let timer: number | undefined;
    const finish = () => {
      clearTimeout(timer);
      if (!drag) return;
      const id = drag.pointer;
      drag = undefined;
      cancelGesture = undefined;
      if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
    };
    handle.onpointerdown = (e) => {
      const secondary = handle === launcher && (e.button === 2 || (e.button === 0 && e.ctrlKey));
      if (
        !e.isTrusted ||
        (e.target instanceof Element && handle === header && e.target.closest('button')) ||
        (!secondary && (e.button !== 0 || e.ctrlKey)) ||
        !e.isPrimary ||
        cancelGesture
      )
        return;
      const box = (handle === launcher ? launcher : card).getBoundingClientRect();
      drag = {
        pointer: e.pointerId,
        x: e.clientX,
        y: e.clientY,
        left: box.left,
        top: box.top,
        moved: false,
        held: false,
        secondary,
      };
      cancelGesture = () => {
        suppressClick = true;
        finish();
      };
      handle.setPointerCapture(e.pointerId);
      if (handle === launcher && !secondary) {
        suppressClick = false;
        timer = window.setTimeout(() => {
          if (!drag || drag.moved) return;
          drag.held = true;
          suppressClick = true;
          menu?.open(launcher);
        }, 500);
      }
    };
    const move = (e: PointerEvent) => {
      if (!drag || drag.pointer !== e.pointerId) return;
      const dx = e.clientX - drag.x,
        dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) <= 6) return;
      if (!drag.moved) {
        clearTimeout(timer);
        menu?.close();
        drag.moved = true;
      }
      if (handle === launcher) {
        suppressClick = true;
        panelPosition = undefined;
        anchor = {
          right: innerWidth - launcher.offsetWidth - drag.left - dx,
          bottom: innerHeight - launcher.offsetHeight - drag.top - dy,
        };
      } else panelPosition = { x: drag.left + dx, y: drag.top + dy };
      place();
    };
    handle.onpointermove = move;
    handle.onpointerup = (e) => {
      if (drag?.pointer !== e.pointerId) return;
      move(e);
      const secondaryTap = drag.secondary && !drag.moved;
      if (handle === launcher) suppressClick = drag.moved || drag.held || drag.secondary;
      finish();
      if (secondaryTap) menu?.open(launcher);
    };
    handle.onlostpointercapture = handle.onpointercancel = (e) => {
      if (drag?.pointer === e.pointerId) cancelGesture?.();
    };
  }
  document.documentElement.append(host);
  window.addEventListener('resize', place, { signal: events.signal });
  window.addEventListener('blur', () => cancelGesture?.(), { signal: events.signal });
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.hidden) cancelGesture?.();
    },
    { signal: events.signal },
  );
  place();
}
void mount();
