// The plugin sends synthetic questions to the platform's local test server.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createServer, request as upstreamRequest } from 'node:http';
import {
  cp,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises';
import { createServer as createTlsServer } from 'node:https';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import { createHash, X509Certificate, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import {
  sampleRecordingMemory,
  seedLargeRecording,
  previewRecording,
  captureSave,
} from './agent-recording-browser.mjs';
import { checkFloat } from './float-browser.mjs';
import { chromium } from 'playwright';

const agentRoot = fileURLToPath(new URL('../../', import.meta.url));
const withRecording = process.env.EA_TEST_RECORDING === '1';
const throughNginx = process.env.EA_TEST_NGINX === '1';
let nginxContainer;
let heartbeats = 0;
const root = await mkdtemp(join(tmpdir(), 'mes-agent-stream-'));
let context, fixture, upstream, streamSocket;
let unavailable = false;
const floating = process.env.EA_TEST_FLOAT === '1';
const mesHost = process.env.EA_FLOAT_HOST ?? 'mes-qa.test';
let lostMessageReceipt = floating;
let rejectFirstFloatingMessage = floating;
const cursors = [];
const requests = [];
const uploads = [];
let lostPart = false,
  pauseParts = false,
  wireBytes = 0;
const profile = process.env.EA_TEST_ORIGIN ?? 'loopback';
assert.ok(['loopback', 'http-host', 'https-host'].includes(profile));
const hostname = profile === 'loopback' ? '127.0.0.1' : 'agent-qa.test';
const tls = profile === 'https-host';
const scheme = tls ? 'https' : 'http';
const flags =
  profile === 'loopback'
    ? []
    : [
        '--host-resolver-rules=MAP agent-qa.test 127.0.0.1',
        '--no-proxy-server',
      ];
let expireReceipt;
async function forward(req, res) {
  if (rejectFirstFloatingMessage && req.method === 'POST' && req.url.endsWith('/messages')) {
    rejectFirstFloatingMessage = false;
    res.writeHead(409, {'Content-Type':'application/json'});
    res.end(JSON.stringify({code:'application_unavailable'}));
    return;
  }
  if (
    expireReceipt &&
    req.method === 'GET' &&
    req.url.split('?')[0].includes('/messages/')
  ) {
    const expire = expireReceipt;
    expireReceipt = undefined;
    await expire();
  }
  if (
    pauseParts &&
    (req.url.endsWith('/recordings') || req.url.includes('/parts/'))
  ) {
    res.writeHead(503);
    res.end('{}');
    return;
  }
  if (req.method === 'PUT' && req.url.includes('/parts/')) {
    uploads.push(req.url.split('/').at(-1));
    req.on('data', (b) => {
      wireBytes += b.length;
    });
  }
  const streaming = req.url.endsWith('/events');
  if (streaming) {
    cursors.push(Number(req.headers['last-event-id'] ?? 0));
    if (unavailable) {
      res.writeHead(503);
      res.end();
      return;
    }
    streamSocket = res.socket;
  }
  if (!upstream) {
    res.writeHead(503);
    res.end();
    return;
  }
  const forwarded = upstreamRequest(
    {
      hostname: '127.0.0.1',
      port: upstream,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, 'x-forwarded-proto': scheme },
    },
    (reply) => {
      requests.push([req.method, req.url.split('?')[0], reply.statusCode]);
      if (
        withRecording &&
        !lostPart &&
        req.method === 'PUT' &&
        req.url.includes('/parts/') &&
        reply.statusCode === 200
      ) {
        lostPart = true;
        pauseParts = true;
        reply.resume();
        res.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': '128',
        });
        res.write('{', () => res.destroy());
        return;
      }
      if (
        !lostMessageReceipt &&
        req.method === 'POST' &&
        req.url.endsWith('/messages') &&
        reply.statusCode === 202
      ) {
        lostMessageReceipt = true;
        reply.resume();
        res.writeHead(202, {
          'Content-Type': 'application/json',
          'Content-Length': '128',
        });
        // Deliver the status then cut the JSON mid-body. Closing a reused socket
        // before headers can trigger a transparent HTTP retry inside Chromium.
        res.write('{', () => res.destroy());
        return;
      }
      res.writeHead(reply.statusCode, reply.headers);
      if (streaming && throughNginx) {
        let tail = '';
        reply.on('data', (chunk) => {
          tail += chunk.toString('utf8');
          const lines = tail.split('\n');
          tail = lines.pop();
          heartbeats += lines.filter((line) => line === ': heartbeat').length;
        });
      }
      reply.pipe(res);
      res.on('close', () => reply.destroy());
    },
  );
  forwarded.on('error', () => res.destroy());
  req.pipe(forwarded);
}
let proxy;
if (tls) {
  // Trust only this throwaway certificate in this Chrome profile.
  const keyPath = join(root, 'test-key.pem'),
    certPath = join(root, 'test-crt.pem');
  execFileSync(
    'openssl',
    [
      'req',
      '-x509',
      '-newkey',
      'rsa:2048',
      '-sha256',
      '-days',
      '1',
      '-nodes',
      '-subj',
      '/CN=agent-qa.test',
      '-addext',
      'subjectAltName=DNS:agent-qa.test',
      '-keyout',
      keyPath,
      '-out',
      certPath,
    ],
    { stdio: 'ignore' },
  );
  const cert = await readFile(certPath),
    key = await readFile(keyPath);
  const spki = new X509Certificate(cert).publicKey.export({
    type: 'spki',
    format: 'der',
  });
  flags.push(
    '--ignore-certificate-errors-spki-list=' +
      createHash('sha256').update(spki).digest('base64'),
  );
  proxy = createTlsServer({ key, cert }, forward);
} else proxy = createServer(forward);
await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
const origin = scheme + '://' + hostname + ':' + proxy.address().port;
try {
  await runBrowserTest();
} finally {
  await context?.close();
  if (fixture && fixture.exitCode === null) {
    const exited = new Promise((resolve) => fixture.once('exit', resolve));
    fixture.stdin.end('stop\n');
    await exited;
  }
  if (nginxContainer)
    execFileSync('docker', ['stop', '--time', '1', nginxContainer]);
  proxy.closeAllConnections();
  await new Promise((resolve) => proxy.close(resolve));
  await rm(root, { recursive: true, force: true });
}

