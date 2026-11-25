import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { assertSchema } from '../shared/validation';
import { recording } from './helpers';
import { newTarget } from '../extension/background/session/gate';
import { SCHEMA_VERSION, PACKAGE_VERSION } from '../shared/contracts';

test('发布 schema 与静态校验函数拒绝错误必填、字段类型、枚举和旧契约版本', async () => {
  const schema = JSON.parse(await readFile('shared/problem-package.schema.json','utf8'));
  assert.equal(schema.properties.schemaVersion.enum.at(-1),PACKAGE_VERSION);
  assert.equal(schema.$defs.recording.properties.schemaVersion.const,SCHEMA_VERSION);
  const r=recording(); assertSchema('recording',r);
  assert.throws(()=>assertSchema('recording',{...r,eventsPersisted:'1'}),/schema/);
  assert.throws(()=>assertSchema('recording',{...r,state:'DONE'}),/schema/);
  assert.throws(()=>assertSchema('recording',{...r,schemaVersion:'1.0.0'}),/schema/);
  const t=newTarget(r,{id:1,windowId:1},1,'start','root'); assertSchema('target',t);
  assert.throws(()=>assertSchema('target',{...t,documents:{}}),/schema/);
  assert.throws(()=>assertSchema('target',{...t,channels:{network:t.channels.network}}),/schema/);
  assertSchema('pagePacket',{seq:1,kind:'ui.observation',sourceTime:1,payload:{action:'input'}});
  for(const packet of [{seq:1,kind:'unknown',sourceTime:1,payload:{}},{seq:1,kind:'ui.observation',sourceTime:1,payload:[]},{seq:1,kind:'ui.observation',payload:{}}]) assert.throws(()=>assertSchema('pagePacket',packet),/schema/);
});

test('静态校验产物不在运行期动态编译，不依赖 eval 或 Function', async () => {
  const generated=await readFile('shared/generated/schema.js','utf8');
  assert.ok(!/\beval\s*\(|new\s+Function\s*\(/.test(generated));
  assert.ok(!/(?:from\s+["']ajv|=\s*require\(["']ajv)/.test(generated));
});
