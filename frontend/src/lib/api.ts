export type FieldError = { field?: string; message?: string };

export class ApiError extends Error {
  status: number;
  code: string;
  fieldErrors: FieldError[];

  constructor(status: number, message: string, code = "request_failed", fieldErrors: FieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }
}

function cookie(name: string): string {
  const item = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return item ? decodeURIComponent(item.slice(name.length + 1)) : "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("enterprise_agent_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(path, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const structured = detail && typeof detail === "object" && !Array.isArray(detail) ? detail : {};
    const validation = Array.isArray(detail) ? detail : [];
    throw new ApiError(
      response.status,
      structured.message ?? (typeof detail === "string" ? detail : "请求未完成"),
      structured.code ?? (response.status === 409 ? "revision_conflict" : "request_failed"),
      structured.field_errors ?? validation.map((item: { loc?: string[]; msg?: string }) => ({
        field: item.loc?.slice(1).join("."),
        message: item.msg,
      })),
    );
  }
  return payload as T;
}

export const jsonBody = (value: unknown): Pick<RequestInit, "body"> => ({
  body: JSON.stringify(value),
});
