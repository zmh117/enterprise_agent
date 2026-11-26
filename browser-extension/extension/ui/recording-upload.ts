import {detail,protectedName,unsafeText,type Omission,type Json} from '../../shared/business-json';
import {
  platformTraffic,
  rememberPlatform,
} from '../../shared/platform-traffic';
import { EvidenceDB, sha256 } from '../storage/database';
import {
  terminal,
  type BlobRecord,
  type Chunk,
  type EvidenceEvent,
  type NetworkRecord,
  type Recording,
} from '../../shared/contracts';
import { PlatformError } from './agent-answer';

type Row = Record<string, Json>;
type Ref = { id: string; key: string; pos?: number };
type Descriptor = {
  number: number;
  uncompressed_bytes: number;
  sha256: string;
};
type Counts = {
  saved: number;
  shareable: number;
  platform_excluded: number;
  ids_sha256: string;
};
type Manifest = {
  local_recording_id: string;
  checkpoint: number;
  projection_version: '2';
  parts: Descriptor[];
  coverage: {
    actions: Counts;
    requests: Counts;
    gaps: { reason: string; count: number }[];
  };
};
type Projection = {
  manifest: Manifest;
  samples: string[];
  parts: () => AsyncGenerator<Uint8Array>;
};
const encoder = new TextEncoder();
const maxPart = 1024 * 1024;
function canonical(value: Json): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.keys(value)
        .sort()
        .map((k) => JSON.stringify(k) + ':' + canonical(value[k]!))
        .join(',') +
      '}'
    );
  return JSON.stringify(value);
}
export const canonicalManifest = (manifest: Manifest) => canonical(manifest);

const idOk = (id: string) =>
  /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}$/.test(id) && !id.includes('\n');
const actionKinds = new Set([
  'click',
  'submit',
  'input',
  'change',
  'select',
  'invalid',
  'programmatic_change',
  'dialog_open',
  'dialog_close',
  'notice_change',
  'issue_marker',
]);
const methods = new Set([
  'GET',
  'HEAD',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
  'OPTIONS',
  'CONNECT',
  'TRACE',
]);
const offset = (when: string, start: string) =>
  Math.max(0, Date.parse(when) - Date.parse(start)) || 0;

function actionRow(e: EvidenceEvent, r: Recording): Row {
  const p = e.payload,
    target = p.target ?? {};
  const input: Record<string, unknown> = { ...p };
  const named = target.type === 'password' || target.inputType === 'password' ||
    /(?:current-password|new-password|one-time-code)/i.test(String(target.autocomplete ?? '')) ||
    [target.id, target.name].some(
    (v) => typeof v === 'string' && protectedName(v),
  );
  // Raw page text, URLs, notices and surrounding DOM strings have no business-field provenance.
  if (p.context && typeof p.context === 'object') {
    const { url, notices, ...context } = p.context;
    input.context = context;
  }
  delete input.evidenceRefs;
  if (input.target) {
    const { text, label, ...rest } = target;
    input.target = rest;
  }
  if (input.after && typeof input.after === 'object') {
    const { text, validationMessage, ...rest } = input.after as Record<
      string,
      unknown
    >;
    input.after = rest;
  }
  const d = named
    ? { value: null, omissions: [{ path: '', reason: 'protected' }] }
    : detail(input);
  if (!named && p.context?.url)
    d.omissions.push({ path: '/context/url', reason: 'unstructured' });
  if (!named && p.context?.notices)
    d.omissions.push({ path: '/context/notices', reason: 'unstructured' });
  if (!named && (target.text || target.label))
    d.omissions.push({ path: '/target', reason: 'unstructured' });
  if (!named && (p.after?.text || p.after?.validationMessage))
    d.omissions.push({ path: '/after', reason: 'unstructured' });
  return {
    kind: 'action',
    eventId: e.eventId,
    offset_ms: offset(e.observedAt, r.startedAt),
    action: actionKinds.has(p.action) ? p.action : 'other',
    control_code: null,
    details: d,
  };
}

