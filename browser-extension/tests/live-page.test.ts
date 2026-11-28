import test from 'node:test';
import assert from 'node:assert/strict';
import { observePage, sourceOf, projectPageEvent } from '../shared/live-page';
import { ruleForPage } from '../shared/workshop';

test('跨车间后同一文档保持暂停直到新文档，未绑定页和同 URL 标签相互独立', () => {
  const urls = [
    'https://example.invalid/A',
    'https://example.invalid/B',
    'https://example.invalid/C',
  ];
  const rules = urls.map((url, i) => ({
    id: String(i),
    revision: 1,
    enabled: true,
    environment_id: 'e',
    base_id: 'b',
    workshop_id: String(i),
    rule: ruleForPage(url),
  }));
  const a = observePage(undefined, 'doc-A', urls[0]!, rules);
  const b = observePage(undefined, 'doc-B', urls[1]!, rules);
  const c = observePage(undefined, 'doc-C', urls[2]!, rules);
  const copy = observePage(undefined, 'doc-copy', urls[2]!, rules);
  const paused = observePage(a, 'doc-A', urls[1]!, rules);
  assert.equal(observePage(paused, 'doc-A', urls[0]!, rules).state, 'paused');
  assert.equal(sourceOf('A', paused), undefined);
  assert.equal(observePage(paused, 'new-A', urls[1]!, rules).state, 'baseline');
  assert.equal(sourceOf('B', b)?.binding_id, '1');
  assert.notDeepEqual(sourceOf('C', c), sourceOf('copy', copy));
  assert.equal(
    observePage(
      c,
      'doc-C',
      urls[2]!,
      rules.map((r) => ({ ...r, revision: 2 })),
    ).state,
    'paused',
  );
  assert.equal(
    sourceOf('D', observePage(undefined, 'doc-D', 'https://example.invalid/none', rules)),
    undefined,
  );
});

test('旧录制缺少页面文字策略时只保留结构', () => {
  const marker = 'synthetic-private-fixture';
  const event = projectPageEvent({
    kind: 'baseline',
    raw: marker,
    node: {
      id: 1,
      type: 0,
      attributes: { cookie: marker },
      childNodes: [
        {
          id: 2,
          type: 2,
          tagName: marker,
          attributes: { src: marker, style: marker, value: marker },
          childNodes: [{ type: 3, id: 3, textContent: marker }],
        },
      ],
    },
  });
  assert.ok(!JSON.stringify(event).includes(marker));
  assert.deepEqual(
    projectPageEvent({
      kind: 'action',
      action: 'click',
      element: marker,
      node_id: 3,
      text: marker,
    }),
    { kind: 'action', action: 'click', element: 'div', node_id: 3 },
  );
  assert.throws(() =>
    projectPageEvent({ kind: 'baseline', node: { id: 1, type: 0, childNodes: [{ type: 99 }] } }),
  );
});

import { liveBody } from '../shared/live-body';
import { DEFAULT_POLICY, parsePolicy } from '../shared/policy';

test('持续模式保留完整 JSON 业务明细，单正文预算可达 32 MiB，离线策略保留原档位', () => {
  const max = 32 * 1024 * 1024;
  const policy = structuredClone(DEFAULT_POLICY);
  policy.pageOrigins = ['https://example.invalid'];
  policy.budgets.bodyBytes = max;
  policy.budgets.queueBytes = max;
  assert.equal(parsePolicy(policy, 'continuous').budgets.bodyBytes, max);
  assert.throws(() => parsePolicy(policy));
  const fixture = {
    workOrder: 'WO-SYNTHETIC',
    lot: '批次1',
    rows: [{ qty: 3 }],
    authorization: 'synthetic-private-fixture',
  };
  const result = liveBody(JSON.stringify(fixture), 'application/json', max);
  assert.equal(result.status, 'captured');
  assert.equal(
    JSON.stringify(result.value),
    JSON.stringify({ workOrder: fixture.workOrder, lot: '批次1', rows: [{ qty: 3 }] }),
  );
  for (const size of [4 * 1024 * 1024, 4 * 1024 * 1024 + 1, max, max + 1]) {
    const json = '{"note":"' + 'a'.repeat(size - 11) + '"}';
    assert.equal(json.length, size);
    const body = liveBody(json, 'application/json', max);
    assert.equal(body.status, size > max ? 'over_limit' : 'captured');
  }
  const precise = liveBody(
    '{"order":1234567890123456789,"qty":0.1234567890123456789,"token":"synthetic"}',
    'application/json',
    max,
  );
  assert.equal(precise.status, 'captured');
  assert.equal(
    JSON.stringify(precise.value),
    '{"order":1234567890123456789,"qty":0.1234567890123456789}',
  );
});


test('后台只接收定义的页面字段，重新执行标题、行、输入和选择策略', () => {
  const policy = {...DEFAULT_POLICY, allowedInputNames:['qty']};
  const sample = {
    kind:'action', page_format:'visible_page_v1', page_title:'合成录制', page_coverage:'rendered_dom',
    action:'change', element:'input', node_id:3, field_name:'qty', field_label:'数量', target_text:'数量',
    row_text:'WO-C', before_value:'8', value:'12', selection:'甲', arbitrary:'must-not-cross',
  };
  assert.throws(() => projectPageEvent(sample));
  const visible = projectPageEvent(sample, policy);
  assert.ok(visible.kind === 'action' && 'value' in visible && visible.value === '12');
  assert.ok(!('arbitrary' in visible));
  for (const name of ['other', 'current-password', 'otp']) {
    const protectedEvent = projectPageEvent({...sample,field_name:name}, policy);
    assert.ok(protectedEvent.kind === 'action' && 'value' in protectedEvent);
    for (const k of ['value','before_value','selection'] as const)
      assert.equal(protectedEvent[k], '[REDACTED]');
  }
  const masked = JSON.stringify(projectPageEvent(sample, {...policy,maskAllText:true}));
  for (const marker of ['WO-C', '数量', '合成录制', '"12"']) assert.ok(!masked.includes(marker));
  const baseline = projectPageEvent({...sample,kind:'baseline', removed:[], nodes:[
    {id:1,parent:0,order:0,element:'text',text:'字'.repeat(2000),raw:'must-not-cross'},
    {id:2,parent:1,order:0,element:'input',field_name:'otp',value:'must-not-cross'},
    {id:3,parent:1,order:1,element:'text',text:'Bearer synthetic-private'},
  ]}, policy);
  assert.ok('nodes' in baseline && baseline.nodes[0]?.text?.endsWith('…'));
  assert.ok(!JSON.stringify(baseline).includes('must-not-cross'));
  assert.ok(!JSON.stringify(baseline).includes('synthetic-private'));
});
