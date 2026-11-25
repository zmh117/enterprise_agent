import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { zipSync, strToU8 } from 'fflate';
import { chromium } from 'playwright';

const base = 1700000000000;
const iso = offset => new Date(base + offset).toISOString();
const recordingId = 'demo';
function pageEvents(tab, host) {
  const data = {node:{type:0,id:1,childNodes:[{type:2,tagName:'html',attributes:{},id:2,childNodes:[
    {type:2,tagName:'head',attributes:{},childNodes:[],id:3},
    {type:2,tagName:'body',attributes:{},childNodes:[{type:3,id:5,textContent:'工单'}],id:4},
  ]}]},initialOffset:{left:0,top:0}};
  const textAt = (time, value) => ({type:3, timestamp:base + time, data:{
    source:0, texts:[{id:5, value}], attributes:[], removes:[], adds:[]
  }});
  return [
    {type:4,timestamp:base,data:{href:'https://' + host,width:800,height:600}},
    {type:2,timestamp:base+1,data},
    textAt(800, '正在提交工单'),
    textAt(1400, '工单已提交'),
    {type:5,timestamp:base+3500,data:{tag:'end',payload:{}}},
  ].map((rrwebEvent, sourceSeq) => ({recordingId, tabInstanceId:tab, recorderStreamId:tab,
    emitterContext:{documentId:tab}, sourceSeq, kind:'rrweb.event',payload:{rrwebEvent}}));
}
const post = {
  recordingId, tabInstanceId:'a', documentId:'a', requestKey:'post', startedAt:iso(2800), endedAt:iso(4400), networkOutcome:'finished',
  request:{url:'https://api.example/orders?item=A%2BB&item=C',method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
    bodyCaptureStatus:'captured',bodyRef:'bodies/post.txt'},
  response:{httpStatus:201,bodyCaptureStatus:'captured',bodyRef:'bodies/result.json'},
};
const child = {...post, tabInstanceId:'b', documentId:'b', requestKey:'child', startedAt:iso(-500), endedAt:iso(600),
  response:{httpStatus:503,bodyCaptureStatus:'unavailable',bodyCaptureReason:'network_failed'}};
const missing = {...post, requestKey:'missing', startedAt:iso(3000), endedAt:iso(3200),
  request:{...post.request, method:'GET', url:'https://api.example/orders/missing',bodyCaptureStatus:'empty',bodyRef:null},
  response:{httpStatus:200,bodyCaptureStatus:'captured',bodyRef:'bodies/missing.txt'}};
