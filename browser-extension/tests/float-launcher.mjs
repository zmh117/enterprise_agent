import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

// The product has a closed shadow root. Use the accessibility tree to locate
// the actual menu item and send normal mouse input to the rendered button.
async function menuPoint(cdp, name) {
  for (let i = 0; i < 80; i++) {
    const { nodes } = await cdp.send('Accessibility.getFullAXTree');
    const item = nodes.find(
      (n) =>
        n.role?.value === 'menuitem' &&
        n.name?.value === name &&
        !n.properties?.some((p) => p.name === 'disabled' && p.value?.value),
    );
    if (item) {
      const { model } = await cdp.send('DOM.getBoxModel', { backendNodeId: item.backendDOMNodeId });
      return [(model.border[0] + model.border[4]) / 2, (model.border[1] + model.border[5]) / 2];
    }
    await delay(50);
  }
  throw new Error('未找到可用采集动作 ' + name);
}

export async function checkPageLauncher(context, control, first, second) {
  const state = () =>
    control.evaluate(
      async () =>
        (await chrome.runtime.sendMessage({ type: 'session.status' })).continuous?.tabs.map((t) => t.tabId) ??
        [],
    );
  async function count(n) {
    for (let i = 0; i < 100; i++) {
      const ids = await state();
      if (ids.length === n) return ids;
      await delay(100);
    }
    throw new Error('持续采集未达到预期标签页数 ' + n);
  }
  const a = await context.newCDPSession(first),
    b = await context.newCDPSession(second);
  const start = '开始本页采集',
    stop = '停止本页采集';
  const orb = (p) => p.locator('[data-mes-agent-host]');
  try {
    await first.bringToFront();
    await orb(first).click({ button: 'right' });
    await first.mouse.click(...(await menuPoint(a, start)));
    const [firstId] = await count(1);
    await second.bringToFront();
    const box = await orb(second).boundingBox(),
      x = box.x + 25,
      y = box.y + 25;
    await second.mouse.move(x, y);
    await second.mouse.down();
    const target = await menuPoint(b, start);
    await second.mouse.up();
    assert.deepEqual(await state(), [firstId], '长按松手只打开菜单');
    await second.mouse.click(...target);
    const both = await count(2);
    await second.mouse.move(x, y);
    await second.mouse.down();
    await menuPoint(b, stop);
    await second.mouse.move(x - 92, y - 76, { steps: 8 });
    await second.mouse.up();
    const moved = await orb(second).boundingBox();
    assert.ok(Math.abs(moved.x - box.x + 92) < 2);
    assert.deepEqual(await state(), both, '长按转拖动应保留两页');
    assert.ok(!second.frames().some((f) => f.url().includes('/floating.html')));
    assert.ok(
      !(await b.send('Accessibility.getFullAXTree')).nodes.some(
        (n) => n.role?.value === 'menuitem' && n.name?.value === stop,
      ),
    );
    await orb(second).click({ button: 'right' });
    await second.mouse.click(...(await menuPoint(b, stop)));
    assert.deepEqual(await count(1), [firstId]);
    await first.bringToFront();
    const activeSource = await control.evaluate(
      async () => (await chrome.storage.session.get('liveWorkshopCapture')).liveWorkshopCapture.tabs[0].id,
    );
    const since = await control.evaluate(() => Date.now());
    await second.locator('h1').click();
    await first.locator('h1').click();
    const laterActions = () =>
      control.evaluate(async (since) => {
        const db = await new Promise((resolve) => {
          const r = indexedDB.open('mes-workshop-live-v1');
          r.onsuccess = () => resolve(r.result);
        });
        const rows = await new Promise((resolve) => {
          const r = db.transaction('liveEvidence').objectStore('liveEvidence').getAll();
          r.onsuccess = () => resolve(r.result);
        });
        db.close();
        const later = rows.filter((r) => r.observedAt >= since && r.event.kind === 'action');
        return later.map((r) => r.source.tab_id);
      }, since);
    let observed = [];
    for (let i = 0; i < 50 && !observed.length; i++) {
      observed = await laterActions();
      if (!observed.length) await delay(100);
    }
    assert.deepEqual([...new Set(observed)], [activeSource], '停止一页后只有另一页继续保存点击');
    await b.send('Emulation.setTouchEmulationEnabled', { enabled: true });
    const tx = moved.x + 25,
      ty = moved.y + 25;
    const touch = (type, x, y) =>
      b.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
    await second.bringToFront();
    await touch('touchStart', tx, ty);
    await menuPoint(b, start);
    await touch('touchEnd');
    assert.deepEqual(await state(), [firstId], '触屏长按松手不应开始采集');
    await second.keyboard.press('Escape');
    await touch('touchStart', tx, ty);
    await touch('touchMove', tx - 48, ty - 27);
    await delay(550);
    await touch('touchEnd');
    assert.deepEqual(await state(), [firstId], '触屏拖动不应改变其他页状态');
    assert.ok(!second.frames().some((f) => f.url().includes('/floating.html')));
    assert.ok(
      !(await b.send('Accessibility.getFullAXTree')).nodes.some(
        (n) => n.role?.value === 'menuitem' && n.name?.value === start,
      ),
    );
    await first.bringToFront();
    await orb(first).click({ button: 'right' });
    await first.mouse.click(...(await menuPoint(a, stop)));
    await count(0);
  } finally {
    await a.detach();
    await b.detach();
  }
}
