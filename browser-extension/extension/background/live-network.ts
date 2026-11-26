import { BodyQueue } from './cdp/network';
import { apiAllowed } from '../../shared/policy';
import { unsafeText } from '../../shared/business-json';
import { liveBody } from '../../shared/live-body';
import type { PageSource } from '../../shared/live-page';
import type { Policy } from '../../shared/contracts';

type Emit = (tab: number, source: PageSource, event: Record<string, unknown>, at?: number) => void;
interface RequestState {
  key: string;
  source: PageSource;
  mime: string;
  bytes: number;
  status?: number;
  method: string;
}
interface NetworkTab {
  tab: number;
  root?: { id: string; loaderId: string; url: string; urlFragment?: string };
  contexts: Map<number, string>;
  verified?: { frame: string; loader: string; ticket: string };
  missingSource: number;
  rejectedSource: number;
  pending: Map<string, RequestState>;
  owned: boolean;
  detached: boolean;
}
export type NetworkPolicy = Pick<Policy, 'apiRules' | 'requestTypes' | 'budgets'>;
const send = (tab: number, method: string, params: object = {}): Promise<any> =>
  chrome.debugger.sendCommand({ tabId: tab }, method, params);
const sensitivePath =
  /(?:^|\/)(?:oauth2?|oidc|sso|login|logout|auth(?:enticate|orize|entication)?|tokens?|sessions?|credentials?|passwords?)(?:\/|$)/i;
