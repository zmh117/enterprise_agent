import { detail } from './business-json';

export function liveBody(raw: string, mime: string, limit: number) {
  const utf8 = new TextEncoder();
  // Non-ASCII characters may use more than one byte. Avoid encoding an arbitrarily long value.
  if (raw.length > limit) return { status: 'over_limit', minimum_bytes: raw.length } as const;
  const size = utf8.encode(raw).byteLength;
  if (size > limit) return { status: 'over_limit', original_bytes: size } as const;
  if (!raw) return { status: 'empty', original_bytes: 0 } as const;
  if (!/^(?:application|text)\/(?:[\w.-]+\+)?json(?:\s*;|$)/i.test(mime))
    return { status: 'unsupported_mime', original_bytes: size } as const;
  // Bound JSON.parse expansion and recursion independently of the byte budget.
  let nodes = 0,
    depth = 0,
    quoted = false,
    escaped = false;
  for (const c of raw) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === '"') quoted = false;
    } else if (c === '"') quoted = true;
    else if (c === '[' || c === '{') {
      depth++;
      nodes++;
    } else if (c === ']' || c === '}') depth--;
    else if (c === ',' || c === ':') nodes++;
    if (depth > 28 || nodes > 250_000)
      return { status: 'structure_limit', original_bytes: size } as const;
  }
  try {
    const exactNumbers = new WeakSet<object>();
    let sourceNumbers = false;
    const parser = JSON as typeof JSON & {
      rawJSON(source: string): object;
    };
    const json: unknown = parser.parse(
      raw,
      (_key: string, value: unknown, context?: { source?: string }) => {
        if (
          typeof value !== 'number' ||
          !context?.source ||
          (String(value) === context.source && Number.isFinite(value))
        )
          return value;
        // Preserve identifiers and precise decimal literals before Number can round them.
        const literal = parser.rawJSON(context.source);
        exactNumbers.add(literal);
        sourceNumbers = true;
        return literal;
      },
    );
    if (typeof json !== 'object' || !json)
      return { status: 'unstructured', original_bytes: size } as const;
    const projected = detail(json, exactNumbers);
    return {
      status: 'captured',
      original_bytes: size,
      omitted: projected.omissions.length,
      ...(sourceNumbers ? { numeric_precision: 'source' } : {}),
      value: projected.value,
    } as const;
  } catch {
    return { status: 'invalid_json', original_bytes: size } as const;
  }
}