async function checkReply(surface, control) {
  const thread = surface.locator('#agent-answers');
  const question = thread.locator('.chat-question').first();
  const answer = thread.locator('.chat-reply').first();
  const copy = answer.getByRole('button', {name: '复制回复'});
  const userBox = await question.boundingBox();
  const answerBox = await answer.boundingBox();
  const buttonBox = await copy.boundingBox();
  assert.ok(userBox && answerBox && buttonBox);
  assert.ok(userBox.x > answerBox.x && userBox.y + userBox.height <= answerBox.y);
  assert.ok(buttonBox.x < answerBox.x + 10 && buttonBox.y > answerBox.y);
  assert.equal(await question.getByRole('button').count(), 0);

  const activePage = surface.page?.() ?? surface;
  await activePage.bringToFront();
  assert.match(await answer.locator('.reply-duration').innerText(), /用时 .*(秒|分|小时)/);
  assert.match(await question.getAttribute('title'), /^提问时间 .+\d{2}:\d{2}:\d{2}$/);
  assert.match(await answer.getAttribute('title'), /^回答时间 .+\d{2}:\d{2}:\d{2}$/);
  const timeOpacity = el => getComputedStyle(el, '::after').opacity;
  await question.hover();
  assert.equal(await question.evaluate(timeOpacity), '1');
  await copy.hover();
  assert.equal(await answer.evaluate(timeOpacity), '1');
  assert.equal(await question.evaluate(timeOpacity), '0');
  assert.equal(await copy.evaluate(el => getComputedStyle(el, '::before').width), '8px');
  assert.ok(buttonBox.width >= 28 && buttonBox.height >= 28);
  await copy.click();
  await answer.getByRole('button', {name: '已复制'}).waitFor();
  await control.bringToFront();
  const expected = '我查一下。\n\n**缺少批号**。\n\n|项目|结果|\n|---|---|\n|校验|退回|\n\n```json\n{"ok":false}\n```';
  const paste = await control.evaluateHandle(() => {
    const field = document.createElement('textarea');
    document.body.append(field);
    return field;
  });
  try {
    await paste.press('ControlOrMeta+v');
    assert.ok(await paste.evaluate((field, source) => field.value === source, expected),
      '粘贴结果应只包含这条回复的完整 Markdown 原文');
  } finally {
    await paste.evaluate(field => field.remove());
    await paste.dispose();
  }
  await activePage.bringToFront();
}

