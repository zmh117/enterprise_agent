export class PlatformError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

import { openAuthPopup } from './ui/auth-popup';
type Credential = {
  access_token: string;
  user_id: string;
  tenant_id: string;
  expires: number;
  renewAt: number;
};
const prefix = '/api/browser-extension';
const encode = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
const random = () => encode(crypto.getRandomValues(new Uint8Array(32)));
async function checked(res: Response): Promise<Response> {
  if (res.ok) return res;
  const payload = await res.json().catch(() => ({}));
  throw new PlatformError(
    res.status,
    payload.code ?? payload.detail?.code ?? payload.detail ?? 'platform_error',
  );
}

export class Platform {
  private credential?: Credential;
  private renewing?: Promise<Credential>;
  private identity?: string;
  readonly controller = new AbortController();
  constructor(readonly origin: string) {}
  get signal() {
    return this.controller.signal;
  }
  async login(interactive: boolean): Promise<Credential> {
    if (this.renewing) return this.renewing;
    this.renewing = this.exchange(interactive);
    try {
      return await this.renewing;
    } finally {
      this.renewing = undefined;
    }
  }
  private async exchange(interactive: boolean): Promise<Credential> {
    const verifier = random(),
      state = random();
    const challenge = encode(
      new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))),
    );
    const callback = chrome.identity.getRedirectURL();
    const url = new URL(prefix + '/auth/authorize', this.origin);
    url.search = new URLSearchParams({
      client_id: chrome.runtime.id,
      redirect_uri: callback,
      state,
      code_challenge_method: 'S256',
      code_challenge: challenge,
      ...(interactive ? {} : { prompt: 'none' }),
    }).toString();
    const result = interactive
      ? await openAuthPopup(url.href)
      : await chrome.identity.launchWebAuthFlow({
          url: url.href,
          interactive: false,
          abortOnLoadForNonInteractive: false,
          timeoutMsForNonInteractive: 15000,
        });
    this.signal.throwIfAborted();
    if (!result) throw new Error('未完成登录');
    const dest = new URL(result);
    if (dest.origin + dest.pathname !== callback || dest.searchParams.get('state') !== state)
      throw new Error('登录回调校验失败');
    const error = dest.searchParams.get('error');
    if (error) throw new PlatformError(error === 'access_denied' ? 403 : 401, error);
    const code = dest.searchParams.get('code');
    if (!code) throw new Error('未取得授权');
    const res = await checked(
      await fetch(this.origin + prefix + '/auth/token', {
        method: 'POST',
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        signal: this.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: chrome.runtime.id,
          redirect_uri: callback,
          code,
          code_verifier: verifier,
        }),
      }),
    );
    const token = await res.json();
    this.signal.throwIfAborted();
    if (
      !token.user_id ||
      !token.tenant_id ||
      typeof token.access_token !== 'string' ||
      !Number.isSafeInteger(token.expires_in) ||
      token.expires_in <= 0 ||
      token.expires_in > 900
    )
      throw new Error('平台授权响应无效');
    const identity = JSON.stringify([token.tenant_id, token.user_id]);
    if (this.identity && this.identity !== identity) {
      this.controller.abort();
      throw new PlatformError(403, 'account_changed');
    }
    this.identity = identity;
    const now = Date.now();
    const expires = now + token.expires_in * 1000;
    // A short-lived renewal can be capped by the parent session deadline.
    // Relative lifetimes are rounded to seconds, so tolerate one second of skew.
    const previous = this.credential;
    const capped = previous && expires <= previous.expires + 1000;
    return (this.credential = {
      access_token: token.access_token,
      tenant_id: token.tenant_id,
      user_id: token.user_id,
      expires,
      renewAt: capped ? expires : expires - 5000,
    });
  }
  async request(path: string, options: RequestInit): Promise<Response> {
    const signal = options.signal ? AbortSignal.any([this.signal, options.signal]) : this.signal;
    let token = this.credential;
    signal.throwIfAborted();
    if (!token || token.renewAt <= Date.now()) token = await this.login(false);
    const send = (value: Credential) => {
      const headers = new Headers(options.headers);
      headers.set('Authorization', 'Bearer ' + value.access_token);
      return fetch(this.origin + prefix + path, {
        ...options,
        headers,
        signal,
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
      }).then(checked);
    };
    try {
      return await send(token);
    } catch (e) {
      if (!(e instanceof PlatformError && e.status === 401 && e.code === 'credential_expired'))
        throw e;
      if (this.credential === token) this.credential = undefined;
      const renewed = this.credential ?? (await this.login(false));
      if (/^\/recordings\/[^/]+\/(?:parts\/\d+|complete)$/.test(path))
        throw new PlatformError(409, 'resume_upload');
      return send(renewed);
    }
  }
}
