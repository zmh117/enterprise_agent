export type FieldError = { field?: string; message?: string };

export type PageMeta = {
  limit: number;
  next_cursor: string | null;
  has_more: boolean;
  generated_at?: string;
};

export type Page<T> = { items: T[]; page: PageMeta };

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code = "request_failed",
    public readonly fieldErrors: FieldError[] = [],
    public readonly correlationId = "",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function cookie(name: string): string {
  if (typeof document === "undefined") return "";
  const item = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name}=`));
  return item ? decodeURIComponent(item.slice(name.length + 1)) : "";
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (!headers.has("X-Correlation-ID")) {
    const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `web-${Date.now().toString(36)}`;
    headers.set("X-Correlation-ID", id);
  }
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookie("enterprise_agent_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(path, { ...init, headers, credentials: "include" });
  const correlationId = response.headers.get("x-correlation-id") ?? "";
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("enterprise-agent:unauthorized"));
    const detail = payload.detail;
    const structured = detail && typeof detail === "object" && !Array.isArray(detail) ? detail as Record<string, unknown> : {};
    const validation = Array.isArray(detail) ? detail as Array<{ loc?: string[]; msg?: string }> : [];
    throw new ApiError(
      response.status,
      typeof structured.message === "string" ? structured.message : typeof detail === "string" ? detail : "请求未完成",
      typeof structured.code === "string" ? structured.code : response.status === 409 ? "revision_conflict" : "request_failed",
      Array.isArray(structured.field_errors) ? structured.field_errors as FieldError[] : validation.map((item) => ({ field: item.loc?.slice(1).join("."), message: item.msg })),
      correlationId,
    );
  }
  return payload as T;
}

export function jsonBody(value: unknown): Pick<RequestInit, "body"> {
  return { body: JSON.stringify(value) };
}

export function withQuery(path: string, values: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}
