import assert from 'node:assert/strict';
import {join} from 'node:path';
import {on} from 'node:events';
import {createServer} from 'node:http';
import {checkPageLauncher} from './float-launcher.mjs';
import {checkStopReply} from './stop-reply.mjs';

async function stopCollectorWorker(context, control, id) {
  const session = await context.newCDPSession(control);
  const updates = on(session, 'ServiceWorker.workerVersionUpdated', {signal:AbortSignal.timeout(6000)});
  try {
    await session.send('ServiceWorker.enable');
    for await (const [event] of updates) {
      const worker = event.versions.find(v => v.scriptURL === 'chrome-extension://' + id + '/background.js' && v.runningStatus === 'running');
      if (worker) {
        await session.send('ServiceWorker.stopWorker', {versionId:worker.versionId});
        break;
      }
    }
  } finally {
    await updates.return();
    await session.detach();
  }
}

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
    const save = control.locator('#workshop-save');
    const address = control.locator('#site-address');
    const status = control.locator('#workshop-status');
    const rules = control.locator('#site-rules');
    const start = control.locator('#start');
    const feedback = control.locator('#start-feedback');
    const configure = async (url, shopName, key) => {
      await control.locator('#site-new').click();
      await address.fill(url);
      await control.locator('#site-app').selectOption({label:'合成诊断'});
      await control.locator('#workshop-environment').selectOption({label:'采集联调'});
      if (shopName) await control.locator('#workshop-base').selectOption({label:'一号基地'});
      if (shopName && shopName !== '基地') await control.locator('#workshop-choice').selectOption({label:shopName});
      if (key) await control.getByRole('checkbox',{name:'匹配参数 ' + key}).check();
    };
    const persist = async () => {
      await save.click();
      await status.filter({hasText:'规则已保存到平台'}).waitFor();
    };
    async function bind(url,name,key) { await configure(url,name,key); await persist(); }
    await control.getByRole('button',{name:'刷新',exact:true}).click();
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#tab-search').fill(origin);
    await control.locator('#select-all').check();
    await control.locator('#record-mode').selectOption('continuous');
    await start.click();
    await feedback.filter({hasText:'尚未绑定'}).waitFor();
    assert.ok(await start.isEnabled());
    await control.locator('#start-settings').click();
    assert.equal(await address.inputValue(),origin + '/');
    await control.locator('#site-app').selectOption({label:'合成诊断'});
    await control.locator('#workshop-environment').selectOption({label:'采集联调'});
    assert.equal(await control.locator('#workshop-base').inputValue(),'');
    await control.evaluate(() => {
      const original = chrome.permissions.request;
      chrome.permissions.request = async () => { chrome.permissions.request = original; return false; };
    });
    await save.click();
    await status.filter({hasText:'未获得站点访问权限'}).waitFor();
    await persist();
    await host.waitFor();
    await bind(secondOrigin + '/', '基地');
    await otherHost.waitFor();
    await control.reload();
    await rules.getByRole('button').filter({hasText:'一号基地'}).waitFor();
    assert.equal(await rules.getByRole('button').count(),2);
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#tab-search').fill(origin);
    await control.locator('#select-all').check();
    assert.equal(await control.locator('#environment').textContent(), 'capture-fixture');
    await control.locator('#record-mode').selectOption('offline');
    await start.click();
    await control.locator('#stop').click();
    await control.locator('#preview:enabled').click();
    await control.locator('#summary-preview').filter({hasText:'capture-fixture'}).waitFor();
    await control.locator('nav a[href="#records"]').click();
    await control.locator('#history-search').fill('capture-fixture');
    await control.locator('.history-row').first().waitFor();
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#new').click();
    await control.locator('nav a[href="#sites"]').click();
    await mes.goto(origin + '/mes#/orders?shop=mix&transient=ignored');
    const packing = await context.newPage(); await packing.goto(origin + '/users');
    await bind(mes.url(), '配液车间','shop');
    const mesRuleId = await rules.locator('[aria-current=true]').getAttribute('data-binding-id');
    await bind(origin + '/users','包装车间');
    const siteGroup = site => rules.locator('.site-group').filter({has:control.getByText(site,{exact:true})});
    await siteGroup(origin).getByRole('button').filter({hasNotText:'/users'}).filter({hasNotText:'/mes'}).click();
    await control.locator('#workshop-base').selectOption({label:'一号基地'});
    await control.locator('#workshop-choice').selectOption({label:'包装车间'});
    await persist();
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
    await control.locator('#float-refresh').click();
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
    const panel = await frame.frameElement();
    const before = await panel.boundingBox();
    assert.equal(Math.round(before.width),518,'阅读浮窗宽度');
    await mes.mouse.move(before.x + 80, before.y - 22);
    await mes.mouse.down(); await mes.mouse.move(before.x - 75, before.y + 8, {steps:8}); await mes.mouse.up();
    const after = await panel.boundingBox();
    assert.ok(Math.abs(after.x - before.x + 155) < 2 && Math.abs(after.y - before.y - 30) < 2, '窗口随拖动移动');
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
    await mes.mouse.click(after.x + after.width - 25, after.y - 22);
    assert.equal(await panel.boundingBox(),null);
    for (let i = 0; i < 3; i++) {fixture.stdin.write('advance\n'); assert.equal((await next()).jobs, 1);}
    await frame.waitForFunction(() => document.querySelector('.answer small')?.textContent === '已完成', null, {polling:100, timeout:12000});
    await host.click();
    assert.equal(await draft.inputValue(), '未发送的追问');
    await frame.locator('.answer strong').filter({hasText:'缺少批号'}).waitFor();
    assert.equal(await frame.locator('.answer table tbody tr').count(), 1);
    await frame.locator('.answer pre code').waitFor();
    await checkReply(frame, control);
    await stopCollectorWorker(context, control, id);
    // The test profile pre-grants host permissions. Exercise the API surface of the
    // field installation, where the embedded extension page only has messaging.
    await frame.evaluate(() => {
      Object.defineProperty(chrome, 'tabs', {configurable:true, value:undefined});
      Object.defineProperty(chrome.runtime, 'openOptionsPage', {configurable:true, value:undefined});
      window.addEventListener('error', event => { window.__floatError = event.message; });
    });
    assert.equal(await frame.evaluate(() => typeof chrome.tabs), 'undefined');
    const historyUrl = 'chrome-extension://' + id + '/control.html#conversations';
    const [historyPage] = await Promise.all([
      context.waitForEvent('page', {timeout:5000}),
      frame.locator('#agent-open-history').click(),
    ]).catch(async error => { throw new Error(await frame.evaluate(() => window.__floatError) || error.message); });
    await historyPage.waitForURL(historyUrl);
    await historyPage.close();
    await mes.bringToFront();
    await frame.locator('#agent-connection summary').click();
    await frame.locator('#agent-open-console').click();
    const consoleFocused = await control.evaluate(async () => {
      const url = chrome.runtime.getURL('control.html');
      for (let attempt = 0; attempt < 50; attempt++) {
        const [tab] = await chrome.tabs.query({active:true, currentWindow:true});
        if (tab?.url?.split('#')[0] === url) return true;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      return false;
    });
    assert.ok(consoleFocused, '控制台应在当前窗口获得焦点');
    await mes.bringToFront();
    assert.equal(await frame.evaluate(() => window.__floatError), undefined);
    assert.equal(await draft.inputValue(), '未发送的追问');
    for (const type of ['float.captureStart','float.captureStop']) {
      const reply=await frame.evaluate(type=>chrome.runtime.sendMessage({type,ticket:location.hash.slice(1)}),type);
      assert.equal(reply?.ok,false,'嵌入的对话页不能发起采集命令');
    }
    for (const fields of [{ticket:'unregistered',view:'history'}, {ticket:undefined,view:'https://example.test'}]) {
      const result = await frame.evaluate(fields => chrome.runtime.sendMessage({
        type:'float.openControl', ...fields, ticket:fields.ticket ?? location.hash.slice(1),
      }), fields);
      assert.equal(result?.ok, false);
    }
    await control.locator('nav a[href="#sites"]').click();
    assert.equal(await mes.locator('body').getByText(question).count(), 0);
    await mes.reload(); await host.waitFor();
    const recovered = await open();
    await recovered.locator('.answer strong').filter({hasText:'缺少批号'}).waitFor();
    assert.equal(await recovered.locator('.question').count(), 1);
    const sibling=await context.newPage();
    try {
      await sibling.goto(mes.url());
      await sibling.locator('[data-mes-agent-host]').waitFor();
      await checkPageLauncher(context,control,mes,sibling);
    } finally {await sibling.close();}
    if (process.env.EA_CHAT_PREVIEW_DIR) {
      await recovered.locator('#agent-answers').evaluate(el => { el.scrollTop = 0; });
      await (await recovered.frameElement()).screenshot({path:join(process.env.EA_CHAT_PREVIEW_DIR, 'agent-chatgpt-floating.png')});
    }
    const posts = requests.filter(([method,path]) => method === 'POST' && path.endsWith('/messages'));
    assert.equal(posts.length, 1);
    assert.ok(!requests.some(([method,path]) => method === 'GET' && path.includes('/messages/')),
      '平台明确拒绝的问题不应进入丢失回执恢复');
    await checkStopReply(recovered, mes, requests);
    await rules.locator('[data-binding-id="' + mesRuleId + '"]').click();
    await control.locator('#site-floating').uncheck(); await persist();
    await host.waitFor({state:'detached'});
    await other.reload(); await otherHost.waitFor();
    await control.reload();
    await rules.locator('[data-binding-id="' + mesRuleId + '"]').click();
    assert.ok(!await control.locator('#site-floating').isChecked());
    await siteGroup(secondOrigin).getByRole('button').click();
    await control.locator('#site-floating').uncheck(); await persist();
    await otherHost.waitFor({state:'detached'});
    await mes.reload(); assert.equal(await host.count(), 0);
    await rules.locator('[data-binding-id="' + mesRuleId + '"]').click();
    await control.locator('#site-floating').check(); await persist();
    await host.waitFor();
    await control.locator('nav a[href="#capture"]').click();
    await control.locator('#refresh').click();
    await control.locator('#tab-search').fill(origin);
    await control.locator('#select-all').check();
    await control.locator('#record-mode').selectOption('continuous');
    await start.click();
    await control.waitForFunction(() => document.querySelector('#live-tabs').textContent.includes('正在采集'));
    const switchingFrame = await open();
    await switchingFrame.waitForFunction(() => !document.querySelector('#agent-send').disabled);
    await switchingFrame.evaluate(() => {
      Object.defineProperty(chrome, 'tabs', {configurable:true, value:undefined});
    });
    await switchingFrame.locator('#agent-connection summary').click();
    await switchingFrame.locator('#agent-switch').click();
    await signIn('demo-second', true);
    await control.waitForFunction(() => document.querySelector('#agent-account')?.textContent.includes('demo-second')
      && !document.querySelector('#agent-send').disabled);
    await host.waitFor({state:'detached'});
    await control.waitForFunction(async () => !(await chrome.runtime.sendMessage({type:'session.status'})).continuous);
    await control.locator('nav a[href="#sites"]').click();
    await rules.getByText('暂无地址规则').waitFor();
    assert.equal(await control.locator('#workshop-environment option').count(), 1, '换账号后不得继承其他用户的环境车间');
    assert.ok(await control.locator('#workshop-revoke').isHidden());
    console.log(JSON.stringify({workerRestart:true, floatingNavigation:true, workshopScope:true, accountSwitch:true, floatingHost:mesHost, launcherDrag:true, windowDrag:true, multiSite:true, collapsedStream:true, draftRetained:true, reloaded:true, disabled:true, submittedJobs:posts.length}));
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
