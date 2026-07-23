export type FieldError = {
  field: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: FieldError[]
  readonly currentRevision?: number

  constructor(options: {
    status: number
    code: string
    message: string
    fieldErrors?: FieldError[]
    currentRevision?: number
  }) {
    super(options.message)
    this.name = "ApiError"
    this.status = options.status
    this.code = options.code
    this.fieldErrors = options.fieldErrors ?? []
    this.currentRevision = options.currentRevision
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
}

const csrfCookieName =
  import.meta.env.VITE_CSRF_COOKIE_NAME || "enterprise_agent_csrf"

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase()
  const headers = new Headers(options.headers)
  headers.set("Accept", "application/json")
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json")
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie(csrfCookieName)
    if (csrf) {
      headers.set("X-CSRF-Token", csrf)
    }
  }
  let response: Response
  try {
    response = await fetch(path, {
      ...options,
      method,
      headers,
      credentials: "include",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError({
      status: 0,
      code: "network_unavailable",
      message: "管理服务当前不可用，请稍后重试。",
    })
  }
  const payload = await readJson(response)
  if (!response.ok) {
    throw toApiError(response.status, payload)
  }
  return payload as T
}

function readCookie(name: string): string {
  const prefix = `${encodeURIComponent(name)}=`
  for (const part of document.cookie.split(";")) {
    const normalized = part.trim()
    if (normalized.startsWith(prefix)) {
      return decodeURIComponent(normalized.slice(prefix.length))
    }
  }
  return ""
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? ""
  if (!contentType.includes("application/json")) {
    return null
  }
  try {
    return await response.json()
  } catch {
    return null
  }
}

function toApiError(status: number, payload: unknown): ApiError {
  const body = isRecord(payload) ? payload : {}
  const rawDetail = body.detail
  const detail = isRecord(rawDetail)
    ? rawDetail
    : { message: typeof rawDetail === "string" ? rawDetail : "" }
  const code =
    typeof detail.code === "string"
      ? detail.code
      : status === 401
        ? "authentication_required"
        : status === 403
          ? "forbidden"
          : status === 404
            ? "not_found"
            : "request_failed"
  const fieldErrors = Array.isArray(detail.field_errors)
    ? detail.field_errors.flatMap((value) => {
        if (!isRecord(value)) return []
        return [
          {
            field: String(value.field ?? ""),
            message: String(value.message ?? "输入无效"),
          },
        ]
      })
    : []
  return new ApiError({
    status,
    code,
    message:
      typeof detail.message === "string" && detail.message
        ? detail.message
        : "请求未能完成。",
    fieldErrors,
    currentRevision:
      typeof detail.current_revision === "number"
        ? detail.current_revision
        : undefined,
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