async function requestRow(
  db: EvidenceDB,
  n: NetworkRecord,
  r: Recording,
  actions: Set<string>,
): Promise<Row> {
  const url = new URL(n.request.url);
  const template = r.policy.businessRules.find(
    (rule) => rule.origin === url.origin && rule.pathPrefix === url.pathname,
  );
  const row: Row = {
    kind: 'request',
    requestKey: n.requestKey,
    offset_ms: offset(n.startedAt, r.startedAt),
    method: methods.has(n.request.method) ? n.request.method : 'OTHER',
    path_template:
      template && /^\/[A-Za-z0-9._{}/:-]{0,255}$/.test(template.pathPrefix)
        ? template.pathPrefix
        : null,
    http_status:
      typeof n.response.httpStatus === 'number' &&
      n.response.httpStatus >= 100 &&
      n.response.httpStatus <= 599
        ? n.response.httpStatus
        : null,
    duration_ms: n.endedAt ? offset(n.endedAt, n.startedAt) : null,
    network_outcome: n.networkOutcome,
    business_outcome: n.businessOutcome,
    associations: n.actionCandidates
      .filter((a) => actions.has(a.actionId))
      .map((a) => ({ eventId: a.actionId, basis: 'time_proximity' }))
      .sort((a, b) =>
        a.eventId < b.eventId ? -1 : a.eventId > b.eventId ? 1 : 0,
      ),
  };
  const correlation = n.serverCorrelation;
  if (
    correlation?.requestId &&
    /^response_header:(x-request-id|request-id)$/.test(
      correlation.requestIdSource ?? '',
    ) &&
    idOk(correlation.requestId) &&
    !unsafeText(correlation.requestId)
  )
    row.request_id = correlation.requestId;
  if (
    correlation?.traceId &&
    /^(response|request)_header:traceparent$/.test(
      correlation.traceIdSource ?? '',
    ) &&
    /^[0-9a-f]{32}$/i.test(correlation.traceId)
  )
    row.trace_id = correlation.traceId;
  const authPath =
    /(?:^|\/)(?:auth|oauth2?|login|signin|token|credentials?|password)(?:\/|$)/i.test(
      url.pathname,
    );
  function params(values: URLSearchParams) {
    const fields: Record<string, string | string[]> = Object.create(null);
    for (const [name, value] of values) {
      const prior = fields[name];
      fields[name] =
        prior === undefined
          ? value
          : Array.isArray(prior)
            ? [...prior, value]
            : [prior, value];
    }
    return fields;
  }
  for (const side of ['request', 'response'] as const) {
    const b = n[side];
    row[side + '_capture'] = b.bodyCaptureStatus;
    if (authPath) {
      row[side + '_fields'] = 'excluded_by_policy';
      continue;
    }
    const fields: Record<string, unknown> = Object.create(null);
    const omitted: Omission[] = [];
    if (side === 'request' && url.search)
      fields.query = params(url.searchParams);
    // Transport headers can carry opaque vendor-specific session credentials.
    // Only dedicated correlation fields are shared; raw headers stay local.
    if (Object.keys(b.headers).length)
      omitted.push({ path: '/headers', reason: 'protected' });
    const state = b.bodyCaptureStatus;
    if (state === 'captured' && b.bodyRef) {
      const ref = /^bodies\/([a-zA-Z0-9-]+)\.(json|txt)$/.exec(b.bodyRef);
      if (!ref) throw new Error('本地正文引用无效');
      const blob = await db.recordedItem<BlobRecord>(
        'blobs',
        ref[1]!,
        r.recordingId,
      );
      if (blob.path !== b.bodyRef) throw new Error('本地正文已变化');
      if (
        b.redactionStatus === 'fully_masked' ||
        b.redactionStatus === 'failed_excluded'
      )
        omitted.push({ path: '/body', reason: 'protected' });
      else if (blob.encoding === 'utf8' && /json/i.test(blob.mime)) {
        try {
          fields.body = JSON.parse(blob.data);
        } catch {
          omitted.push({ path: '/body', reason: 'unstructured' });
        }
      } else if (
        blob.encoding === 'utf8' &&
        /x-www-form-urlencoded/i.test(blob.mime)
      ) {
        fields.body = params(new URLSearchParams(blob.data));
      } else omitted.push({ path: '/body', reason: 'unstructured' });
    } else if (!['empty', 'not_applicable'].includes(state)) {
      omitted.push({
        path: '/body',
        reason:
          state === 'truncated'
            ? 'truncated'
            : state === 'excluded_by_policy'
              ? 'protected'
              : 'not_captured',
      });
    }
    if (Object.keys(fields).length || omitted.length) {
      const d = detail(fields);
      d.omissions.push(...omitted);
      row[side + '_fields'] = d.omissions.length ? 'partial' : 'included';
      row[side + '_details'] = d;
    } else row[side + '_fields'] = 'empty';
    if (
      side === 'response' &&
      ['included', 'partial'].includes(String(row.response_fields)) &&
      (typeof n.businessCode === 'string' || typeof n.businessCode === 'number')
    ) {
      const code = String(n.businessCode);
      if (/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(code))
        row.response_code = code;
    }
  }
  return row;
}

