import assert from 'node:assert/strict';
import {join} from 'node:path';
import {createServer} from 'node:http';

export async function checkFloat({context, control, id, fixture, next, requests, mesHost, checkReply}) {
  const server = createServer((_req,res) => {
    res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'});
    res.end('<!doctype html><title>MES 合成测试</title><main><h1>工单查询</h1></main>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const origin = 'http://' + mesHost + ':' + server.address().port;
    const secondOrigin = 'http://' + (mesHost === '127.0.0.1' ? 'localhost' : '127.0.0.1') + ':' + server.address().port;
    const mes = await context.newPage();
    await mes.goto(origin);
    const other = await context.newPage();
    await other.goto(secondOrigin);
    const host = mes.locator('[data-mes-agent-host]');
    const otherHost = other.locator('[data-mes-agent-host]');
    assert.equal(await host.count(), 0);
    await control.locator('nav a[href="#sites"]').click();
    const firstSite = control.getByRole('checkbox', {name:origin, exact:true});
    const secondSite = control.getByRole('checkbox', {name:secondOrigin, exact:true});
    const save = control.getByRole('button', {name:'保存站点'});
    await control.getByRole('button', {name:'刷新站点'}).click();
    await firstSite.check(); await secondSite.check();
    const environment = control.getByRole('combobox', {name: origin + ' 的关联环境', exact: true});
    await environment.selectOption('capture-fixture');
    assert.equal(await otherHost.count(), 0);
    await save.click();
    await Promise.all([host.waitFor(), otherHost.waitFor()]);
    await control.reload();
    await firstSite.waitFor();
    assert.ok(await firstSite.isChecked() && await secondSite.isChecked());
    await control.waitForFunction(site => document.querySelector('select[aria-label="' + site +
      ' 的关联环境"]')?.value === 'capture-fixture', origin);
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#tab-search').fill(origin);
    await control.locator('#select-all').check();
    assert.equal(await control.locator('#environment').textContent(), 'capture-fixture');
    await control.locator('#start').click();
    await control.locator('#stop').waitFor();
    await control.locator('#stop').click();
    await control.locator('#preview:enabled').waitFor();
    await control.locator('#preview').click();
    await control.locator('#summary-preview').filter({hasText: 'capture-fixture'}).waitFor();
    await control.locator('nav a[href="#records"]').click();
    await control.locator('#history-search').fill('capture-fixture');
    await control.locator('.history-row').first().waitFor();
    await control.locator('nav a[href="#sites"]').click();

    const fake = await mes.evaluateHandle(id => {
      const iframe = document.createElement('iframe');
      iframe.src = 'chrome-extension://' + id + '/floating.html#unregistered';
      document.body.append(iframe);
      return iframe;
    }, id);
    const untrusted = await fake.asElement().contentFrame();
    await untrusted.waitForLoadState('load');
    assert.equal(await untrusted.locator('#floating-view').isVisible(), false);
    await fake.evaluate(el => el.remove()); await fake.dispose();
    const viewport = await mes.evaluate(() => ({width: innerWidth, height: innerHeight}));
    const button = await host.boundingBox();
    assert.ok(Math.abs(button.x + button.width + 16 - viewport.width) < 2);
    assert.ok(Math.abs(button.y + button.height + 16 - viewport.height) < 2);
    await mes.mouse.move(button.x+25, button.y+25);
    await mes.mouse.down();
    await mes.mouse.move(button.x+25-90, button.y+25-42, {steps:8});
    await mes.mouse.up();
    const moved = await host.boundingBox();
    assert.ok(Math.abs(moved.x - button.x + 90) < 2 && Math.abs(moved.y - button.y + 42) < 2);
    assert.equal(moved.width, button.width, '拖动图标后仍然收起');
    assert.ok(!mes.frames().some(f => f.url().startsWith('chrome-extension://' + id + '/floating.html')));
    async function open() {
      await Promise.all([
        mes.waitForEvent('framenavigated', {predicate: f => f.url().startsWith('chrome-extension://' + id + '/floating.html')}),
        host.click(),
      ]);
      const frame = mes.frames().find(f => f.url().startsWith('chrome-extension://' + id + '/floating.html'));
      assert.ok(frame, '悬浮窗 iframe 应已加载');
      await frame.locator('#floating-view').waitFor();
      return frame;
    }
    const frame = await open();
    const draft = frame.locator('#agent-question');
    await frame.waitForFunction(() => !document.querySelector('#agent-send')?.disabled, null, {timeout:12000})
      .catch(async () => { throw new Error('助手登录状态 ' + await frame.locator('#agent-status').textContent()); });
    const before = await host.boundingBox();
    await mes.mouse.move(before.x + 80, before.y + 20);
    await mes.mouse.down(); await mes.mouse.move(before.x - 75, before.y - 25, {steps:8}); await mes.mouse.up();
    const after = await host.boundingBox();
    assert.ok(Math.abs(after.x - before.x + 155) < 2 && Math.abs(after.y - before.y + 45) < 2, '窗口随拖动移动');
    const question = '检查合成保存操作';
    const rejected = '检查应用暂时不可用时能否重试';
    await draft.fill(rejected); await draft.press('Enter');
    await frame.locator('#agent-status').getByText(/应用暂时无法接收问题/).waitFor();
    assert.equal(await draft.inputValue(), rejected);
    assert.equal(await frame.locator('.question').count(), 0);
    await draft.fill(question); await draft.press('Enter');
    await frame.getByText('排队中', {exact:true}).waitFor();
    await frame.locator('.question').getByText(question).waitFor();
    fixture.stdin.write('advance\n'); await next();
    await frame.locator('.answer').getByText(/我查一下/).first().waitFor();
    await draft.fill('未发送的追问');
    await mes.mouse.click(after.x + after.width - 25, after.y + 22);
    assert.ok((await host.boundingBox()).width < 60);
    for (let i = 0; i < 3; i++) {fixture.stdin.write('advance\n'); assert.equal((await next()).jobs, 1);}
    await frame.waitForFunction(() => document.querySelector('.answer small')?.textContent === '已完成', null, {polling:100, timeout:12000});
    await host.click();
    assert.equal(await draft.inputValue(), '未发送的追问');
    await frame.locator('.answer strong').filter({hasText:'缺少批号'}).waitFor();
    assert.equal(await frame.locator('.answer table tbody tr').count(), 1);
    await frame.locator('.answer pre code').waitFor();
    await checkReply(frame, control);
    assert.equal(await mes.locator('body').getByText(question).count(), 0);
    await mes.reload(); await host.waitFor();
    const recovered = await open();
    await recovered.locator('.answer strong').filter({hasText:'缺少批号'}).waitFor();
    assert.equal(await recovered.locator('.question').count(), 1);
    if (process.env.EA_CHAT_PREVIEW_DIR) {
      await recovered.locator('#agent-answers').evaluate(el => { el.scrollTop = 0; });
      await host.screenshot({path:join(process.env.EA_CHAT_PREVIEW_DIR, 'agent-chatgpt-floating.png')});
    }
    const posts = requests.filter(([method,path]) => method === 'POST' && path.endsWith('/messages'));
    assert.equal(posts.length, 1);
    assert.ok(!requests.some(([method,path]) => method === 'GET' && path.includes('/messages/')),
      '平台明确拒绝的问题不应进入丢失回执恢复');
    await firstSite.uncheck(); await save.click();
    await host.waitFor({state:'detached'});
    await other.reload(); await otherHost.waitFor();
    await control.reload(); await firstSite.waitFor();
    assert.ok(!await firstSite.isChecked() && await secondSite.isChecked());
    await secondSite.uncheck(); await save.click(); await otherHost.waitFor({state:'detached'});
    await mes.reload(); assert.equal(await host.count(), 0);
    console.log(JSON.stringify({floatingHost:mesHost, launcherDrag:true, windowDrag:true, multiSite:true, collapsedStream:true, draftRetained:true, reloaded:true, disabled:true, submittedJobs:posts.length}));
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
