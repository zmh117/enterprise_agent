import type { LiveCapture } from '../background/live-capture';

type Capture = ReturnType<LiveCapture['pageStatus']>;
const labels = {
  ready: '采集中',
  baseline: '等待页面基线',
  paused: '已暂停，请刷新页面',
  unbound: '当前地址未绑定',
};

export function captureMenu(
  root: ShadowRoot,
  launcher: HTMLButtonElement,
  more: HTMLButtonElement,
  ticket: string,
) {
  const menu = document.createElement('section');
  menu.className = 'capture-menu';
  menu.popover = 'manual';
  menu.innerHTML =
    '<strong>本页持续采集</strong><span role="status"></span><div role="menu" aria-label="本页持续采集"><button type="button" role="menuitem"></button></div>';
  const status = menu.querySelector('span')!;
  const action = menu.querySelector('button')!;
  const badge = document.createElement('span');
  badge.className = 'capture-badge';
  badge.hidden = true;
  badge.setAttribute('aria-hidden', 'true');
  const liveNotice = document.createElement('span');
  liveNotice.className = 'visually-hidden';
  liveNotice.setAttribute('role', 'status');
  launcher.append(badge);
  root.append(menu, liveNotice);
  const events = new AbortController();
  let current: Capture = null,
    anchor: HTMLElement | undefined;
  let generation = 0,
    busy = false,
    known = false,
    clock: number | undefined;
  function tick() {
    if (current?.state !== 'ready' || !current.startedAt) return;
    const sec = Math.max(0, Math.floor((Date.now() - current.startedAt) / 1000));
    badge.textContent =
      Math.floor(sec / 60)
        .toString()
        .padStart(2, '0') +
      ':' +
      (sec % 60).toString().padStart(2, '0');
  }
  function render() {
    const label = current ? labels[current.state] : '未采集';
    launcher.title = '单击对话，右键或长按打开本页采集菜单，拖动移位 · ' + label;
    launcher.setAttribute('aria-label', '询问 采集助手 · ' + label);
    badge.hidden = !current;
    badge.textContent =
      current?.state === 'ready' ? '采集中' : current?.state === 'baseline' ? '准备中' : '暂停';
    badge.classList.toggle('recording', current?.state === 'ready');
    if (current?.state === 'ready' && current.startedAt) {
      tick();
      clock ??= window.setInterval(tick, 1000);
    } else {
      clearInterval(clock);
      clock = undefined;
    }
    status.textContent = current?.detail || label;
    action.textContent = current ? '停止本页采集' : '开始本页采集';
    action.classList.toggle('stop', !!current);
    action.disabled = !known || busy;
  }
  function place() {
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect(),
      width = menu.offsetWidth,
      height = menu.offsetHeight;
    menu.style.left = Math.max(4, Math.min(rect.right - width, innerWidth - width - 4)) + 'px';
    menu.style.top =
      (rect.top >= height + 12
        ? rect.top - height - 8
        : Math.min(rect.bottom + 8, innerHeight - height - 4)) + 'px';
  }
  function close(focus = false) {
    if (!anchor) return;
    const trigger = anchor;
    anchor = undefined;
    menu.hidePopover();
    more.setAttribute('aria-expanded', 'false');
    if (focus) trigger.focus({ preventScroll: true });
  }
  async function read() {
    if (busy) return;
    const seq = ++generation;
    try {
      const reply = await chrome.runtime.sendMessage({ type: 'float.captureStatus', ticket });
      if (!reply?.ok) throw new Error(reply?.error || '请刷新页面后重试');
      if (seq !== generation) return;
      current = reply.capture;
      known = true;
      render();
      if (anchor && root.activeElement === anchor) action.focus({ preventScroll: true });
    } catch (err) {
      if (seq !== generation) return;
      known = false;
      action.disabled = true;
      status.textContent = String(err);
    }
    place();
  }
  function open(source: HTMLElement) {
    anchor = source;
    if (!menu.matches(':popover-open')) menu.showPopover();
    more.setAttribute('aria-expanded', 'true');
    if (!busy) {
      known = false;
      action.disabled = true;
      status.textContent = '正在核对本页状态…';
      source.focus({ preventScroll: true });
      void read();
    }
    place();
  }
  action.onclick = async (e) => {
    if (!e.isTrusted || !anchor || !known || busy) return;
    busy = true;
    ++generation;
    action.disabled = true;
    const stopping = !!current;
    status.textContent = stopping ? '正在停止…' : '正在启动…';
    try {
      const reply = await chrome.runtime.sendMessage({
        type: stopping ? 'float.captureStop' : 'float.captureStart',
        ticket,
        membership: current?.id,
      });
      if (events.signal.aborted) return;
      if (!reply?.ok) throw new Error(reply?.error || '扩展后台无响应');
      current = reply.capture;
      known = true;
      render();
      close(true);
      liveNotice.textContent = current ? labels[current.state] : '本页采集已停止';
    } catch (err) {
      known = false;
      status.textContent = String(err);
      place();
    } finally {
      busy = false;
      action.disabled = !known;
    }
  };
  more.onclick = (e) => {
    if (e.isTrusted) {
      if (anchor) close(true);
      else open(more);
    }
  };
  document.addEventListener(
    'pointerdown',
    (e) => {
      if (anchor && !e.composedPath().includes(root.host)) close();
    },
    { capture: true, signal: events.signal },
  );
  root.addEventListener('pointerdown', (e) => {
    if (anchor && !e.composedPath().some((n) => n === menu || n === launcher || n === more)) close();
  });
  root.addEventListener('keydown', (e) => {
    if (e instanceof KeyboardEvent && anchor && (e.key === 'Escape' || e.key === 'Tab')) {
      if (e.key === 'Escape') e.preventDefault();
      close(true);
    }
  });
  window.addEventListener('blur', () => close(), { signal: events.signal });
  render();
  void read();
  return {
    open,
    close,
    place,
    read,
    dispose() {
      ++generation;
      close();
      events.abort();
      clearInterval(clock);
    },
  };
}
