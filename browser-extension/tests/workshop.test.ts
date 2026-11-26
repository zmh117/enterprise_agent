import test from 'node:test';
import assert from 'node:assert/strict';
import { bindingForPage, ruleForPage, type WorkshopBinding } from '../shared/workshop';

test('两个同域标签页只按选定的页面路径、hash 和业务定位键匹配', () => {
  const url = 'https://example.invalid/mes?volatile=ignored#/orders?plant=2';
  const rule = ruleForPage(url, ['plant']);
  const binding: WorkshopBinding = {
    id: 'first',
    revision: 1,
    enabled: true,
    environment_id: 'env',
    base_id: 'b',
    workshop_id: 'w',
    rule,
  };
  assert.deepEqual(Object.keys(rule.query), ['plant']);
  assert.equal(rule.query.plant, '2');
  assert.equal(bindingForPage(url, [binding]), binding);
  for (const changed of [
    '/other?',
    '/mes#/other?plant=2',
    '/mes#/orders?plant=3',
    '/mes?plant=2#/orders?plant=2',
  ]) {
    assert.equal(bindingForPage('https://example.invalid' + changed, [binding]), undefined);
  }
  assert.equal(bindingForPage(url, [binding, { ...binding, id: 'conflict' }]), undefined);
  assert.equal(bindingForPage(url, [{ ...binding, enabled: false }]), undefined);
  assert.throws(() => ruleForPage(url, ['cookie']));
});
