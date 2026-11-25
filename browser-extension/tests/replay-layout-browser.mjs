// 从实际录制脚本取得事件，再在断网播放器中比较 CSS 像素坐标。
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium, webkit } from 'playwright';
import { zipSync, strToU8 } from 'fflate';
import { DEFAULT_POLICY } from '../shared/policy.ts';

const root = await mkdtemp(join(tmpdir(),'mes-css-test-'));
const css = '#action{position:absolute;left:287px;top:171px;width:92px;height:38px}';
const late = '#action{top:208px}';
const engine = process.env.MES_REPLAY_WEBKIT === '1' ? webkit : chromium;
let browser, recordingBrowser;
async function startCapture(page, policy) {
  await page.addScriptTag({path:resolve('dist/recorder.js')});
  await page.evaluate(policy => {
    window.events = [];
    window.addEventListener('message', ({data}) => {
      if (data?.type !== 'packet') return;
      const packet = JSON.parse(data.json);
      if (packet.kind === 'rrweb.event') window.events.push(packet.payload.rrwebEvent);
    });
    window.postMessage({channel:'mes-evidence-v1', type:'start',ticket:{
      id:'fixture', nonce:'abc', recorderStreamId:'r', documentId:'d', mode:'top', policy
    }},location.origin);
  },policy);
  await page.waitForFunction(()=>window.events.some(e=>e.type===2));
}
try {
  recordingBrowser = await chromium.launch({executablePath:process.env.MES_TEST_CHROME});
  const capture = await recordingBrowser.newPage({viewport:{width:900,height:600}});
  await capture.route('http://capture.test/**', route => {
    const path = new URL(route.request().url()).pathname;
    return path.endsWith('.css') ? route.fulfill({contentType:'text/css',body:path.endsWith('late.css') ? late : css}) :
      route.fulfill({contentType:'text/html',body:'<!doctype html><link rel="stylesheet" href="/assets/app.css"><button id="action">确认</button>'});
  });
  await capture.goto('http://capture.test/');
  await startCapture(capture, DEFAULT_POLICY);
  await capture.evaluate(()=>{ const el=document.createElement('link'); el.rel='stylesheet'; el.href='/assets/late.css'; document.head.append(el); });
  await capture.waitForFunction(()=>document.querySelector('button').getBoundingClientRect().top===208);
  // 开始快照中没有这个新节点。拖动进度时必须先重建它，才能定位后续点击。
  await capture.evaluate(()=>{
    const old = document.querySelector('button');
    old.replaceWith(old.cloneNode(true));
  });
  await capture.locator('#action').click();
  await capture.waitForFunction(()=>window.events.some(e=>e.type===3 && e.data.source===2 && e.data.type===2));
  const events = await capture.evaluate(()=>window.events);
  assert.ok(JSON.stringify(events.find(e=>e.type===2)).includes('287px'));
  assert.ok(JSON.stringify(events).includes('208px'));
  const click = events.find(e=>e.type===3 && e.data.source===2 && e.data.type===2);
  const point = {x:click.data.x,y:click.data.y};
  const rect = await capture.locator('#action').evaluate(el=>el.getBoundingClientRect().toJSON());
  events.push({type:5,timestamp:events.at(-1).timestamp+2000,data:{tag:'fixture-end',payload:{}}});
  const largePage = await recordingBrowser.newPage();
  const rules = Array.from({length:500}, (_,i)=>'.cell'+i+'{margin-left:'+i+'px}').join('\n');
  await largePage.route('http://budget.test/**', route => route.request().url().endsWith('.css')
    ? route.fulfill({contentType:'text/css',body:rules})
    : route.fulfill({contentType:'text/html',body:'<!doctype html><link rel="stylesheet" href="a.css"><link rel="stylesheet" href="b.css"><main>预算测试</main>'}));
  await largePage.goto('http://budget.test/');
  await startCapture(largePage, {...DEFAULT_POLICY,budgets:{...DEFAULT_POLICY.budgets,baselineBytes:24000}});
  await largePage.waitForFunction(()=>window.events.filter(e=>e.type===3 && e.data.source===0 && e.data.attributes.some(a=>a.attributes._cssText?.includes('.cell499'))).length>=2);
  assert.ok(!(await largePage.evaluate(()=>JSON.stringify(window.events.find(e=>e.type===2)))).includes('.cell499'));
  await recordingBrowser.close(); recordingBrowser=undefined;
  browser = await engine.launch(engine===chromium ? {executablePath:process.env.MES_TEST_CHROME} : {});
  const p = await browser.newPage({offline:true,viewport:{width:1100,height:800}});
  const errors=[]; p.on('pageerror',e=>errors.push(e.message));
  await p.goto(pathToFileURL(resolve('release/MES-rrweb-replay.html')).href);
  async function load(list) {
    const lines=list.map((rrwebEvent,sourceSeq)=>JSON.stringify({recordingId:'s',tabInstanceId:'t',recorderStreamId:'r',sourceSeq,kind:'rrweb.event',payload:{rrwebEvent}})).join('\n');
    await p.locator('#zip').setInputFiles({name:'sample.zip',mimeType:'application/zip',buffer:Buffer.from(zipSync({'rrweb/00000001.ndjson':strToU8(lines)}))});
    await p.locator('.rr-progress__slider').waitFor();
    await p.locator('.rr-progress__slider').focus(); await p.keyboard.press('End');
  }
  const action=p.frameLocator('.replayer-wrapper iframe').first().locator('#action');
  async function checkAligned() {
    const actual=await action.evaluate(el=>el.getBoundingClientRect().toJSON());
    for (const key of ['x','y','width','height']) assert.equal(actual[key],rect[key],key);
    const cursor=await p.locator('.replayer-mouse').evaluate(el=>({x:parseFloat(el.style.left),y:parseFloat(el.style.top)}));
    assert.deepEqual(cursor,point);
    assert.ok(cursor.x>=actual.x && cursor.x<=actual.right && cursor.y>=actual.y && cursor.y<=actual.bottom);
    await p.waitForFunction(()=> {
      const mouse=document.querySelector('.replayer-mouse').getBoundingClientRect();
      const frame=document.querySelector('.replayer-wrapper iframe');
      const screen=frame.getBoundingClientRect(), button=frame.contentDocument.querySelector('#action').getBoundingClientRect();
      const scale=screen.width/frame.offsetWidth;
      return mouse.left>=screen.left+button.left*scale && mouse.left<=screen.left+button.right*scale &&
        mouse.top>=screen.top+button.top*scale && mouse.top<=screen.top+button.bottom*scale;
    });
  }
  await load(events);
  await checkAligned();
  await p.setViewportSize({width:720,height:780});
  await checkAligned();
  // 旧包只含引用。用同位置的单个外部样式等价重建目标布局。
  const legacy=structuredClone(events);
  function strip(node) {
    if (node.tagName==='link' && node.attributes._cssText) node.attributes={rel:'stylesheet',href:'http://capture.test/assets/'+(node.attributes._cssText.includes('208px') ? 'late.css' : 'app.css')};
    for (const child of node.childNodes || []) strip(child);
  }
  strip(legacy.find(e=>e.type===2).data.node);
  for (const e of legacy.filter(e=>e.type===3 && e.data.source===0)) {
    for (const add of e.data.adds) strip(add.node);
    for (const update of e.data.attributes) delete update.attributes._cssText;
  }
  await load(legacy);
  await p.locator('#layout-message').filter({hasText:'2 个外部样式表缺少正文'}).waitFor();
  await p.locator('#click-target').filter({hasText:'橙框'}).waitFor();
  assert.notEqual(await action.evaluate(el=>el.getBoundingClientRect().left),rect.x);
  const dir=join(root,'dist');
  await mkdir(join(dir,'assets'),{recursive:true});
  await writeFile(join(dir,'assets/app.css'),css);
  await writeFile(join(dir,'assets/late.css'),late);
  await p.locator('#styles-folder').setInputFiles(dir);
  await p.locator('#layout-message').filter({hasText:'已补入本页引用的 2 个'}).waitFor();
  await checkAligned();
  assert.deepEqual(errors,[]);
  console.log('页面布局与点击坐标一致，已验证新录制静态/动态样式、旧包目标标记以及本地 CSS 回补。');
} finally {
  await browser?.close(); await recordingBrowser?.close(); await rm(root,{recursive:true,force:true});
}
