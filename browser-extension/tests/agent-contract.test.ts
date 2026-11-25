import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import Ajv2020 from 'ajv/dist/2020.js';

const root = new URL('../../contracts/browser-extension/v1/', import.meta.url);
const read = (path: string) => readFile(new URL(path, root), 'utf8');
const schema = JSON.parse(await read('protocol.schema.json'));
const ajv = new Ajv2020({ strict: false });
ajv.addSchema(schema);
function check(name: string, value: unknown) {
  const valid = ajv.getSchema(schema.$id + '#/$defs/' + name);
  assert.ok(valid);
  assert.ok(valid(value), JSON.stringify(valid.errors));
}
const digest = (s: string) => createHash('sha256').update(s).digest('hex');

test('平台 v1 合成回执、绑定三态、错误分类及五种 SSE 事件', async () => {
  const events = new Set<string>(),
    errors = new Set<string>(),
    bindings = new Set<string>();
  for (const { contract, body } of JSON.parse(
    await read('golden/conversation.json'),
  )) {
    check(contract, body);
    if (contract === 'AnswerEvent') events.add(body.event);
    if (contract === 'Error') errors.add(body.code);
    if (contract === 'CreateMessage')
      bindings.add(
        !Object.hasOwn(body, 'recording_id')
          ? 'inherit'
          : body.recording_id === null
            ? 'clear'
            : 'bind',
      );
  }
  assert.deepEqual(bindings, new Set(['inherit', 'clear', 'bind']));
  assert.deepEqual(
    events,
    new Set(['answer_delta', 'reset', 'failed', 'status', 'completed']),
  );
  for (const code of [
    'credential_expired',
    'login_required',
    'consent_required',
    'access_denied',
    'parts_missing',
    'scope_changed',
    'upload_expired',
  ])
    assert.ok(errors.has(code));
});

test('两个封存版本的原始字节、源 ID 摘要及计数与平台清单一致', async () => {
  for (const version of ['a', 'b']) {
    const init = JSON.parse(await read('golden/init-' + version + '.json'));
    check('InitRecording', init);
    const raw = await read('golden/recording-' + version + '.ndjson');
    const part = init.manifest.parts[0];
    assert.equal(part.uncompressed_bytes, Buffer.byteLength(raw));
    assert.equal(part.sha256, digest(raw));
    const rows = raw
      .trimEnd()
      .split('\n')
      .map((line) => JSON.parse(line));
    for (const row of rows) check('EvidenceRow', row);
    for (const kind of ['action', 'request']) {
      const ids: string[] = rows
        .filter((row) => row.kind === kind)
        .map((row) => row.eventId ?? row.requestKey)
        .sort();
      const counts = init.manifest.coverage[kind + 's'];
      assert.equal(new Set(ids).size, counts.shareable);
      assert.equal(counts.saved, counts.shareable + counts.platform_excluded);
      assert.equal(
        digest(ids.map((id) => id + '\n').join('')),
        counts.ids_sha256,
      );
    }
  }
});

test('首见接口保留嵌套业务字段，受保护字段只保留省略位置', async () => {
  const row = JSON.parse(await read('golden/recording-b.ndjson'));
  assert.equal(row.path_template, null);
  assert.equal(row.request_details.value['新增业务字段'][0]['数量'], 3.5);
  assert.deepEqual(row.request_details.omissions, [{path: '/sessionToken', reason: 'protected'}]);
  check('EvidenceRow', row);
  const valid = ajv.getSchema(schema.$id + '#/$defs/EvidenceRow')!;
  assert.equal(valid({...row, request_fields: 'included'}), false);
  assert.equal(valid({...row, response_details: row.request_details}), false);
  const detail = {value: [{nested: {Cookie: 'synthetic-marker'}}], omissions: []};
  assert.equal(valid({...row, request_fields: 'included', request_details: detail}), false);
});
