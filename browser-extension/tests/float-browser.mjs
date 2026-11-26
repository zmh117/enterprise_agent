import assert from 'node:assert/strict';
import {join} from 'node:path';
import {createServer} from 'node:http';

export async function checkFloat({context, control, id, fixture, next, requests, mesHost, checkReply, signIn}) {
  let requestStarted, releaseRequest;
  const started = new Promise(resolve=>{requestStarted=resolve;});
  const released = new Promise(resolve=>{releaseRequest=resolve;});
  const server = createServer(async (req,res) => {
    if (req.url === '/api/save') {
      res.writeHead(422, {'Content-Type':'application/json','X-Request-ID':'beef0123456789abcdef0123456789ab'});
      res.end('{"workOrder":"WO-C","orderId":9876543210123456789,"code":"BATCH_REQUIRED"}');
      return;
    }
    if (req.url==='/api/shared') {
      requestStarted(); await released;
      res.writeHead(200,{'Content-Type':'application/json','X-Request-ID':'abcdef0123456789abcdef0123456789'});
      res.end(JSON.stringify({workOrder:'WO-SYNTHETIC',batch:'B-SYNTHETIC',rows:[{qty:3}],cookie:'synthetic-private-header-value'}));
      return;
    }
    res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'});
    res.end('<!doctype html><title>MES 合成测试</title><main><h1>工单查询</h1><button onclick="fetch(\'/api/save\',{method:\'POST\'})">保存</button></main>');
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
    // Starting before binding must leave the selected tab available to configure and retry.
    await control.locator('#record-mode').selectOption('continuous');
    const start = control.locator('#start');
    const feedback = control.locator('#prepare .panel-footer #start-feedback');
    if (process.env.EA_TEST_HISTORY === '1') {
      await control.locator('nav a[href="#sites"]').click();
      const editor = control.locator('#workshop-editor');
      const application = editor.getByRole('combobox', {name:'业务应用', exact:true});
      assert.equal(await application.locator('option:checked').textContent(), '合成诊断');
      await application.selectOption({label:'合成巡检'});
      await editor.getByRole('status').filter({hasText:'在「合成巡检」没有可采集的车间'}).waitFor();
      assert.equal(await editor.locator('#workshop-environment option').count(), 1);
      assert.ok(await editor.locator('#workshop-save').isDisabled());
      await control.locator('nav a[href="#capture"]').click();
      await start.click();
      await feedback.filter({hasText:'没有可采集的车间'}).waitFor();
      await control.locator('nav a[href="#assistant"]').click();
      assert.equal(await control.locator('#assistant #agent-app option:checked').textContent(), '合成巡检');
      await control.locator('#agent-app').selectOption({label:'合成诊断'});
      await control.locator('nav a[href="#sites"]').click();
      assert.equal(await application.locator('option:checked').textContent(), '合成诊断');
      await control.waitForFunction(() => document.querySelector('#workshop-environment').options.length > 1);
      await control.locator('nav a[href="#capture"]').click();
    }
    await control.evaluate(() => {
      const request = chrome.permissions.request;
      chrome.permissions.request = () => new Promise(resolve => {
        window.releaseStartPermission = () => { chrome.permissions.request = request; resolve(true); };
      });
    });
    await start.click();
    await feedback.filter({hasText:'正在确认 Chrome 站点权限'}).waitFor();
    assert.ok(await start.isDisabled());
    await control.evaluate(() => window.releaseStartPermission());
    await feedback.filter({hasText:'允许页面并绑定车间'}).waitFor();
    assert.ok(await start.isEnabled());
    assert.ok(await control.locator('#live-session').isHidden());
    await control.locator('#start-settings').click();
    assert.equal(await control.locator('#workshop-page option:checked').textContent(), origin + '/');
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#record-mode').selectOption('offline');
    await control.locator('#start').click();
    await control.locator('#stop').waitFor();
    await control.locator('#stop').click();
    await control.locator('#preview:enabled').waitFor();
    await control.locator('#preview').click();
    await control.locator('#summary-preview').filter({hasText: 'capture-fixture'}).waitFor();
    await control.locator('nav a[href="#records"]').click();
    await control.locator('#history-search').fill('capture-fixture');
    await control.locator('.history-row').first().waitFor();
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#new').click();
    await control.locator('#record-mode').selectOption('continuous');
    await start.click();
    await feedback.filter({hasText:'允许页面并绑定车间'}).waitFor();
    // Force the same status refresh that runs on the polling timer after a failed attempt.
    await control.evaluate(() => document.querySelector('#live-refresh').click());
    await control.locator('#start:enabled').waitFor();
    await control.locator('#start-settings').click();

    // Two workshop URLs share their Chrome origin permission.
    await mes.goto(origin + '/mes#/orders?shop=mix&transient=ignored');
    const packing = await context.newPage();
    await packing.goto(origin + '/users');
    await control.getByRole('button', {name:'刷新站点'}).click();
    async function bind(pageUrl, name, keys = '') {
      await control.locator('#workshop-page').selectOption({label:pageUrl});
      if (await control.locator('#workshop-keys').isEnabled())
        await control.locator('#workshop-keys').fill(keys);
      await control.locator('#workshop-environment').selectOption({label:'采集联调'});
      await control.locator('#workshop-base').selectOption({label:'一号基地'});
      await control.locator('#workshop-choice').selectOption({label:name});
      await control.locator('#workshop-save').click();
      await control.locator('#workshop-revoke:enabled').waitFor();
    }
    await control.locator('#workshop-page').selectOption({label: origin + '/mes#/orders'});
    assert.equal(await control.locator('#workshop-choice').inputValue(), '', '旧环境不能推断车间');
    await control.locator('#workshop-environment').selectOption({label:'采集联调'});
    await control.locator('#workshop-base').selectOption({label:'一号基地'});
    await control.locator('#workshop-choice').selectOption({label:'配液车间'});
    await control.evaluate(() => {
      const request = chrome.permissions.request;
      chrome.permissions.request = async () => { chrome.permissions.request = request; return false; };
    });
    await control.locator('#workshop-save').click();
    await control.locator('#workshop-status').filter({hasText:'未获得页面访问权限'}).waitFor();
    await bind(origin + '/mes#/orders', '配液车间', 'shop');
    assert.equal(await control.locator('#workshop-url').textContent(), origin + '/mes#/orders?shop=mix');
    await bind(origin + '/users', '包装车间');
    await control.locator('#workshop-range').selectOption('site');
    await bind(origin + '/users', '包装车间');
    assert.equal(await control.locator('#workshop-url').textContent(), origin + '/');
    await control.locator('#workshop-range').selectOption('path');
    // The continuous run owns three distinct tabs, including two on the same bound URL.
    const twin = await context.newPage();
    await twin.goto(mes.url());
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#refresh').click();
    await control.locator('#tab-search').fill(origin);
    await control.locator('#select-all').check();
    await control.locator('#record-mode').selectOption('continuous');
    await control.locator('#start').click();
    await control.waitForFunction(()=>document.querySelector('#live-tabs')?.textContent.match(/正在采集/g)?.length === 3).catch(async error => {
      throw new Error('三页基线状态 '+(await control.locator('#live-tabs').innerText())+' '+(await feedback.textContent()),{cause:error});
    });
    assert.equal(await control.locator('#status-pill').textContent(), '持续采集已启动');
    async function networkStatus() {
      return control.evaluate(async()=>(await chrome.runtime.sendMessage({type:'session.status'})).continuous?.tabs.map(t=>({network:t.network,gap:t.networkGap})));
    }
    const deadline=Date.now()+10000;
    while (!(await networkStatus())?.every(t=>t.network?.mapped)) {
      if (Date.now()>deadline) throw new Error('Network mapping '+JSON.stringify(await networkStatus()));
      await new Promise(r=>setTimeout(r,100));
    }
    await packing.evaluate(() => history.pushState({}, '', '/users/roles'));
    await packing.locator('h1').click();
    await packing.evaluate(() => fetch('/api/child-route').then(r => r.text()));
    await packing.evaluate(() => history.pushState({}, '', '/reports'));
    await packing.evaluate(() => fetch('/api/root-route').then(r => r.text()));
    const delayed = mes.evaluate(()=>fetch('/api/shared',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workOrder:'WO-SYNTHETIC'})}).then(r=>r.json()).then(()=>true));
    await started;
    await mes.evaluate(()=>history.pushState({},'', '/users/roles'));
    releaseRequest(); await delayed;
    await control.waitForFunction(()=>document.querySelector('#live-tabs')?.textContent.includes('页面采集已暂停'));
    await mes.evaluate(()=>history.pushState({},'', '/mes#/orders?shop=mix'));
    assert.equal(await control.locator('#live-tabs p').filter({hasText:'正在采集'}).count(),2);
    await control.waitForFunction(async () => {
      const db=await new Promise(resolve=>{const r=indexedDB.open('mes-workshop-live-v1');r.onsuccess=()=>resolve(r.result);});
      const rows=await new Promise(resolve=>{const r=db.transaction('liveEvidence').objectStore('liveEvidence').getAll();r.onsuccess=()=>resolve(r.result);});
      db.close(); return rows.some(r=>r.event.kind==='body' && r.event.side==='response');
    },null,{timeout:10000});
    await twin.locator('h1').click();
    await mes.reload();
    await control.waitForFunction(()=>document.querySelector('#live-tabs')?.textContent.match(/正在采集/g)?.length === 3);
    const evidence = await control.evaluate(async () => {
      const db = await new Promise((resolve,reject)=>{const r=indexedDB.open('mes-workshop-live-v1'); r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
      const rows = await new Promise((resolve,reject)=>{const r=db.transaction('liveEvidence').objectStore('liveEvidence').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
      db.close();
      return {tabs:new Set(rows.map(r=>r.source.tab_id)).size, documents:new Set(rows.map(r=>r.source.document_id)).size,
        network:(()=>{
          const req=rows.find(r=>r.event.kind==='request' && r.event.api_path==='/api/shared');
          const related=rows.filter(r=>req && r.event.request_key===req.event.request_key);
          const body=related.find(r=>r.event.kind==='body' && r.event.side==='response')?.event;
          return {found:!!req, sameSource:!!req && related.every(r=>JSON.stringify(r.source)===JSON.stringify(req.source)),
            body:body?.status, workOrder:body?.value?.workOrder==='WO-SYNTHETIC', detail:body?.value?.rows?.[0]?.qty===3,
            protected:!!body?.value && !('cookie' in body.value), requestBodies:related.filter(r=>r.event.kind==='body').map(r=>[r.event.side,r.event.status]).sort()};
        })(), inherited: (() => {
          const child = rows.find(r => r.event.api_path === '/api/child-route');
          const root = rows.find(r => r.event.api_path === '/api/root-route');
          return !!child && !!root && JSON.stringify(root.source) === JSON.stringify(child.source) &&
            rows.some(r => r.event.kind === 'action' && JSON.stringify(r.source) === JSON.stringify(child.source));
        })(),hasAction:rows.some(r=>r.event.kind==='action'), masked:rows.every(r=>!JSON.stringify(r).includes('工单查询'))};
    });
    assert.deepEqual(evidence,{tabs:3,documents:4,network:{found:true,sameSource:true,body:'captured',workOrder:true,detail:true,protected:true,requestBodies:[['request','captured'],['response','captured']]},inherited:true,hasAction:true,masked:true});
    await Promise.all([mes.waitForResponse(r => r.url().endsWith('/api/save')),mes.getByRole('button',{name:'保存'}).click()]);
    await packing.evaluate(() => history.pushState({}, '', '/users/roles'));
    await control.locator('nav a[href="#sites"]').click();
    await control.getByRole('button', {name:'刷新站点'}).click();
    await bind(origin + '/users/roles', '配液车间');
    await control.locator('nav a[href="#capture"]').click();
    await control.waitForFunction(() => document.querySelector('#live-tabs').textContent.includes('页面采集已暂停'));
    assert.equal(await control.locator('#live-tabs p').filter({hasText:'正在采集'}).count(), 2);
    await twin.close();
    await control.locator('nav a[href="#sites"]').click();
    await packing.close();
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
    await frame.locator('#agent-workshop').filter({hasText:'采集联调 › 一号基地 › 配液车间'}).waitFor();
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
    fixture.stdin.write('sending-page\n');
    const sentPage = await next();
    assert.equal(sentPage.registered, true, '浮窗问题应在停止录制之前绑定发送页');
    if (process.env.BROWSER_EVIDENCE_SYNTHETIC_ROUNDTRIP === '1') {
      fixture.stdin.write('live-tool\n');
      assert.deepEqual(await next(), {observedSave:true, body:true, sameTab:true, status:422});
    }
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#live-stop').click();
    await control.locator('nav a[href="#sites"]').click();
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
    fixture.stdin.write('end-session\n'); assert.equal((await next()).ended, true);
    await control.locator('nav a[href="#assistant"]').click();
    await control.locator('#agent-connection').evaluate(el => el.open = true);
    await control.locator('#agent-login').click();
    await signIn('demo-second');
    await control.waitForFunction(() => !document.querySelector('#agent-send').disabled);
    await control.locator('nav a[href="#sites"]').click();
    await control.locator('#workshop-page').selectOption({label:origin + '/mes#/orders'});
    assert.equal(await control.locator('#workshop-environment option').count(), 1, '换账号后不得继承其他用户的环境车间');
    assert.ok(await control.locator('#workshop-revoke').isDisabled());
    console.log(JSON.stringify({workshopScope:true, accountSwitch:true, floatingHost:mesHost, launcherDrag:true, windowDrag:true, multiSite:true, collapsedStream:true, draftRetained:true, reloaded:true, disabled:true, submittedJobs:posts.length}));
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
