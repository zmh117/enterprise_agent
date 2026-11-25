import validators from './generated/schema.js';

export function assertSchema(name: 'manifest' | 'recording' | 'target' | 'event' | 'network' | 'pagePacket', value: unknown): void {
  const validate = validators[name]!;
  if (!validate(value)) {
    const e = validate.errors?.[0];
    throw new Error(`${name} schema 错误: ${e?.instancePath ?? '/'} ${e?.keyword ?? 'invalid'}`);
  }
}