export class LiveNetwork {
  private tabs = new Map<number, NetworkTab>();
  private queue: BodyQueue;
  constructor(
    private policy: NetworkPolicy,
    private source: (id: number, ticket: string, url: string) => PageSource | undefined,
    private emit: Emit,
    private gap: (tab: number, reason: string) => void,
  ) {
    this.queue = new BodyQueue(policy.budgets.bodyConcurrency, policy.budgets.queueBytes);
  }
  async attach(id: number, resume = false) {
    if (this.tabs.has(id)) {
      await this.verify(id);
      return;
    }
    if ((1 + this.tabs.size) * this.policy.budgets.bodyBytes > this.policy.budgets.queueBytes) {
      this.gap(id, '网络缓存预算不足，请提高队列预算或减少标签');
      return;
    }
    const t: NetworkTab = {
      tab: id,
      contexts: new Map(),
      pending: new Map(),
      missingSource: 0,
      rejectedSource: 0,
      owned: false,
      detached: false,
    };
    this.tabs.set(id, t);
    let phase = '连接';
    try {
      let alreadyOwned = false;
      if (resume) {
        try {
          await send(id, 'Page.getFrameTree');
          alreadyOwned = true;
        } catch {
          /* A new attachment needs explicit Chrome ownership. */
        }
      }
      if (!alreadyOwned) await chrome.debugger.attach({ tabId: id }, '1.3');
      t.owned = true;
      if (t.detached) {
        await chrome.debugger.detach({ tabId: id }).catch(() => {});
        return;
      }
      const size = this.policy.budgets.bodyBytes;
      phase = '读取顶层文档';
      await send(id, 'Page.enable');
      const tree = await send(id, 'Page.getFrameTree');
      t.root = tree.frameTree.frame;
      phase = '识别扩展文档';
      await send(id, 'Runtime.enable');
      phase = '启用网络采集';
      await send(id, 'Network.enable', {
        maxResourceBufferSize: size,
        maxTotalBufferSize: size,
        maxPostDataSize: size,
      });
      await this.verify(id);
    } catch (e) {
      if (!t.detached) {
        const message = String(e);
        const reason = /another debugger|already attached/i.test(message)
          ? '调试器已占用'
          : /cannot access|restricted|not allowed|cannot attach|permission|denied/i.test(message)
            ? '浏览器限制访问'
            : /detached|not attached|closed/i.test(message)
              ? '调试连接已结束'
              : '协议调用失败';
        this.gap(id, phase + '失败 · ' + reason);
        await this.stop(id);
      }
    }
  }
  status(id: number) {
    const t = this.tabs.get(id);
    return {
      attached: !!t?.owned,
      root: !!t?.root,
      mapped: !!t?.verified,
      contexts: t?.contexts.size ?? 0,
      missing: t?.missingSource ?? 0,
      rejected: t?.rejectedSource ?? 0,
    };
  }
  async verify(id: number) {
    const t = this.tabs.get(id);
    if (!t?.root || t.detached) return;
    const loader = t.root.loaderId,
      frame = t.root.id;
    for (const [ctx, frameId] of t.contexts) {
      if (frameId !== frame) continue;
      try {
        const result = await send(id, 'Runtime.evaluate', {
          contextId: ctx,
          expression: 'globalThis.__mesLiveTicket',
          returnByValue: true,
          silent: true,
          throwOnSideEffect: true,
        });
        if (
          typeof result.result?.value === 'string' &&
          t.root?.loaderId === loader &&
          t.contexts.get(ctx) === frame &&
          !t.detached
        )
          t.verified = { frame, loader, ticket: result.result.value };
      } catch {
        /* A destroyed context cannot establish a request source. */
      }
    }
  }
  event(source: chrome.debugger.Debuggee, method: string, p: any) {
    const t = source.tabId === undefined ? undefined : this.tabs.get(source.tabId);
    if (!t || t.detached || ('sessionId' in source && source.sessionId)) return;
    if (method === 'Runtime.executionContextCreated') {
      const ctx = p.context;
      const extension = 'chrome-extension://' + chrome.runtime.id;
      if (
        ctx?.auxData?.isDefault === false &&
        (ctx.origin === extension || ctx.name === extension || ctx.name === chrome.runtime.id)
      ) {
        t.contexts.set(ctx.id, ctx.auxData.frameId);
        void this.verify(t.tab);
      }
      return;
    }
    if (method === 'Runtime.executionContextsCleared') {
      t.verified = undefined;
      t.contexts.clear();
      return;
    }
    if (method === 'Runtime.executionContextDestroyed') {
      if (t.contexts.delete(p.executionContextId)) t.verified = undefined;
      return;
    }
    if (method === 'Page.frameNavigated' && !p.frame.parentId) {
      t.root = p.frame;
      t.verified = undefined;
      void this.verify(t.tab);
      return;
    }
    if (method === 'Page.navigatedWithinDocument' && t.root?.id === p.frameId) {
      if (t.root) {
        t.root.url = p.url;
        t.root.urlFragment = undefined;
      }
      return;
    }
    const id = p.requestId;
    if (typeof id !== 'string') return;
    const prior = t.pending.get(id);
    if (method === 'Network.requestWillBeSent') {
      if (prior) {
        this.emit(t.tab, prior.source, {
          kind: 'request_end',
          request_key: prior.key,
          outcome: 'redirect',
          status: p.redirectResponse?.status,
        });
        t.pending.delete(id);
      }
      const binding = t.verified;
      if (!['Fetch', 'XHR'].includes(p.type)) return;
      if (
        !binding ||
        !p.loaderId ||
        binding.frame !== p.frameId ||
        binding.loader !== p.loaderId ||
        typeof p.documentURL !== 'string' ||
        !t.root
      ) {
        t.missingSource++;
        return;
      }
      // CDP may carry the fragment separately on the top frame and omit it from documentURL.
      const urlAtStart = t.root.url + (t.root.urlFragment ?? '');
      if (urlAtStart.split('#')[0] !== p.documentURL.split('#')[0]) {
        t.rejectedSource++;
        return;
      }
      const owner = this.source(
        t.tab,
        binding.ticket,
        p.documentURL.includes('#') ? p.documentURL : urlAtStart,
      );
      if (!owner) {
        t.rejectedSource++;
        return;
      }
      const req = p.request;
      if (!owner || !req || !apiAllowed(this.policy, req.url, p.type)) return;
      const url = new URL(req.url);
      if (url.username || url.password || sensitivePath.test(url.pathname)) return;
      const route = this.policy.apiRules
        .filter((r) => r.origin === url.origin && url.pathname.startsWith(r.pathPrefix))
        .sort((a, b) => b.pathPrefix.length - a.pathPrefix.length)[0];
      if (!route) return;
      let path = route.pathPrefix;
      try {
        const decoded = decodeURIComponent(url.pathname);
        if (
          !unsafeText(decoded) &&
          !sensitivePath.test(decoded) &&
          /^[\p{L}\p{N}_.\/-]{1,768}$/u.test(decoded)
        )
          path = url.pathname;
      } catch {
        /* Keep the explicitly configured route when the path is opaque. */
      }
      if (t.pending.size >= 512) {
        this.gap(t.tab, '并发请求超过采集上限');
        return;
      }
      const key = crypto.randomUUID(),
        verb = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(req.method)
          ? req.method
          : 'OTHER';
      const r: RequestState = { key, source: owner, mime: '', bytes: 0, method: verb };
      t.pending.set(id, r);
      this.emit(
        t.tab,
        owner,
        {
          kind: 'request',
          request_key: key,
          method: verb,
          api_origin: route.origin,
          api_path: path,
        },
        Number.isFinite(p.wallTime) ? Math.round(p.wallTime * 1000) : undefined,
      );
      if (typeof req.postData === 'string') {
        const contentType = header(req.headers, 'content-type') ?? '';
        this.emit(t.tab, owner, {
          kind: 'body',
          side: 'request',
          request_key: key,
          ...liveBody(req.postData, contentType, this.policy.budgets.bodyBytes),
        });
      } else if (req.hasPostData)
        this.emit(t.tab, owner, {
          kind: 'body',
          side: 'request',
          request_key: key,
          status: 'unavailable',
        });
      return;
    }
    if (!prior) return;
    const r = prior;
    if (method === 'Network.responseReceived') {
      const res = p.response;
      r.status = res.status;
      r.mime = res.mimeType ?? '';
      const trace = /^[a-f\d]{2}-([a-f\d]{32})-[a-f\d]{16}-[a-f\d]{2}$/i.exec(
        header(res.headers, 'traceparent') ?? '',
      )?.[1];
      const requestId = header(res.headers, 'x-request-id') ?? header(res.headers, 'request-id');
      this.emit(t.tab, r.source, {
        kind: 'response',
        request_key: r.key,
        status: r.status,
        ...(trace ? { trace_id: trace } : {}),
        ...(requestId && /^[0-9a-f-]{16,64}$/i.test(requestId) ? { request_id: requestId } : {}),
      });
    } else if (
      method === 'Network.dataReceived' &&
      Number.isSafeInteger(p.dataLength) &&
      p.dataLength >= 0
    ) {
      r.bytes += p.dataLength;
    } else if (method === 'Network.loadingFailed') {
      t.pending.delete(id);
      this.emit(t.tab, r.source, { kind: 'request_end', request_key: r.key, outcome: 'failed' });
    } else if (method === 'Network.loadingFinished') {
      this.emit(t.tab, r.source, { kind: 'request_end', request_key: r.key, outcome: 'finished' });
      this.body(t, id, r);
    }
  }
  private body(t: NetworkTab, id: string, r: RequestState) {
    const max = this.policy.budgets.bodyBytes;
    const valid = () => !t.detached && t.pending.get(id) === r;
    const finish = (data: Record<string, unknown>) => {
      if (!valid()) return;
      t.pending.delete(id);
      this.emit(t.tab, r.source, { kind: 'body', side: 'response', request_key: r.key, ...data });
    };
    if (r.method === 'HEAD' || r.status === 204 || r.status === 304) {
      finish({ status: 'empty' });
      return;
    }
    if (r.bytes > max) {
      finish({ status: 'over_limit', original_bytes: r.bytes });
      return;
    }
    if (!/^(application|text)\/(?:[\w.-]+\+)?json(?:;|$)/i.test(r.mime)) {
      finish({ status: 'unsupported_mime' });
      return;
    }
    if (
      !this.queue.add(
        String(t.tab),
        valid,
        async () => {
          try {
            const result = await send(t.tab, 'Network.getResponseBody', { requestId: id });
            if (!valid()) return;
            if (typeof result?.body !== 'string') {
              finish({ status: 'unavailable' });
              return;
            }
            if (result.base64Encoded && result.body.length > Math.ceil(max / 3) * 4) {
              finish({ status: 'over_limit' });
              return;
            }
            const raw = result.base64Encoded
              ? new TextDecoder('utf-8', { fatal: true }).decode(
                  Uint8Array.from(atob(result.body), (c) => c.charCodeAt(0)),
                )
              : result.body;
            finish(liveBody(raw, r.mime, max));
          } catch {
            finish({ status: 'unavailable' });
          }
        },
        max,
      )
    )
      finish({ status: 'queue_limit' });
  }
  async stop(id: number, detached = false) {
    const t = this.tabs.get(id);
    if (!t) return;
    this.tabs.delete(id);
    t.detached = true;
    this.queue.cancel(String(id));
    for (const r of t.pending.values())
      this.emit(id, r.source, { kind: 'request_end', request_key: r.key, outcome: 'interrupted' });
    t.pending.clear();
    if (t.owned && !detached) await chrome.debugger.detach({ tabId: id }).catch(() => {});
  }
}

function header(headers: Record<string, unknown> | undefined, name: string) {
  for (const key of Object.keys(headers ?? {}))
    if (key.toLowerCase() === name && typeof headers![key] === 'string')
      return headers![key] as string;
}
