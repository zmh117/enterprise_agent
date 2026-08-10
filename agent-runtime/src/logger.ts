import errors from "../contracts/v1/errors.json" with { type: "json" };

export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogSink = (line: string) => void;

const DENIED_FIELDS = new Set(errors.sensitive_field_denylist.map((item) => item.toLowerCase()));
const MAX_LOG_VALUE_CHARS = 2048;

function sensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return [...DENIED_FIELDS].some(
    (denied) => normalized === denied || normalized.endsWith(`_${denied}`)
  );
}

function safeString(value: string): string {
  const redacted = value
    .replace(/Bearer\s+[/A-Za-z0-9._~+-]+=*/gi, "Bearer [REDACTED]")
    .replace(/(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+/g, "$1[REDACTED]")
    .replace(/(postgres(?:ql)?:\/\/)[^/@\s]+@/gi, "$1[REDACTED]@");
  return redacted.length > MAX_LOG_VALUE_CHARS
    ? `${redacted.slice(0, MAX_LOG_VALUE_CHARS)}[TRUNCATED]`
    : redacted;
}

export function sanitizeLogValue(value: unknown, key = ""): unknown {
  if (sensitiveKey(key)) return "[REDACTED]";
  if (typeof value === "string") return safeString(value);
  if (Array.isArray(value)) return value.slice(0, 128).map((item) => sanitizeLogValue(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .slice(0, 128)
        .map(([childKey, child]) => [childKey, sanitizeLogValue(child, childKey)])
    );
  }
  return value;
}

export class StructuredLogger {
  constructor(
    private readonly minimumLevel: LogLevel,
    private readonly sink: LogSink = (line) => process.stdout.write(`${line}\n`)
  ) {}

  log(level: LogLevel, event: string, fields: Record<string, unknown> = {}): void {
    const order: LogLevel[] = ["debug", "info", "warn", "error"];
    if (order.indexOf(level) < order.indexOf(this.minimumLevel)) return;
    this.sink(
      JSON.stringify({
        timestamp: new Date().toISOString(),
        level,
        event,
        ...(sanitizeLogValue(fields) as Record<string, unknown>)
      })
    );
  }
}
