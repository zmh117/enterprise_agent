import assert from 'node:assert/strict';
import test, { type TestContext } from 'node:test';
import { Platform } from '../extension/ui/agent-panel';
import { PlatformError } from '../extension/ui/agent-answer';

const origin = 'https://agent.invalid:8443';
const id = 'a'.repeat(32);
const callback = 'https://' + id + '.chromiumapp.org/';
const ok = () => Response.json({});
const rejected = (status: number, code: string) =>
  Response.json({ code }, { status });

function fixture(t: TestContext) {
  // Node 22 has no LockManager. Cross-page exclusion is exercised in the Chrome suite.
  const previousLocks = Object.getOwnPropertyDescriptor(navigator, 'locks');
  Object.defineProperty(navigator, 'locks', {configurable: true, value: {
    request: (_name: string, {signal}: {signal: AbortSignal}, run: () => unknown) => {
      signal.throwIfAborted();
      return run();
    },
  }});
  t.after(() => previousLocks ? Object.defineProperty(navigator, 'locks', previousLocks) : Reflect.deleteProperty(navigator, 'locks'));
  let now = 1_000_000;
  let owner = 'alice',
    lifetime = 30,
    consent = '',
    returned = '',
    wrongState = false;
  let opens = 0,
    tokens = 0;
  const requests: string[] = [];
  let onExchange: (() => Promise<void>) | undefined;
  const oldChrome = Object.getOwnPropertyDescriptor(globalThis, 'chrome');
  Object.defineProperty(globalThis, 'chrome', {
    configurable: true,
    value: {
      runtime: { id },
      tabs: {
        onCreated: { addListener() {}, removeListener() {} },
        onUpdated: { addListener() {}, removeListener() {} },
      },
      identity: {
        getRedirectURL: () => callback,
        launchWebAuthFlow: async ({
          url,
          interactive,
        }: {
          url: string;
          interactive: boolean;
        }) => {
          opens++;
          const flow = new URL(url);
          assert.equal(flow.origin, origin);
          if (interactive) assert.ok([null, 'select_account'].includes(flow.searchParams.get('prompt')));
          else assert.equal(flow.searchParams.get('prompt'), 'none');
          const dest = new URL(returned || callback);
          dest.searchParams.set('state', wrongState ? 'wrong-state' : flow.searchParams.get('state')!);
          dest.searchParams.set(
            consent ? 'error' : 'code',
            consent || 'synthetic-code',
          );
          return dest.href;
        },
      },
    },
  });
  t.after(() =>
    oldChrome
      ? Object.defineProperty(globalThis, 'chrome', oldChrome)
      : Reflect.deleteProperty(globalThis, 'chrome'),
  );
  t.mock.method(Date, 'now', () => now);
  let send: (path: string, token: string, options: RequestInit) => Promise<Response> = async () =>
    ok();
  t.mock.method(
    globalThis,
    'fetch',
    async (url: string, options: RequestInit) => {
      assert.ok(url.startsWith(origin + '/api/browser-extension/'));
      assert.equal(options.redirect, 'error');
      if (url.endsWith('/auth/token')) {
        tokens++;
        const credentials = {
          user_id: owner,
          tenant_id: origin,
          access_token: 'synthetic-' + tokens,
          expires_in: lifetime,
        };
        await onExchange?.();
        return Response.json(credentials);
      }
      const token = new Headers(options.headers).get('Authorization')!;
      requests.push(token);
      return send(url, token, options);
    },
  );
  return {
    client: new Platform(origin),
    delayExchange: (wait: () => Promise<void>) => { onExchange = wait; },
    requests,
    get opens() {
      return opens;
    },
    get tokens() {
      return tokens;
    },
    advance: (ms: number) => {
      now += ms;
    },
    ttl: (seconds: number) => {
      lifetime = seconds;
    },
    switchTo: (user: string) => {
      owner = user;
    },
    error: (value: string) => {
      consent = value;
    },
    redirect: (value: string) => {
      returned = value;
    },
    invalidState: (value: boolean) => { wrongState = value; },
    respond: (fn: typeof send) => {
      send = fn;
    },
  };
}

test('旧平台复用原账号时拒绝将普通授权回执当作换号成功', async t => {
  const f = fixture(t);
  await assert.rejects(f.client.login('select_account'), /当前平台版本不支持切换插件账号/);
  assert.equal(f.tokens, 0);
});

test('活动期间合并换证，父会话临期时保持同一凭据到实际过期', async (t) => {
  const f = fixture(t);
  await f.client.login(true);
  f.advance(26_000);
  assert.equal(f.opens, 1);
  f.ttl(4);
  await Promise.all([
    f.client.request('/one', {}),
    f.client.request('/two', {}),
  ]);
  await f.client.request('/three', {});
  assert.equal(f.opens, 2);
  assert.deepEqual(new Set(f.requests), new Set(['Bearer synthetic-2']));
  f.advance(60_000);
  assert.equal(f.opens, 2);
  f.ttl(30);
  await f.client.request('/resume', {});
  assert.equal(f.tokens, 3);
});