export async function prepareRecording(
  db: EvidenceDB,
  r: Recording,
  origin: string,
  signal: AbortSignal,
): Promise<Projection> {
  if (!terminal(r.state) || r.saveState !== 'saved')
    throw new Error('请选择已经封存并保存成功的录制');
  const prior = (await chrome.storage.local.get('agentPlatformOrigins'))
    .agentPlatformOrigins;
  if (Array.isArray(prior))
    for (const origin of prior)
      if (typeof origin === 'string') rememberPlatform(origin);
  const actions: Ref[] = [],
    requests: Ref[] = [];
  let savedActions = 0,
    savedRequests = 0;
  for await (const key of db.recordingKeys('chunks', r.recordingId)) {
    signal.throwIfAborted();
    const chunk = await db.recordedItem<Chunk>('chunks', key, r.recordingId);
    chunk.events.forEach((e, pos) => {
      if (e.kind === 'ui.action') {
        savedActions++;
        if (!platformTraffic(String(e.payload.context?.url ?? ''), origin))
          actions.push({ id: e.eventId, key, pos });
      }
    });
  }
  for await (const key of db.recordingKeys('network', r.recordingId)) {
    signal.throwIfAborted();
    const n = await db.recordedItem<NetworkRecord>(
      'network',
      key,
      r.recordingId,
    );
    savedRequests++;
    if (!platformTraffic(n.request.url, origin))
      requests.push({ id: n.requestKey, key });
  }
  async function counts(refs: Ref[], saved: number): Promise<Counts> {
    refs.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    if (refs.some((ref, i) => !idOk(ref.id) || ref.id === refs[i - 1]?.id))
      throw new Error('录制证据标识重复或格式不受支持');
    return {
      saved,
      shareable: refs.length,
      platform_excluded: saved - refs.length,
      ids_sha256: await sha256(refs.map((ref) => ref.id + '\n').join('')),
    };
  }
  const reasons = new Map<string, number>();
  for (const gap of r.gaps) {
    const k = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/.test(gap.code)
      ? gap.code
      : 'unknown';
    reasons.set(k, (reasons.get(k) ?? 0) + 1);
  }
  if (actions.length + requests.length > 1_000_000 || reasons.size > 256)
    throw new Error('录制超过平台可共享条数或缺口种类上限');
  const coverage = {
    actions: await counts(actions, savedActions),
    requests: await counts(requests, savedRequests),
    gaps: [...reasons]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([reason, count]) => ({ reason, count })),
  };
  const ids = new Set(actions.map((a) => a.id));
  const samples: string[] = [];
  async function* rows() {
    let chunk: Chunk | undefined;
    for (const ref of actions) {
      signal.throwIfAborted();
      if (chunk?.id !== ref.key)
        chunk = await db.recordedItem<Chunk>('chunks', ref.key, r.recordingId);
      const event = chunk.events[ref.pos!]!;
      if (event.eventId !== ref.id) throw new Error('本地录制已改变');
      yield actionRow(event, r);
    }
    for (const ref of requests) {
      signal.throwIfAborted();
      yield await requestRow(
        db,
        await db.recordedItem<NetworkRecord>('network', ref.key, r.recordingId),
        r,
        ids,
      );
    }
  }
  async function* parts() {
    let buffer = new Uint8Array(maxPart),
      size = 0;
    let actionCount = 0,
      requestCount = 0;
    for await (const row of rows()) {
      if (
        row.kind === 'action'
          ? row.eventId !== actions[actionCount++]?.id
          : row.requestKey !== requests[requestCount++]?.id
      )
        throw new Error('投影证据标识与录制源不一致');
      const text = canonical(row) + '\n',
        data = encoder.encode(text);
      if (data.length > maxPart)
        throw new Error('单条证据超过 1 MiB，无法共享。本地录制仍可导出。');
      if (size + data.length > maxPart) {
        yield buffer.slice(0, size);
        buffer = new Uint8Array(maxPart);
        size = 0;
      }
      buffer.set(data, size);
      size += data.length;
      if (samples.length < 2) samples.push(text.slice(0, 1200));
    }
    if (actionCount !== actions.length || requestCount !== requests.length)
      throw new Error('投影条数与录制源不一致');
    if (size) yield buffer.slice(0, size);
  }
  const descriptors: Descriptor[] = [];
  let projectedBytes = 0;
  for await (const raw of parts()) {
    projectedBytes += raw.length;
    if (projectedBytes > 256 * maxPart)
      throw new Error('录制业务投影超过 256 MiB 上限');
    descriptors.push({
      number: descriptors.length,
      uncompressed_bytes: raw.length,
      sha256: await sha256(raw),
    });
  }
  if ((await db.getRecording(r.recordingId))?.checkpoint !== r.checkpoint)
    throw new Error('录制检查点发生变化，请重新预览');
  return {
    manifest: {
      projection_version: '2',
      local_recording_id: r.recordingId,
      checkpoint: r.checkpoint,
      coverage,
      parts: descriptors,
    },
    samples,
    parts,
  };
}

