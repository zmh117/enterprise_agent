import type { BundleData, Context, EvidenceEvent, NetworkRecord } from '../../shared/contracts';

/** Hashes attest bytes; these checks attest only internal relationships, not truth of page content. */
export function validateRelations(targets: BundleData['targets'], events: Map<string, EvidenceEvent>, requests: NetworkRecord[]) {
  const byTarget = new Map(targets.map(t => [t.tabInstanceId, t]));
  const streams = new Map<string, { target: string; documentId: string; frame: number }>();
  for (const t of targets) for (const d of t.documents) {
    if (!d.documentId || !Number.isSafeInteger(d.chromeFrameId)) throw new Error('无效文档身份');
    if (d.recorderStreamId) {
      if (streams.has(d.recorderStreamId)) throw new Error('重复录制流身份');
      streams.set(d.recorderStreamId, { target: t.tabInstanceId, documentId: d.documentId, frame: d.chromeFrameId });
    }
  }
  const context = (target: string | null, c: Context | null | undefined) => {
    if (!c || c.documentId == null) { if (c?.chromeFrameId != null) throw new Error('不完整文档身份'); return; }
    if (!target || !byTarget.get(target)?.documents.some(d => d.documentId === c.documentId && d.chromeFrameId === c.chromeFrameId)) throw new Error('上下文文档不属于目标');
  };
  const nodeRoots = new Map<string, number>(); const rootDocs = new Map<string, string>();
  const rootsInEvent = new Map<string, Set<number>>();
  for (const e of events.values()) {
    if (Array.isArray(e.payload)) throw new Error('事件 payload 必须为对象');
    context(e.tabInstanceId, e.emitterContext); context(e.tabInstanceId, e.subjectContext); context(e.tabInstanceId, e.payload.documentContext);
    if (e.recorderStreamId) {
      const owner = streams.get(e.recorderStreamId);
      if (!owner || owner.target !== e.tabInstanceId || e.emitterContext?.documentId !== owner.documentId || e.emitterContext.chromeFrameId !== owner.frame) throw new Error('事件录制流与发送文档不一致');
    }
    if (e.kind === 'rrweb.event') {
      const rootIds = new Set<number>(); rootsInEvent.set(e.eventId, rootIds);
      const walk = (n: any, root?: number) => {
        if (!n) return;
        if (!Number.isSafeInteger(n.id) || n.id < 0) throw new Error('非法 rrweb 节点身份');
        if (n.type === 0) { root = n.id; rootIds.add(n.id); }
        if (typeof n.rootId === 'number') root = n.rootId;
        if (root !== undefined) nodeRoots.set(`${e.recorderStreamId}:${n.id}`, root);
        for (const child of n.childNodes ?? []) walk(child, root);
      };
      const r = e.payload.rrwebEvent;
      walk(r.data?.node);
      for (const add of r.data?.adds ?? []) walk(add.node, nodeRoots.get(`${e.recorderStreamId}:${add.parentId}`));
    }
    for (const n of e.payload.nodeContexts ?? []) {
      if (n.recorderStreamId !== e.recorderStreamId || !Number.isSafeInteger(n.nodeId) || n.nodeId < 0) throw new Error('节点映射录制流不一致');
      context(e.tabInstanceId, n.context);
      if (n.documentRoot && n.context?.documentId) {
        const key = `${e.recorderStreamId}:${n.nodeId}`; const before = rootDocs.get(key);
        if (before && before !== n.context.documentId) throw new Error('文档根节点归属冲突');
        rootDocs.set(key, n.context.documentId);
      }
    }
  }
  for (const t of targets) for (const d of t.documents) {
    if (d.status === 'baseline_received' && !d.baselineRef) throw new Error('已覆盖文档缺少基线引用');
    if (!d.baselineRef) continue;
    const ref = d.baselineRef; const e = events.get(ref.eventId);
    if (!e || e.tabInstanceId !== t.tabInstanceId || e.recorderStreamId !== ref.recorderStreamId || !rootsInEvent.get(e.eventId)?.has(ref.nodeId) || rootDocs.get(`${ref.recorderStreamId}:${ref.nodeId}`) !== d.documentId) throw new Error('文档基线引用错误');
  }
  for (const e of events.values()) {
    if (e.kind.startsWith('ui.') && e.payload.before?.status === 'observed') {
      const before = events.get(e.payload.before.snapshotRef);
      if (!before || before.kind !== 'ui.state_snapshot' || before.tabInstanceId !== e.tabInstanceId || before.recorderStreamId !== e.recorderStreamId || before.subjectContext?.documentId !== e.subjectContext?.documentId || before.sourceSeq >= e.sourceSeq || before.observedAt !== e.payload.before.observedAt || (before.payload.observation?.sourceTime ?? before.sourceTime) !== e.payload.before.sourceTime) throw new Error('before 观测引用或时间错误');
    }
    if (e.kind === 'ui.action') {
      if (!Array.isArray(e.payload.evidenceRefs) || e.payload.evidenceRefs.length !== 1) throw new Error('动作缺少唯一状态快照');
      const state = events.get(e.payload.evidenceRefs[0]);
      if (!state || state.kind !== 'ui.state_snapshot' || state.tabInstanceId !== e.tabInstanceId || state.recorderStreamId !== e.recorderStreamId || state.subjectContext?.documentId !== e.subjectContext?.documentId) throw new Error('动作快照跨目标或文档引用');
    }
    const ref = e.payload.target?.elementRef;
    if (ref) {
      const root = nodeRoots.get(`${ref.recorderStreamId}:${ref.nodeId}`);
      const doc = rootDocs.get(`${ref.recorderStreamId}:${root}`);
      if (ref.recorderStreamId !== e.recorderStreamId || root === undefined || !doc || doc !== e.subjectContext?.documentId) throw new Error('元素引用跨流、跨文档或节点缺失');
    }
    for (const n of e.payload.nodeContexts ?? []) {
      const root = nodeRoots.get(`${e.recorderStreamId}:${n.nodeId}`); const doc = rootDocs.get(`${e.recorderStreamId}:${root}`);
      if (doc && n.context?.documentId && doc !== n.context.documentId) throw new Error('节点主体与基线文档矛盾');
      if (e.subjectContext?.documentId && n.context?.documentId && e.subjectContext.documentId !== n.context.documentId) throw new Error('事件主体与节点映射矛盾');
    }
  }
  for (const n of requests) {
    context(n.tabInstanceId, { documentId: n.documentId ?? null, chromeFrameId: n.chromeFrameId });
    for (const id of n.evidenceRefs) {
      const e = events.get(id);
      if (!e || e.tabInstanceId !== n.tabInstanceId || e.payload.requestKey !== n.requestKey || (e.channel !== 'control' && (e.channel !== 'network' || e.streamId !== n.debuggerSessionKey))) throw new Error('请求证据跨目标或调试会话引用');
    }
    if (!Array.isArray(n.actionCandidates)) throw new Error('无效动作候选');
    for (const c of n.actionCandidates) {
      const e = events.get(c.actionId);
      if (!e || e.kind !== 'ui.action' || e.tabInstanceId !== n.tabInstanceId || c.confirmed !== false || typeof c.basis !== 'string' || (n.documentId && e.subjectContext?.documentId !== n.documentId)) throw new Error('动作候选引用错误');
    }
  }
}