test('旧请求迟到的 401 复用新凭据，撤权不会触发再登录', async (t) => {
  const f = fixture(t);
  await f.client.login(true);
  let arrived!: () => void, release!: () => void;
  const pending = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  f.respond(async (path, token) => {
    if (path.endsWith('/late') && token === 'Bearer synthetic-1') {
      arrived();
      await blocked;
      return rejected(401, 'credential_expired');
    }
    return token === 'Bearer synthetic-1'
      ? rejected(401, 'credential_expired')
      : ok();
  });
  const late = f.client.request('/late', {});
  await pending;
  await f.client.request('/now', {});
  release();
  await late;
  assert.equal(f.tokens, 2);
  f.respond(async () => rejected(403, 'access_denied'));
  await assert.rejects(f.client.request('/denied', {}), {
    code: 'access_denied',
  });
  assert.equal(f.opens, 2);
});

test('重新登录、重新同意、跨 Origin 回调和换号均先停止原请求', async (t) => {
  const f = fixture(t);
  await f.client.login(true);
  f.advance(60_000);
  for (const code of ['login_required', 'consent_required']) {
    f.error(code);
    await assert.rejects(
      f.client.request('/old', {}),
      (e: unknown) => e instanceof PlatformError && e.code === code,
    );
  }
  f.error('access_denied');
  await assert.rejects(f.client.request('/old', {}), { status: 403, code: 'access_denied' });
  f.error('');
  f.invalidState(true);
  await assert.rejects(f.client.request('/old', {}), /回调/);
  f.invalidState(false);
  f.redirect('https://elsewhere.invalid/');
  await assert.rejects(f.client.request('/old', {}), /回调/);
  assert.equal(f.tokens, 1);
  f.redirect('');
  f.switchTo('bob');
  await assert.rejects(f.client.request('/old', {}), {
    code: 'account_changed',
  });
  assert.ok(f.client.signal.aborted);
  assert.equal(f.requests.length, 0);
});

test('重新选择账号后迟到的旧兑换不能恢复旧请求', async (t) => {
  const f = fixture(t);
  let entered!: () => void, resume!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const blocked = new Promise<void>((resolve) => {
    resume = resolve;
  });
  f.delayExchange(async () => {
    entered();
    await blocked;
  });
  const old = f.client.request('/pending', {});
  await started;
  f.client.controller.abort();
  f.switchTo('bob');
  f.delayExchange(async () => {});
  const current = new Platform(origin);
  await current.login(true);
  await current.request('/current', {});
  resume();
  await assert.rejects(old, { name: 'AbortError' });
  assert.deepEqual(f.requests, ['Bearer synthetic-2']);
});

test('消息、分片和 SSE 跨过期点后按原账号、原消息和原游标恢复', async (t) => {
  const cases = [
    {
      path: '/applications/app/messages',
      options: { method: 'POST', body: '{"client_message_id":"stable"}' },
    },
    {
      path: '/recordings/r/parts/1',
      options: { method: 'PUT', body: 'synthetic' },
    },
    {
      path: '/jobs/job/events',
      options: { headers: { 'Last-Event-ID': '17' } },
    },
  ];
  for (const { path, options } of cases) {
    for (const mode of ['silent', 'login_required', 'switch', 'denied']) {
      await t.test(path + ' ' + mode, async (sub) => {
        const f = fixture(sub);
        await f.client.login(true);
        let attempts = 0;
        f.respond(async (url, token, actual) => {
          const resumingUpload =
            path.startsWith('/recordings/') && token !== 'Bearer synthetic-1';
          const expected = resumingUpload
            ? '/applications/app/recordings'
            : path;
          assert.equal(
            new URL(url).pathname,
            '/api/browser-extension' + expected,
          );
          if (!resumingUpload) {
            assert.equal(actual.body, options.body);
            assert.equal(
              new Headers(actual.headers).get('Last-Event-ID'),
              new Headers(options.headers).get('Last-Event-ID'),
            );
          }
          attempts++;
          if (mode === 'denied') return rejected(403, 'access_denied');
          if (token === 'Bearer synthetic-1') {
            if (mode === 'switch') f.switchTo('bob');
            if (mode === 'login_required') f.error(mode);
            return rejected(401, 'credential_expired');
          }
          return ok();
        });
        const run = () => f.client.request(path, options as RequestInit);
        if (mode === 'denied' || mode === 'switch') {
          await assert.rejects(run(), {
            code: mode === 'denied' ? 'access_denied' : 'account_changed',
          });
          assert.equal(attempts, 1);
          return;
        }
        if (mode === 'login_required') {
          await assert.rejects(run(), { code: 'login_required' });
          assert.equal(attempts, 1);
          f.error('');
          await f.client.login(true);
          assert.equal(
            (
              await f.client.request(
                path.startsWith('/recordings/')
                  ? '/applications/app/recordings'
                  : path,
                path.startsWith('/recordings/')
                  ? { method: 'POST' }
                  : (options as RequestInit),
              )
            ).status,
            200,
          );
        } else if (path.startsWith('/recordings/')) {
          await assert.rejects(run(), { code: 'resume_upload' });
          assert.equal(attempts, 1);
        } else {
          assert.equal((await run()).status, 200);
          assert.equal(attempts, 2);
        }
      });
    }
  }
});