type PlatformRequest = (
  path: string,
  options: RequestInit,
) => Promise<Response>;
export async function uploadRecording(
  prepared: Projection,
  app: string,
  scope: string,
  attempt: string,
  request: PlatformRequest,
  signal: AbortSignal,
  progress: (text: string) => void,
) {
  const init = async () =>
    (
      await request(
        '/applications/' + encodeURIComponent(app) + '/recordings',
        {
          method: 'POST',
          signal,
          headers: {
            'Content-Type': 'application/json',
            'X-Application-Scope': scope,
          },
          body: JSON.stringify({
            upload_attempt_id: attempt,
            manifest: prepared.manifest,
          }),
        },
      )
    ).json();
  let recordingId: string | undefined;
  for (let round = 0; round < 3; round++) {
    try {
      const receipt = await init();
      if (
        typeof receipt.recording_id !== 'string' ||
        !receipt.recording_id ||
        (recordingId !== undefined && receipt.recording_id !== recordingId) ||
        !Array.isArray(receipt.missing_parts) ||
        !['ready', 'uploading'].includes(receipt.state)
      )
        throw new Error('录制回执无效');
      recordingId = receipt.recording_id;
      const missing = new Set<number>(receipt.missing_parts);
      if (
        missing.size !== receipt.missing_parts.length ||
        (receipt.state === 'ready' && missing.size !== 0) ||
        [...missing].some(
          (n) => !Number.isInteger(n) || !prepared.manifest.parts[n],
        )
      )
        throw new Error('服务端缺片清单无效');
      if (receipt.state === 'ready') return receipt.recording_id as string;
      let number = 0;
      if (missing.size)
        for await (const raw of prepared.parts()) {
          const part = prepared.manifest.parts[number++];
          if (!part || (await sha256(raw)) !== part.sha256)
            throw new Error('本地内容与确认时的清单不同');
          if (!missing.has(part.number)) continue;
          progress(
            '正在上传分片 ' +
              (part.number + 1) +
              ' / ' +
              prepared.manifest.parts.length,
          );
          const gz = await new Response(
            new Blob([new Uint8Array(raw)])
              .stream()
              .pipeThrough(new CompressionStream('gzip')),
          ).arrayBuffer();
          const ack = await (
            await request(
              '/recordings/' +
                encodeURIComponent(receipt.recording_id) +
                '/parts/' +
                part.number,
              {
                method: 'PUT',
                signal,
                headers: {
                  'Content-Type': 'application/x-ndjson',
                  'Content-Encoding': 'gzip',
                },
                body: gz,
              },
            )
          ).json();
          if (
            ack.recording_id !== receipt.recording_id ||
            ack.number !== part.number ||
            ack.sha256 !== part.sha256
          )
            throw new Error('分片回执不匹配');
        }
      if (missing.size && number !== prepared.manifest.parts.length)
        throw new Error('本地分片数量与确认时的清单不同');
      const final = await (
        await request(
          '/recordings/' +
            encodeURIComponent(receipt.recording_id) +
            '/complete',
          { method: 'POST', signal },
        )
      ).json();
      if (
        final.recording_id !== receipt.recording_id ||
        final.state !== 'ready'
      )
        throw new Error('录制发布回执无效');
      return receipt.recording_id as string;
    } catch (e) {
      signal.throwIfAborted();
      if (
        round === 2 ||
        !(
          e instanceof TypeError ||
          e instanceof SyntaxError ||
          (e instanceof PlatformError &&
            (e.status >= 500 ||
              ['parts_missing', 'resume_upload'].includes(e.code)))
        )
      )
        throw e;
    }
  }
  throw new Error('上传未完成，请继续上传');
}
