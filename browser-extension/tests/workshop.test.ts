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

test('路径按段继承，根目录提供默认车间，更具体的规则优先', () => {
  const origin = 'http://127.0.0.1:8080';
  const bind = (path: string, id: string, keys: string[] = []): WorkshopBinding => ({
    id, revision: 1, enabled: true, environment_id: 'e', base_id: 'b', workshop_id: id,
    rule: ruleForPage(origin + path, keys), reserved_paths: [],
  });
  const users = bind('/users', 'A'), profiles = bind('/agent-profiles', 'B'), root = bind('/', 'default');
  const routes = [profiles, users];
  for (const path of ['/users', '/users/', '/users/roles?sort=name', '/users/roles/1#detail'])
    assert.equal(bindingForPage(origin + path, routes), users);
  for (const path of ['/reports', '/users-admin', '/'])
    assert.equal(bindingForPage(origin + path, routes), undefined);
  assert.equal(bindingForPage(origin + '/reports', [...routes, root]), root);
  assert.equal(bindingForPage(origin + '/agent-profiles/edit', [root, ...routes]), profiles);
  assert.equal(bindingForPage('http://127.0.0.1:8081/users', routes), undefined);
  assert.equal(bindingForPage(origin + '/login', [root], origin), undefined);
  assert.equal(bindingForPage(origin + '/users/roles', [{...users, reserved_paths: undefined}]), undefined);
  const keyed = bind('/users#/orders?shop=B', 'keyed', ['shop']);
  assert.equal(bindingForPage(origin + '/users#/orders/sub?shop=B', [users, keyed]), keyed);
  for (const url of ['/users#/orders/sub', '/users#/orders/sub?shop=C', '/users#/orders/sub?shop=B&shop=C'])
    assert.equal(bindingForPage(origin + url, [users, keyed]), undefined);
  const reserved = {...root, reserved_paths: [{path:'/private', hash_path:''}]};
  assert.equal(bindingForPage(origin + '/private/orders', [reserved]), undefined);
  assert.equal(bindingForPage(origin + '/users/roles', [root, {...users, enabled:false}]), undefined);
});
