import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const exec = promisify(execFile);

// Query only OS processes reported by this dedicated Chrome instance.
export async function sampleRecordingMemory(browser) {
  const session = await browser.newBrowserCDPSession();
  let samples = 0,
    extensionRssBytes = 0,
    chromeRssBytes = 0;
  let pending = Promise.resolve();
  const sample = async () => {
    const { processInfo } = await session.send('SystemInfo.getProcessInfo');
    const ids = processInfo.map((p) => p.id).filter((pid) => pid > 0);
    const { stdout } = await exec('ps', [
      '-ww',
      '-p',
      ids.join(','),
      '-o',
      'rss=,args=',
    ]);
    let extension = 0,
      total = 0;
    for (const line of stdout.trim().split('\n')) {
      const row = line.trim().match(/^(\d+)\s+(.+)$/);
      if (!row) continue;
      const bytes = Number(row[1]) * 1024;
      total += bytes;
      if (/(?:^|\s)--extension-process(?:\s|$)/.test(row[2]))
        extension += bytes;
    }
    extensionRssBytes = Math.max(extensionRssBytes, extension);
    chromeRssBytes = Math.max(chromeRssBytes, total);
    samples++;
  };
  try {
    await sample();
  } catch (error) {
    await session.detach();
    throw error;
  }
  let timer,
    stopped = false,
    failure;
  function schedule() {
    if (stopped) return;
    timer = setTimeout(() => {
      pending = sample().then(schedule, (error) => {
        failure = error;
      });
    }, 100);
  }
  schedule();
  return async () => {
    stopped = true;
    clearTimeout(timer);
    try {
      await pending;
      if (failure) throw failure;
      assert.ok(samples > 1 && extensionRssBytes > 0, '未采到扩展进程驻留内存');
      return { samples, extensionRssBytes, chromeRssBytes };
    } finally {
      await session.detach();
    }
  };
}


export async function seedLargeRecording(control, origin) {
  return control.evaluate(async (origin) => {
    const db = await new Promise((ok, no) => {
      const open = indexedDB.open('mes-evidence-v1', 1);
      open.onsuccess = () => ok(open.result);
      open.onerror = () => no(open.error);
    });
    let bytes = 0;
    const put = async (name, values) => {
      const tx = db.transaction(name, 'readwrite');
      for (const row of values) {
        bytes += new TextEncoder().encode(JSON.stringify(row)).length;
        tx.objectStore(name).put(row);
      }
      await new Promise((ok, no) => {
        tx.oncomplete = ok;
        tx.onerror = no;
      });
    };
    const t = '2026-11-19T10:00:00Z',
      rid = 'synthetic-upload-v2';
    await put('recordings', [
      {
        recordingId: rid,
        state: 'READY',
        title: '合成大录制',
        saveState: 'saved',
        startedAt: t,
        checkpoint: 110,
        gaps: [],
        policy: { businessRules: [] },
      },
    ]);
    const data = 'x'.repeat(1024 * 1024);
    for (let k = 0; k < 101; k++)
      await put('chunks', [
        {
          id: 'chunk-' + String(k).padStart(3, '0'),
          recordingId: rid,
          events: [{ kind: 'rrweb.event', payload: { data } }],
        },
      ]);
    await put('chunks', [
      {
        id: 'action',
        recordingId: rid,
        events: [
          {
            kind: 'ui.action',
            eventId: 'ui:1',
            observedAt: t,
            payload: {
              action: 'submit',
              context: {
                url: 'http://mes.test/save',
                business: { lot: 'demo' },
              },
            },
          },
        ],
      },
    ]);
    for (let n = 0; n < 4; n++) {
      const id = 'body-' + n,
        path = 'bodies/' + id + '.json',
        raw = JSON.stringify({
          sample: 'z'.repeat(350000),
          code: 'DEMO_REJECTED',
          units: 3,
        });
      await put('blobs', [
        {
          id,
          recordingId: rid,
          path,
          mime: 'application/json',
          data: raw,
          encoding: 'utf8',
        },
      ]);
      await put('network', [
        {
          requestKey: 'net:' + n,
          recordingId: rid,
          startedAt: t,
          networkOutcome: 'finished',
          businessOutcome: 'failure',
          businessCode: 'DEMO_REJECTED',
          actionCandidates: [{ actionId: 'ui:1', basis: 'time_proximity' }],
          request: {
            url:
              n === 3
                ? origin + '/api/browser-extension/auth/token'
                : 'http://mes.test/save',
            method: 'POST',
            bodyCaptureStatus: 'unavailable',
            headers: {},
          },
          response: {
            httpStatus: 200,
            headers: {},
            bodyCaptureStatus: 'captured',
            bodyRef: path,
            redactionStatus: 'none',
          },
        },
      ]);
    }
    db.close();
    return bytes;
  }, origin);
}

