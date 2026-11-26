import assert from 'node:assert/strict';

async function retained(page) {
  return page.evaluate(async () => {
    const read = (request) =>
      new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    const db = await read(indexedDB.open('mes-workshop-live-v1', 1));
    try {
      const tx = db.transaction(['liveEvidence', 'liveParts']);
      const [events, parts] = await Promise.all(
        ['liveEvidence', 'liveParts'].map((name) => read(tx.objectStore(name).getAll())),
      );
      const results = [];
      for (const row of events) {
        const chunks = parts.filter((p) => p.id === row.id).sort((a, b) => a.number - b.number);
        const bytes = new Uint8Array(row.length);
        let offset = 0;
        for (const chunk of chunks) {
          bytes.set(chunk.data, offset);
          offset += chunk.data.byteLength;
        }
        const digest = Array.from(
          new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
          (v) => v.toString(16).padStart(2, '0'),
        ).join('');
        if (offset !== row.length || digest !== row.digest) throw new Error('待传原文摘要发生变化');
        results.push([row.recordingId, row.id, row.source, digest, row.delivery]);
      }
      return results;
    } finally {
      db.close();
    }
  });
}

export async function checkRollback({ control, restart }) {
  const before = await retained(control);
  const oldCount = await control.evaluate(
    async () => (await chrome.runtime.sendMessage({ type: 'history.list' })).recordings.length,
  );
  assert.ok(oldCount > 0, '回退前必须存在封存的离线录制');
  assert.ok(
    before.some((r) => r[4] === 'pending'),
    '停用写入时应保留待传材料',
  );
  const old = await restart(true);
  const restoredCount = await old.evaluate(
    async () => (await chrome.runtime.sendMessage({ type: 'history.list' })).recordings.length,
  );
  assert.equal(restoredCount, oldCount);
  await old.locator('.history-row').first().waitFor();
  assert.equal(await old.locator('#record-mode').count(), 0);
  await old.locator('#history-search').fill('capture-fixture');
  await old.locator('.history-row').first().waitFor();
  const restored = await restart(false);
  await restored.locator('.history-row').first().waitFor();
  assert.equal(await restored.locator('#record-mode').count(), 1);
  assert.deepEqual(await retained(restored), before);
  console.log(
    JSON.stringify({
      rollback: true,
      offlineRecordingVisible: true,
      restoredEvents: before.length,
    }),
  );
}
