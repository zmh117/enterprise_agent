import assert from 'node:assert/strict';
import { copyFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

// Only the worker is a fixture. Chrome loads the shipped recorder in an isolated world.
const root = await mkdtemp(join(tmpdir(), 'mes-recorder-reload-'));
const extension = join(root, 'extension');
const origin = 'http://recorder.test';
const url = origin + '/applications/assist03';
let context;
try {
  await mkdir(extension);
  await copyFile(resolve('dist/live-recorder.js'), join(extension, 'live-recorder.js'));
  await writeFile(join(extension, 'manifest.json'), JSON.stringify({
    manifest_version: 3, name: 'MES recorder reload fixture', version: '1.0',
    background: {service_worker: 'background.js'},
    content_scripts: [{matches: [origin + '/*'], js: ['live-recorder.js', 'probe.js']}],
  }));
  await writeFile(join(extension, 'background.js'), `
    chrome.runtime.onMessage.addListener((message, sender, reply) => {
      const tab = sender.tab.id;
      if (message.type === 'probe.start') {
        const rule = {origin: new URL(sender.url).origin, path: '/applications', hash_path: '', query: {}};
        const binding = {id:'binding', revision:1, enabled:true, reserved_paths:[], environment_id:'test', base_id:null, workshop_id:null, rule};
        const key = message.policy;
        const pagePolicy = key ? {maskAllText:key==='masked',allowedInputNames:['quantity','station'],sensitiveSelectors:['.private-fixture']} : undefined;
        chrome.tabs.sendMessage(tab, {type:'live.begin', ticket:{id:crypto.randomUUID(), pagePolicy, binding, rules:[binding], platformOrigin:'https://platform.test'}});
      } else if (message.event?.kind === 'baseline' || message.type === 'live.gap' || message.type === 'live.pause') {
        chrome.tabs.sendMessage(tab, {type:'probe.observed', value:message.event?.kind ?? message.type});
      }
      reply({ok: !(sender.url.endsWith('?gap') && message.event?.kind === 'action')});
    });
  `);
  await writeFile(join(extension, 'probe.js'), `
    const marker = document.documentElement.dataset;
    const policy = new URL(location.href).searchParams.get('policy');
    if (policy) {
      const events = [];
      const send = chrome.runtime.sendMessage.bind(chrome.runtime);
      chrome.runtime.sendMessage = message => {
        if (message.type === 'live.event') events.push(message.event);
        return send(message);
      };
      window.addEventListener('probe-results', () => window.postMessage({type:'fixture-events',events},location.origin));
    }
    // Older Chrome bindings can still be present and throw synchronously upon invalidation.
    if (location.search === '?sync' || location.search === '?reject') {
      const send = chrome.runtime.sendMessage.bind(chrome.runtime);
      chrome.runtime.sendMessage = message => {
        if (message.type === 'live.gap' || message.event?.kind === 'action') {
          const error = new Error('Extension context invalidated.');
          if (location.search === '?sync') throw error;
          return Promise.reject(error);
        }
        return send(message);
      };
    }
    chrome.runtime.onMessage.addListener(message => {
      if (message.type === 'probe.observed') marker.observed = message.value;
    });
    window.addEventListener('probe-recorder', () => {
      marker.recording = String(!!globalThis.__mesLiveTicket);
    });
    window.addEventListener('unhandledrejection', e => { marker.rejection = e.reason?.stack ?? String(e.reason); });
    chrome.runtime.sendMessage({type:'probe.start',policy}).catch(error => { marker.startError = error.message; });
  `);
  context = await chromium.launchPersistentContext(join(root, 'profile'), {
    channel:'chromium', headless:true, ignoreDefaultArgs:['--disable-extensions'],
    args:['--enable-unsafe-extension-debugging', '--disable-extensions-except=' + extension],
  });
  const cdp = await context.browser().newBrowserCDPSession();
  await cdp.send('Extensions.loadUnpacked', {path:extension});
  await cdp.detach();
  await context.route(origin + '/**', route => route.fulfill({
    contentType:'text/html; charset=utf-8', body:new URL(route.request().url()).searchParams.has('policy') ? `<!doctype html>
    <title>合成排产</title><p>班次二</p><p hidden>PRIVATE-hidden</p>
    <table><thead><tr><th>工单</th><th>操作</th><th>Token</th></tr></thead>
    <tbody><tr><td>WO-2</td><td><button id="edit"><span>编辑</span><span class="private-fixture">PRIVATE-child</span></button></td><td>PRIVATE-cell</td></tr></tbody></table>
    <label>批号<input name="batch" value="PRIVATE-batch"></label>
    <label>数量<input name="quantity" value="8"></label>
    <input type="password" value="PRIVATE-password"><div data-raw-message>PRIVATE-message</div>
    <div role="combobox" id="station" aria-label="工序" aria-controls="choices"></div>
    <div role="listbox" id="choices"><span role="option">制粒</span></div>
    <div id="state">待确认</div><span id="long"></span><canvas></canvas>` :
    '<!doctype html><button>测试操作</button>',
  }));
  const errors = [];
  async function recordingPage(address) {
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(address);
    await page.locator('html[data-observed="baseline"]').waitFor();
    return page;
  }
  async function assertStopped(page) {
    await page.waitForFunction(() => {
      window.dispatchEvent(new Event('probe-recorder'));
      return document.documentElement.dataset.recording === 'false';
    });
    // Let Chrome deliver unhandledrejection after the failed message's microtasks.
    await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
    assert.equal(await page.locator('html').getAttribute('data-rejection'), null);
  }
  for (const policy of ['limited','masked']) {
    const page = await recordingPage(url + '?policy=' + policy);
    await page.locator('#edit span').first().click();
    await page.getByLabel('批号').fill('PRIVATE-edited');
    await page.getByLabel('数量').fill('12');
    await page.getByLabel('数量').press('Tab');
    await page.getByRole('option').click();
    await page.evaluate(() => {
      document.getElementById('state').firstChild.data='已提交';
      document.getElementById('long').textContent='文'.repeat(1024);
      document.querySelector('.private-fixture').textContent='PRIVATE-mutation';
      document.title='提交详情';
    });
    // A real trusted click flushes the pending DOM update.
    await page.locator('#edit span').first().click();
    const events = await page.evaluate(async () => {
      const until = Date.now()+5000;
      while (true) {
        const reply = new Promise(resolve => {
          const read = e => {
            if (e.source === window && e.data?.type === 'fixture-events') {
              window.removeEventListener('message',read);
              resolve(e.data.events);
            }
          };
          window.addEventListener('message',read);
        });
        window.dispatchEvent(new Event('probe-results'));
        const events = await reply;
        if (events.filter(e => e.kind==='action' && e.action==='click' && e.element==='button').length >= 2) return events;
        if (Date.now()>until) throw Error('Missing edit clicks: '+JSON.stringify(events.map(e=>[e.kind,e.action,e.element])));
        await new Promise(resolve=>setTimeout(resolve,25));
      }
    });
    const json = JSON.stringify(events);
    assert.ok(!json.includes('PRIVATE-'));
    if (policy === 'masked') {
      for (const literal of ['合成排产','班次二','WO-2','制粒','已提交','提交详情','"12"']) assert.ok(!json.includes(literal));
    } else {
      const action = events.find(e => e.action==='change' && e.field_name==='quantity');
      assert.deepEqual([action.field_label,action.before_value,action.value],['数量','8','12']);
      const pick = events.find(e => e.selection==='制粒');
      assert.equal(pick.field_label,'工序');
      assert.ok(events.some(e => e.kind==='baseline' && e.page_coverage.includes('embedded_content_omitted')));
      assert.ok(events.some(e => e.kind==='mutation' && e.page_title==='提交详情' && e.page_coverage.includes('budget_limited')));
      assert.ok(json.includes('已提交'));
    }
    await page.close();
  }
  for (const mode of ['sync', 'reject']) {
    const fault = await recordingPage(url + '?' + mode);
    await fault.getByRole('button').click();
    await assertStopped(fault);
    await fault.close();
  }
  const mutation = await recordingPage(url);
  const navigation = await recordingPage(url);
  const healthy = await recordingPage(url + '?gap');
  await healthy.getByRole('button').click();
  await healthy.locator('html[data-observed="live.gap"]').waitFor();
  await healthy.goto(url);
  await healthy.locator('html[data-observed="baseline"]').waitFor();
  await healthy.evaluate(() => history.pushState({}, '', '/elsewhere'));
  await healthy.locator('html[data-observed="live.pause"]').waitFor();

  const manager = await context.newPage();
  await manager.goto('chrome://extensions');
  await manager.locator('#devMode').check();
  const card = manager.locator('extensions-item').filter({hasText:'MES recorder reload fixture'});
  const newWorker = context.waitForEvent('serviceworker', {predicate:w => w.url().endsWith('/background.js')});
  await card.locator('#dev-reload-button').click();
  await newWorker;
  await mutation.evaluate(() => document.body.append(document.createElement('p')));
  await navigation.evaluate(() => history.pushState({}, '', '/elsewhere'));
  for (const page of [mutation, navigation]) await assertStopped(page);
  await mutation.reload();
  await mutation.locator('html[data-observed="baseline"]').waitFor();
  assert.deepEqual(errors, []);
  console.log('已验证扩展重载时的 DOM 变更和跨范围导航，以及有效上下文中的缺口、暂停和刷新后的新基线。');
} finally {
  try { await context?.close(); }
  finally { await rm(root, {recursive:true, force:true}); }
}