async function runBrowserTest() {
  const unpacked = join(root, 'unpacked');
  await cp(resolve('dist'), unpacked, { recursive: true });
  const file = join(unpacked, 'manifest.json');
  const manifest = JSON.parse(await readFile(file, 'utf8'));
  // Pre-grant just this loopback host in the test copy to avoid an OS permission dialog.
  manifest.host_permissions = [...new Set([scheme + '://' + hostname + '/*', ...(floating ? ['http://' + mesHost + '/*', 'http://127.0.0.1/*', 'http://localhost/*'] : [])])];
  await writeFile(file, JSON.stringify(manifest));
  context = await chromium.launchPersistentContext(join(root, 'profile'), {
    channel: 'chromium',
    viewport: null,
    headless: true,
    ...(process.env.MES_TEST_CHROME
      ? { executablePath: process.env.MES_TEST_CHROME }
      : {}),
    ignoreDefaultArgs: ['--disable-extensions'],
    args: [
      ...flags,
      ...(floating ? ['--host-resolver-rules=MAP ' + mesHost + ' 127.0.0.1', '--no-proxy-server'] : []),
      '--headless=new',
      '--window-size=1280,820',
      '--disable-extensions-except=' + unpacked,
      '--load-extension=' + unpacked,
      '--enable-unsafe-extension-debugging',
    ],
  });
  let id;
  const ownWorker = (w) => w.url().endsWith('/background.js');
  const worker =
    context.serviceWorkers().find(ownWorker) ??
    (await context
      .waitForEvent('serviceworker', { predicate: ownWorker, timeout: 4000 })
      .catch(() => undefined));
  if (worker) id = new URL(worker.url()).hostname;
  else {
    // Branded Chrome builds load an unpacked extension via their extension debugging API.
    const cdp = await context.browser().newBrowserCDPSession();
    try {
      ({ id } = await cdp.send('Extensions.loadUnpacked', { path: unpacked }));
    } finally {
      await cdp.detach();
    }
  }
  fixture = spawn(
    join(agentRoot, '.venv/bin/python'),
    ['-m', 'backend.tests.support.browser_stream_server'],
    {
      cwd: agentRoot,
      stdio: ['pipe', 'pipe', 'inherit'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    },
  );
  const input = createInterface({ input: fixture.stdout })[
    Symbol.asyncIterator
  ]();
  async function next() {
    const { done, value } = await input.next();
    if (done) throw new Error('服务端测试进程已退出');
    return JSON.parse(value);
  }
  const config = await next();
  upstream = config.port;
  if (throughNginx) {
    const configPath = join(root, 'nginx.conf');
    const nginx = await readFile(
      join(agentRoot, 'frontend/nginx.conf'),
      'utf8',
    );
    assert.ok(nginx.includes('api-server:8000 resolve'));
    // In this fixture the fault proxy is the external TLS terminator.
    const upstreamConfig = nginx.replace(
      'api-server:8000 resolve',
      'host.docker.internal:' + upstream,
    );
    await writeFile(
      configPath,
      'access_log off;\n' +
        (tls
          ? upstreamConfig.replace(
              'X-Forwarded-Proto $scheme',
              'X-Forwarded-Proto https',
            )
          : upstreamConfig),
    );
    nginxContainer = 'ea-test-extension-' + randomUUID();
    execFileSync('docker', [
      'run',
      '--rm',
      '--pull=never',
      '-d',
      '--name',
      nginxContainer,
      '-p',
      '127.0.0.1::80',
      '-v',
      configPath + ':/etc/nginx/conf.d/default.conf:ro',
      'nginx:latest',
    ]);
    upstream = Number(
      execFileSync('docker', ['port', nginxContainer, '80/tcp'], {
        encoding: 'utf8',
      })
        .trim()
        .split(':')
        .at(-1),
    );
    let ready = false;
    for (let attempt = 0; attempt < 60 && !ready; attempt++) {
      ready = await fetch(
        'http://127.0.0.1:' + upstream + '/api/browser-extension/applications',
      ).then(
        (r) => r.status === 401,
        () => false,
      );
      if (!ready) await delay(200);
    }
    assert.ok(ready, '代理未能连到本次回环测试服务');
  }
  let control = await context.newPage();
  await control.goto('chrome-extension://' + id + '/control.html#assistant');
  await control.locator('#agent-origin').fill(origin + '/console/applications');
  assert.equal(await control.locator('#agent-http-note').isVisible(), !tls);
  await control.locator('#agent-login').click();
  async function signIn(username) {
    let authorization;
    for (let i = 0; i < 100 && !authorization; i++) {
      authorization = context
        .pages()
        .find((page) =>
          page
            .url()
            .startsWith(origin + '/api/browser-extension/auth/authorize?'),
        );
      if (!authorization) await delay(100);
    }
    assert.ok(authorization, 'Chrome 原生授权窗口未打开');
    await authorization.waitForFunction(() => outerWidth <= 480 && outerHeight <= 520);
    await authorization.locator('[name=username]').fill(username);
    await authorization.locator('[name=password]').fill(config.password);
    await authorization.locator('[value=login]').click();
    await authorization.locator('[value=allow]').click();
  }
  await signIn(config.username);
  const historyMode = process.env.EA_TEST_HISTORY === '1';
  if (historyMode) {
    await control.waitForFunction(() => document.querySelector('#agent-app')?.options.length === 2);
    await control.locator('#agent-app').selectOption({label:'合成诊断'});
  }
  try {
    await control.waitForFunction(
      () =>
        document.querySelector('#agent-app')?.selectedOptions[0]
          ?.textContent === '合成诊断',
    );
  } catch (e) {
    console.error(
      '登录阶段',
      await control.locator('#agent-status').textContent(),
      requests,
    );
    throw e;
  }
  assert.equal(await control.locator('#agent-origin').inputValue(), origin);
  assert.equal(await control.locator('#agent-app option').count(), historyMode ? 2 : 1);

  if (process.env.EA_CHAT_PREVIEW_DIR && !floating) {
    await control.locator('.chat-welcome').waitFor();
    await control.locator('#agent-question').focus();
    await control.screenshot({path:join(process.env.EA_CHAT_PREVIEW_DIR, 'agent-chatgpt-empty.png')});
  }
  if (floating) {
    return checkFloat({context, control, id, fixture, next, requests, mesHost, checkReply});
  }
  if (withRecording) {
    const sourceBytes = await seedLargeRecording(control, origin);
    await control.reload();
    const stopMemory = process.env.EA_TEST_RSS === '1'
      ? await sampleRecordingMemory(context.browser()) : undefined;
    const cdp = await context.newCDPSession(control);
    await cdp.send('Performance.enable');
    let peak = 0;
    const poll = setInterval(
      () =>
        cdp
          .send('Performance.getMetrics')
          .then(({ metrics }) => {
            peak = Math.max(
              peak,
              metrics.find((v) => v.name === 'JSHeapUsedSize').value,
            );
          })
          .catch(() => {}),
      50,
    );
    await previewRecording(control);
    const projected = Number(
      (await control.locator('#agent-record-status').textContent()).match(
        /待传 (\d+) 字节/,
      )[1],
    );
    await control.locator('#agent-record-share').click();
    for (let i = 0; i < 120 && !lostPart; i++) await delay(150);
    assert.ok(
      lostPart,
      JSON.stringify({
        uploads,
        status: await control.locator('#agent-record-status').textContent(),
      }),
    );
    clearInterval(poll);
    await control.close();
    pauseParts = false;
    fixture.stdin.write('expire\n');
    assert.equal((await next()).expired, true);
    control = await context.newPage();
    await control.goto('chrome-extension://' + id + '/control.html#assistant');
    await previewRecording(control);
    await control.locator('#agent-record-share').click();
    await control
      .waitForFunction(
        () =>
          document
            .querySelector('#agent-record-status')
            ?.textContent?.includes('可在本会话连续提问'),
        null,
        { timeout: 12000 },
      )
      .catch(async () => {
        throw new Error(
          JSON.stringify({
            status: await control.locator('#agent-record-status').textContent(),
            uploads,
            httpCodes: requests.map((x) => x[2]),
          }),
        );
      });
    assert.deepEqual(uploads, ['0', '1']);
    assert.ok(sourceBytes > 100 * 1024 * 1024);
    console.log(
      JSON.stringify({
        sourceBytes,
        projected,
        wireBytes,
        uploads,
        heapPeak: peak,
        ...(stopMemory ? await stopMemory() : {}),
        excludedRequests: 1,
        requests: 3,
        actions: 1,
      }),
    );
  }
  await control.locator('#agent-question').fill('检查合成保存操作');
  await control.locator('#agent-send').click();
  for (let i = 0; i < 100 && !lostMessageReceipt; i++) await delay(100);
  assert.ok(lostMessageReceipt, '测试代理须在服务端受理后丢弃回执');
  const marker = await control.evaluate(async (origin) => {
    const items = await chrome.storage.local.get(null);
    const chat = Object.entries(items).find(
      ([key]) => key.startsWith('["agent-chat",') && key.includes(origin),
    )?.[1];
    return {
      awaiting: chat?.awaiting?.length,
      fields: Object.keys(chat?.awaiting?.[0] ?? {}).sort(),
      jobs: chat?.jobs?.length,
    };
  }, origin);
  assert.deepEqual(marker, {
    awaiting: 1,
    fields: withRecording
      ? ['conversation', 'key', 'recording', 'scope']
      : ['conversation', 'key', 'scope'],
    jobs: 0,
  });
  await control.close();
  expireReceipt = async () => {
    fixture.stdin.write('expire\n');
    assert.equal((await next()).expired, true);
  };
  control = await context.newPage();
  await control.goto('chrome-extension://' + id + '/control.html#assistant');
  let body = control.locator('.agent-markdown');
  await body.waitFor({ state: 'attached' });
  await control.getByText('排队中', { exact: true }).waitFor();
  assert.equal(await control.getByRole('button', {name: '复制回复'}).count(), 0);
  async function advance() {
    fixture.stdin.write('advance\n');
    return next();
  }
  if (withRecording) {
    fixture.stdin.write('attempt-fails\n');
    assert.equal((await next()).failed_attempt, 0);
    await body.getByText('上一轮的合成草稿').waitFor();
  }
  await advance();
  await control.waitForFunction(() =>
    document.querySelector('.agent-markdown')?.textContent?.includes('**缺'),
  );
  assert.ok(!(await body.textContent()).includes('上一轮的合成草稿'));
  assert.ok(streamSocket);
  if (throughNginx) {
    for (let i = 0; i < 80 && !heartbeats; i++) await delay(200);
    assert.ok(heartbeats > 0, '代理没有及时转发空闲心跳');
  }
  unavailable = true;
  streamSocket.destroy();
  await control.getByText('连接中断，正在续读…').waitFor();
  fixture.stdin.write('expire\n');
  assert.equal((await next()).expired, true);
  await advance();
  unavailable = false;
  await body.locator('strong').filter({ hasText: '缺少批号' }).waitFor();
  assert.ok(cursors.length >= 2 && cursors.at(-1) > cursors[0]);
  // Determine the two snapshots in the same state, including when completion happens during login.
  const explicitLogin = process.env.EA_TEST_SIGNIN_RECOVERY === '1';
  if (explicitLogin) {
    const endSession = async () => {
      fixture.stdin.write('end-session\n');
      assert.equal((await next()).ended, true);
    };
    await endSession();
    streamSocket.destroy();
    await control.getByText('请重新登录以继续', { exact: true }).waitFor();
    assert.equal(await body.innerHTML(), '');
    if (!(await control.locator('#agent-login').isVisible())) await control.locator('#agent-connection summary').click();
    await control.locator('#agent-login').click();
    await signIn('demo-second');
    await control.getByText('已连接', { exact: true }).waitFor();
    await control.waitForFunction(
      () => !document.querySelector('#agent-send').disabled,
    );
    assert.equal(await control.locator('#agent-answers article').count(), 0);
    await endSession();
    if (!(await control.locator('#agent-login').isVisible())) await control.locator('#agent-connection summary').click();
    await control.locator('#agent-login').click();
    assert.equal((await advance()).jobs, 1);
    assert.equal((await advance()).jobs, 1);
    await signIn(config.username);
    body = control.locator('.agent-markdown');
    await control.getByText('已完成', { exact: true }).waitFor();
  } else {
    await control.close();
    assert.equal((await advance()).jobs, 1);
    control = await context.newPage();
    await control.goto('chrome-extension://' + id + '/control.html#assistant');
    body = control.locator('.agent-markdown');
    await body.locator('pre code.language-json').waitFor();
  }
  const before = await body.innerHTML();
  assert.equal((await body.textContent()).split('我查一下。').length, 2);
  assert.equal(await body.locator('table tbody tr').count(), 1);
  if (!explicitLogin) assert.equal((await advance()).jobs, 1);
  await control.getByText('已完成', { exact: true }).waitFor();
  assert.equal(await body.innerHTML(), before);
  assert.equal(await control.locator('#agent-answers article').count(), 1);
  await checkReply(control, control);
  assert.deepEqual(
    requests
      .filter(
        ([method, path]) => method === 'POST' && path.endsWith('/messages'),
      )
      .map(([, , code]) => code),
    [202],
  );
  assert.ok(
    requests.some(
      ([method, path, code]) =>
        method === 'GET' && path.includes('/messages/') && code === 200,
    ),
  );
  assert.deepEqual(requests.filter(([method, path]) => method === 'GET' && path.includes('/messages/')).map(([, , code]) => code), [401, 200]);
  const reads = cursors.length;
  await control.reload();
  await control.getByText('已完成', { exact: true }).waitFor();
  assert.equal(await control.locator('.agent-markdown').innerHTML(), before);
  assert.equal(cursors.length, reads);
  assert.ok(
    requests.some(
      ([method, path, code]) =>
        method === 'GET' && path.endsWith('/events') && code === 401,
    ),
  );
  console.log(
    JSON.stringify({
      recoveredLostFirstReceipt: true,
      resumed: true,
      cursors,
      credentialRenewed: true,
      reopened: true,
      completedDuringLogin: explicitLogin,
      accountSwitchChecked: explicitLogin,
      closedWhileRunning: !explicitLogin,
      nginx: throughNginx,
      heartbeats,
      duplicateText: false,
      finalMarkdownMatches: true,
      jobs: 1,
    }),
  );
  if (historyMode) {
    await control.locator('a[href="#conversations"]').click();
    const sessions = control.locator('#conversation-list button');
    await sessions.first().waitFor();
    const first = await sessions.first().getAttribute('data-session');
    await control.locator('#conversation-new').click();
    await control.getByRole('heading', {name:'新会话'}).waitFor();
    const draft = control.locator('#agent-question');
    await draft.fill('草稿');
    await draft.press('Shift+Enter');
    assert.equal(await draft.inputValue(), '草稿\n');
    await draft.fill('合成记录核对');
    await draft.press('Enter');
    await sessions.filter({hasText:'合成记录核对'}).waitFor();
    const second = await sessions.filter({hasText:'合成记录核对'}).getAttribute('data-session');
    assert.notEqual(second, first);
    fixture.stdin.write('history-tool\n'); assert.equal((await next()).conversation, second);
    const processBox = control.locator('.job-activity details').filter({has:control.locator('summary', {hasText:'执行过程'})});
    const tools = control.locator('.job-activity details').filter({has:control.locator('summary', {hasText:'工具调用'})});
    await tools.locator('summary').waitFor();
    assert.equal(await tools.evaluate(el => el.open), false);
    assert.equal(await processBox.evaluate(el => el.open), false);
    await tools.locator('summary').click();
    await tools.getByText('lookup_record', {exact:true}).waitFor();
    await tools.getByText('返回 2 条', {exact:true}).waitFor();
    await processBox.locator('summary').click();
    await processBox.getByText('正在核对合成记录。', {exact:true}).waitFor();
    fixture.stdin.write('history-final\n'); await next();
    await control.locator('.agent-markdown').getByText('两条记录已核对。').waitFor();
    assert.equal(await control.locator('.agent-markdown').textContent().then(s => s.trim()), '两条记录已核对。');
    if (process.env.EA_CHAT_PREVIEW_DIR) {
      await control.locator('#agent-question').focus();
      await control.screenshot({path:join(process.env.EA_CHAT_PREVIEW_DIR, 'agent-chatgpt-history.png')});
    }
    await sessions.filter({hasText:'检查合成保存操作'}).click();
    await control.getByRole('button', {name:'跳到提问：检查合成保存操作', exact:true}).focus();
    await control.locator('.turn-preview:visible').getByText('检查合成保存操作', {exact:true}).waitFor();
    await control.locator('#conversation-rail button').first().click();
    await draft.fill('继续在原会话追问');
    await control.locator('#agent-send').click();
    await control.locator('.chat-question').filter({hasText:'继续在原会话追问'}).waitFor();
    assert.equal(await sessions.count(), 2);
    assert.equal(await control.locator('#conversation-rail button').count(), 2);
    assert.equal(await control.locator('#conversation-list [aria-current="true"]').getAttribute('data-session'), first);
    await sessions.filter({hasText:'合成记录核对'}).click();
    await control.waitForFunction(id => document.querySelector('#conversation-list [aria-current="true"]')?.getAttribute('data-session') === id, second);
    await tools.locator('summary').waitFor();
    assert.equal(await tools.evaluate(el => el.open), false);
    for (let i = 1; i <= 21; i++) {
      const question = '跨页合成提问 ' + i;
      await draft.fill(question);
      await control.locator('#agent-send').click();
      await control.locator('.chat-question').filter({hasText:new RegExp('^' + question + '$')}).waitFor();
      fixture.stdin.write('history-final\n'); await next();
    }
    await sessions.filter({hasText:'检查合成保存操作'}).click();
    await control.getByRole('button', {name:'跳到提问：继续在原会话追问', exact:true}).waitFor();
    await sessions.filter({hasText:'合成记录核对'}).click();
    const early = control.getByRole('button', {name:'跳到提问：合成记录核对', exact:true});
    await early.waitFor();
    assert.equal(await control.locator('#conversation-rail button').count(), 22);
    await early.click();
    await control.locator('.chat-question').filter({hasText:'合成记录核对'}).waitFor();
    if (process.env.EA_HISTORY_SCREENSHOT) {
      const firstTurn = control.locator('#agent-answers article').filter({has:control.getByText('合成记录核对',{exact:true})});
      await firstTurn.getByText('工具调用 · 1',{exact:true}).click();
      await control.locator('#conversations').scrollIntoViewIfNeeded();
      await early.focus();
      await control.locator('#turn-preview-popup:visible').waitFor();
      await control.locator('#conversations').screenshot({path:process.env.EA_HISTORY_SCREENSHOT});
    }
    await control.getByRole('button', {name:'跳到提问：跨页合成提问 11', exact:true}).click();
    await control.locator('.chat-question').filter({hasText:'跨页合成提问 11'}).waitFor();
    const appChoice = control.locator('#conversation-app');
    await appChoice.selectOption({label:'合成巡检'});
    await control.getByText('还没有对话', {exact:true}).waitFor();
    assert.equal(await sessions.count(), 0);
    assert.equal(await control.locator('#conversation-rail button, #agent-answers article').count(), 0);
    const otherApp = await appChoice.inputValue();
    await draft.fill('巡检应用第一轮');
    await control.locator('#agent-send').click();
    await sessions.filter({hasText:'巡检应用第一轮'}).waitFor();
    assert.ok(requests.some(([method, path, status]) => method === 'POST'
      && path.endsWith('/applications/' + otherApp + '/messages') && status === 202));
    fixture.stdin.write('history-final\n'); await next();
    await appChoice.selectOption({label:'合成诊断'});
    await sessions.filter({hasText:'合成记录核对'}).waitFor();
    await control.getByRole('button', {name:'跳到提问：跨页合成提问 21', exact:true}).waitFor();
    assert.equal(await sessions.count(), 2);
    assert.equal(await sessions.filter({hasText:'巡检应用第一轮'}).count(), 0);
    await appChoice.selectOption({label:'合成巡检'});
    await control.locator('.chat-question').filter({hasText:'巡检应用第一轮'}).waitFor();
    assert.equal(await sessions.count(), 1);
    console.log(JSON.stringify({historySwitch:true, followup:true, turnNavigation:true, crossPageTurns:22, activity:true, finalOnly:true, applicationSwitch:true}));
  }
  if (withRecording) {
    const initialRequests = requests.filter(
      ([method, path]) => method === 'POST' && path.endsWith('/recordings'),
    ).length;
    const initialBytes = wireBytes;
    const questions = ['上一条保存请求的业务码是什么？', '用一句话总结。'];
    for (let n = 2; n <= 3; n++) {
      await control.locator('#agent-question').fill(questions[n - 2]);
      await control.locator('#agent-send').click();
      await control.getByText('排队中', { exact: true }).waitFor();
      assert.equal(await control.locator('#agent-answers article').last().getByRole('button', {name: '复制回复'}).count(), 0);
      fixture.stdin.write('follow-' + n + '\n');
      const result = await next();
      assert.deepEqual(result, { jobs: n, indexed: 4, published: 1 });
      await control.waitForFunction(
        (count) =>
          Array.from(
            document.querySelectorAll('#agent-answers article small'),
          ).filter((el) => el.textContent === '已完成').length === count,
        n,
      );
    }
    assert.equal(wireBytes, initialBytes);
    assert.equal(
      requests.filter(
        ([method, path]) => method === 'POST' && path.endsWith('/recordings'),
      ).length,
      initialRequests,
    );
    assert.deepEqual(uploads, ['0', '1']);
    fixture.stdin.write('expire-recording\n');
    assert.deepEqual(await next(), { indexed: 0, stored_parts: 0 });
    await control.reload();
    await control.getByRole('button', {name:'录制已失效'}).click();
    await control.getByText(/已不可查询/).waitFor();
    assert.equal(wireBytes, initialBytes);
    console.log(
      JSON.stringify({
        expiredRecordingCleaned: true,
        profile,
        turns: 3,
        published: 1,
        indexed: 4,
        followupUploadBytes: wireBytes - initialBytes,
        summaryUsedHistory: true,
      }),
    );
    if (process.env.EA_TEST_CAPTURE === '1') {
      await captureSave(control, context, origin);
      await control
        .locator('#agent-question')
        .fill('核对刚刚保存时失败的请求及附近的操作');
      await control.locator('#agent-send').click();
      await control.getByText('排队中', { exact: true }).waitFor();
      assert.equal(await control.locator('#agent-answers article').last().getByRole('button', {name: '复制回复'}).count(), 0);
      fixture.stdin.write('captured-save\n');
      assert.deepEqual(await next(), { jobs: 4, saved: true });
      await control
        .locator('.agent-markdown')
        .getByText('SYNTHETIC_LOT_MISSING', { exact: true })
        .waitFor();
      console.log(JSON.stringify({ capturedSaveFound: true }));
    }
  } else {
    const redirected = new URL(origin);
    redirected.hostname = hostname === 'localhost' ? '127.0.0.1' : 'localhost';
    redirected.pathname = '/synthetic-redirect-target';
    let sent = false,
      redirectedRequest = false;
    await context.route(redirected.href, (route) => {
      redirectedRequest = true;
      return route.fulfill({ json: [] });
    });
    await control.route(
      origin + '/api/browser-extension/applications',
      (route) => {
        sent = true;
        return route.fulfill({
          status: 302,
          headers: { location: redirected.href },
        });
      },
    );
    await control.reload();
    await control.waitForFunction(
      () =>
        !document.querySelector('#agent-login').disabled &&
        document.querySelector('#agent-status').textContent.length > 0,
    );
    assert.ok(sent && !redirectedRequest);
    assert.equal(await control.locator('#agent-app option').count(), 0);
    console.log(JSON.stringify({ crossOriginRedirectRejected: true }));
  }
}