const observed = (kind, timestamp, extra) => ({kind:'network.'+kind, observedAt:iso(6000), payload:{requestKey:'post',timestamp,...extra}});
const ndjson = data => data.map(row=>JSON.stringify(row)).join('\n')+'\n';
const files = {
  'events/00000001.ndjson':ndjson([...pageEvents('a','mes.example'),observed('request_observed',80,{wallTime:(base+800)/1000})]),
  'rrweb/00000002.ndjson':ndjson(pageEvents('b','child.example')),
  'network/00000003.ndjson':ndjson([observed('response_observed',81.2),observed('loading_finished',83.6)]),
  'network/index-000000.ndjson':ndjson([child,missing,post]),
  'bodies/post.txt':'name=A%2BB&code=3',
  'bodies/result.json':'{"value":"<img src=x onerror=alert(1)>","id":12345678901234567890}',
};
const root = await mkdtemp(join(tmpdir(),'mes-replay-panel-test-'));
let browser;
try {
  const folder = join(root,'recording');
  for (const [path,data] of Object.entries(files)) {
    await mkdir(dirname(join(folder,path)), {recursive:true});
    await writeFile(join(folder,path),data);
  }
  const zip = join(root,'recording.zip');
  await writeFile(zip,zipSync(Object.fromEntries(Object.entries(files).map(([k,v])=>['recording/'+k,strToU8(v)]))));
  browser = await chromium.launch({executablePath:process.env.MES_TEST_CHROME,headless:true});
  const page = await browser.newPage({offline:true, viewport:{width:1280,height:850}});
  await page.goto(pathToFileURL(resolve('release/MES-rrweb-replay.html')).href);
  const errors = [];
  page.on('pageerror', e=>errors.push(e.message));
  const count = page.locator('#count'), panel=page.locator('#network');
  const track=page.locator('.rr-progress');
  async function waitText(locator, wanted) {
    await locator.filter({hasText:wanted}).first().waitFor({timeout:4500});
  }
  async function seek(fraction) {
    const rect = await track.boundingBox();
    await page.mouse.click(rect.x+Math.max(1,(rect.width-1)*fraction), rect.y+rect.height/2);
  }
  for (const input of ['zip','folder']) {
    await page.locator('#'+input).setInputFiles(input==='zip'?zip:folder);
    await waitText(count,'0 / 2');
    const filter = panel.getByLabel('筛选接口路径');
    const first = panel.locator('.request-entry').filter({has:page.getByRole('button',{name:/POST api\.example\/orders$/})});
    const other = panel.locator('.request-entry').filter({has:page.getByRole('button',{name:/GET .*missing$/})});
    const screen = page.frameLocator('.replayer-wrapper iframe').first().locator('body');
    for (const query of ['api.example','item','unmatched']) {
      await filter.fill(query);
      await waitText(panel,'没有匹配的接口路径');
      assert.equal(await panel.locator('.request-entry').count(),0);
    }
    await filter.fill(' /ORDERS ');
    await waitText(count,'匹配 2 条');
    await waitText(first,'尚未发起');
    await other.getByRole('button').focus();
    await page.keyboard.press('Enter');
    await waitText(screen,'工单已提交');
    assert.ok(await other.locator('details').evaluate(el=>el.open));
    await first.getByRole('button').click();
    await waitText(screen,'正在提交工单');
    await waitText(first,'等待响应');
    await waitText(other,'尚未发起');
    assert.equal(await filter.inputValue(),' /ORDERS ');
    await filter.fill('');
    await waitText(count,'1 / 2');
    await seek(0.3);
    await waitText(first.getByRole('button'),'等待响应');
    await first.locator('summary').click();
    await waitText(first,'item = A+B');
    await waitText(first,'item = C');
    await waitText(first,'name = A+B');
    await waitText(first,'尚未到达响应完成时间');
    await seek(0.53);
    await waitText(first,'HTTP 201');
    assert.ok(!(await first.textContent()).includes(files['bodies/result.json']));
    // 最后一条响应在最后一帧之后，按 End 必须仍然可以查看。
    await page.locator('.rr-progress__slider').focus();
    await page.keyboard.press('End');
    await waitText(count,'2 / 2');
    await waitText(first,files['bodies/result.json']);
    assert.equal(await first.locator('img').count(),0);
    await other.locator('summary').click();
    await waitText(other,'包内缺少正文附件');
    await seek(0.3);
    await waitText(count,'1 / 2');
    assert.equal(await other.count(),0);
    await waitText(first,'等待响应');
    assert.ok(!(await first.textContent()).includes(files['bodies/result.json']));
    await seek(0.01);
    await waitText(count,'0 / 2');
    await page.locator('.rr-controller__btns button').first().click();
    await waitText(count,'1 / 2');
    await page.locator('.rr-controller__btns button').first().click();
    await seek(0.90);
    await first.locator('summary').click();
    await waitText(first,'尚未到达响应完成时间');
    await page.locator('.rr-controller__btns button').first().click();
    await waitText(first,files['bodies/result.json']);
    await filter.fill('/missing');
    await page.locator('#stream').selectOption({index:1});
    await waitText(panel,'没有匹配的接口路径');
    await filter.fill('orders');
    await panel.getByRole('button',{name:/定位到/}).click();
    await waitText(panel,'早于首个页面快照');
    assert.equal(await screen.textContent(),'工单');
    await filter.fill('');
    await seek(0.75);
    await waitText(count,'1 / 1');
    await waitText(panel,'HTTP 503');
    await panel.locator('summary').click();
    await waitText(panel,'network_failed');
  }
  assert.deepEqual(errors,[]);
  console.log('通过 ZIP 与文件夹回放测试，覆盖路径筛选、请求定位与页面快照、时间同步、跨页隔离和正文明细。');
} finally {
  await browser?.close();
  await rm(root,{recursive:true,force:true});
}