async function openRecordingDrawer(control) {
  const toggle = control.locator('#agent-evidence-toggle');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
}

export async function previewRecording(control) {
  await openRecordingDrawer(control);
  await control
    .locator('#agent-record-choice')
    .selectOption('synthetic-upload-v2');
  await control.locator('#agent-record-preview').click();
  await control
    .locator('#agent-record-share')
    .waitFor({ state: 'visible', timeout: 60000 });
  assert.match(
    await control.locator('#agent-record-status').textContent(),
    /请求 3\/4，操作 1\/1/,
  );
}

export async function captureSave(control, context, origin) {
  const page = await context.newPage();
  const entry = origin + '/synthetic-mes';
  const save = entry + '/save';
  await page.route(entry, (route) =>
    route.fulfill({
      contentType: 'text/html; charset=utf-8',
      body: '<button id="save">保存</button><output></output><script>document.querySelector("button").onclick=async()=>{const r=await fetch("/synthetic-mes/save",{method:"POST",body:JSON.stringify({units:3})}); document.querySelector("output").textContent=(await r.json()).code}</script>',
    }),
  );
  await page.route(save, (route) =>
    route.fulfill({ json: { code: 'SYNTHETIC_LOT_MISSING' } }),
  );
  await page.goto(entry);
  const tab = await control.evaluate(
    async (entry) =>
      (await chrome.tabs.query({})).find((t) => t.url === entry)?.id,
    entry,
  );
  assert.ok(Number.isInteger(tab));
  await control.locator('nav a[href="#capture"]').click();
  await control.locator('#refresh').click();
  await control.locator('input[data-tab-id="' + tab + '"]').check();
  await control.locator('#policy-details summary').click();
  const policy = JSON.parse(await control.locator('#policy').inputValue());
  policy.pageOrigins = [origin];
  policy.apiRules = [{ origin, pathPrefix: '/synthetic-mes/' }];
  policy.businessRules = [
    {
      origin,
      pathPrefix: '/synthetic-mes/save',
      codePath: 'code',
      successValues: ['OK'],
    },
  ];
  await control.locator('#policy').fill(JSON.stringify(policy));
  await control.locator('#start').click();
  await control.waitForFunction(async () =>
    (
      await chrome.runtime.sendMessage({ type: 'session.status' })
    ).targets?.some((t) => t.captureState === 'ACTIVE'),
  );
  await page.locator('#save').click();
  await page.getByText('SYNTHETIC_LOT_MISSING').waitFor();
  await control.waitForFunction(async () => {
    const s = await chrome.runtime.sendMessage({ type: 'session.status' });
    return s.recording?.eventsPersisted > 0;
  });
  const rid = await control.evaluate(
    async () =>
      (await chrome.runtime.sendMessage({ type: 'session.status' })).recording
        .recordingId,
  );
  await control.locator('#stop').click();
  await control.waitForFunction(
    async (rid) =>
      (
        await chrome.runtime.sendMessage({ type: 'history.list' })
      ).recordings?.some(
        (r) => r.recordingId === rid && r.saveState === 'saved' && r.stoppedAt,
      ),
    rid,
  );
  await page.close();
  await control.locator('nav a[href="#assistant"]').click();
  await openRecordingDrawer(control);
  await control.locator('#agent-record-choice').selectOption(rid);
  await control.locator('#agent-record-preview').click();
  await control.locator('#agent-record-share').waitFor({ state: 'visible' });
  await control.locator('#agent-record-share').click();
  await control.getByText(/可在本会话连续提问/).waitFor();
}
