import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CaptureGate, newTarget } from '../extension/background/session/gate';
import { LineageTracker } from '../extension/background/lineage/lineage';
import { FragmentAssembler } from '../extension/background/session/fragments';
import { recording } from './helpers';
import { now } from '../shared/contracts';

test('parent cutoff invalidates every old task but keeps descendant eligible', () => {
  const r = recording(); const parent = newTarget(r, { id: 1, windowId: 10 }, 5, 'start', 'root'); const child = newTarget(r, { id: 2, windowId: 10 }, 6, 'start', 'derived', parent);
  const gate = new CaptureGate(r, new Map([[1, parent], [2, child]])); const old = gate.token(parent, 'network'); const childToken = gate.token(child, 'network');
  assert.equal(gate.allows(old), true); gate.stopTarget(parent, 'tab_closed', 8); parent.lifecycle = 'CLOSED';
  assert.equal(gate.allows(old), false); assert.equal(gate.allows(childToken), true);
  gate.stopAll('session_stopped', 9); assert.equal(gate.allows(childToken), false);
});
test('single channel loss leaves page and semantic valid; adding root does not invalidate others', () => {
  const r = recording(); const t = newTarget(r, { id: 1, windowId: 1 }, 1, 'start', 'root'); const gate = new CaptureGate(r, new Map([[1, t]]));
  const network = gate.token(t, 'network'), page = gate.token(t, 'page'), semantic = gate.token(t, 'semantic');
  gate.loseChannel(t, 'network', 'canceled_by_user'); r.scopeVersion++;
  assert.equal(gate.allows(network), false); assert.equal(gate.allows(page), true); assert.equal(gate.allows(semantic), true);
  assert.equal(gate.allows({ ...page, browserRunId: 'old-run' }), false);
});
test('trusted delayed sources resolve grandchildren after a parent close without retroactive scope', () => {
  const r = recording(); const a = newTarget(r, { id: 1, windowId: 1 }, 10, 'start', 'root'); const targets = new Map([[1, a]]); const tracker = new LineageTracker();
  const relation = (parent: number, child: number, seq: number) => tracker.relation({ source: 'webNavigation.onCreatedNavigationTarget', sourceBrowserTabId: parent, targetBrowserTabId: child, observedAt: now(), observedSeq: seq, sourceTime: -999999, sourceClock: 'untrusted_for_authorization' });
  tracker.created(9, 9, now()); relation(1, 9, 15); // Old child is never authorized by a late source event.
  tracker.created(2, 11, now()); tracker.created(3, 12, now()); relation(2, 3, 13); a.cutoffSeq = 14; a.lifecycle = 'CLOSED'; relation(1, 2, 16);
  let resolved = tracker.resolve(targets); assert.deepEqual(resolved.map(x => x.id), [2]);
  const b = newTarget(r, { id: 2, windowId: 1 }, resolved[0]!.seq, 'start', 'derived', a); targets.set(2, b);
  resolved = tracker.resolve(targets); assert.deepEqual(resolved.map(x => x.id), [3]);
  tracker.created(4, 17, now()); relation(1, 4, 18); assert.ok(!tracker.resolve(targets).some(x => x.id === 4));
});
test('source conflicts, self cycles and reused existing named windows do not authorize', () => {
  const r = recording(); const a = newTarget(r, { id: 1, windowId: 1 }, 10, 'start', 'root'); const tracker = new LineageTracker();
  for (const parent of [1, 2]) tracker.relation({ source: 'tabs.onCreated', sourceBrowserTabId: parent, targetBrowserTabId: 3, observedSeq: 12, observedAt: now() });
  tracker.created(3, 11, now());
  tracker.relation({ source: 'webNavigation.onCreatedNavigationTarget', sourceBrowserTabId: 1, targetBrowserTabId: 4, observedSeq: 13, observedAt: now() }); // No observed creation.
  assert.deepEqual(tracker.resolve(new Map([[1, a]])), []); assert.deepEqual(tracker.ambiguous(), [3]);
});
test('IPC retries reassemble whole UTF-8 data; conflicts and oversize fail closed', () => {
  const a = new FragmentAssembler(1024, 800, 512); const base = { type: 'capture.batch' as const, ticketId: 't', packetId: 1, total: 2 };
  assert.equal(a.accept({ ...base, index: 1, data: '中文"}' }), null);
  assert.equal(a.accept({ ...base, index: 1, data: '中文"}' }), null);
  assert.equal(a.accept({ ...base, index: 0, data: '{"data":"' }), '{"data":"中文"}');
  a.accept({ ...base, packetId: 2, index: 0, data: 'a' });
  assert.throws(() => a.accept({ ...base, packetId: 2, index: 0, data: 'b' }), /conflict/);
  assert.equal(a.dropTicket('t'), 1);
  assert.throws(() => a.accept({ ...base, index: 0, data: '汉'.repeat(300) }), /invalid_fragment/);
});
test('metadata-only fragment flooding has a count bound', () => {
  const a = new FragmentAssembler(1024, 800, 512);
  assert.throws(() => a.accept({ type: 'capture.batch', ticketId: 't', packetId: 1, index: 0, total: 2, data: '' }), /invalid_fragment/);
  for (let id = 1; id <= 64; id++) a.accept({ type: 'capture.batch', ticketId: 't', packetId: id, index: 0, total: 2, data: 'a' });
  assert.throws(() => a.accept({ type: 'capture.batch', ticketId: 't', packetId: 65, index: 0, total: 2, data: 'a' }), /reassembly_count_limit/);
});

test('7.3 模拟重复来源通知只合并两个来源，不重复登记同一后代', () => {
  const r = recording(); const root = newTarget(r, { id: 1, windowId: 1 }, 10, 'start', 'root'); const targets = new Map([[1, root]]); const tracker = new LineageTracker();
  tracker.created(2, 11, now()); tracker.created(2, 12, now());
  for (let i = 0; i < 4; i++) for (const source of ['tabs.onCreated','webNavigation.onCreatedNavigationTarget']) tracker.relation({ source, sourceBrowserTabId: 1, targetBrowserTabId: 2, observedSeq: 13 + i, observedAt: now() });
  const candidates = tracker.resolve(targets); assert.equal(candidates.length, 1); assert.equal(candidates[0]!.evidence.length, 2); assert.equal(candidates[0]!.seq, 11);
  targets.set(2, newTarget(r, { id: 2, windowId: 1 }, 11, 'start', 'derived', root)); assert.equal(tracker.resolve(targets).length, 0);
});
