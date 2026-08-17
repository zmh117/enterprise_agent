export const MAX_TEXT_BYTES = 15 * 1024 * 1024;

export type FileFormatPolicyVersion = "text-v1" | "text-v2";
export type TextFormatCode = "TXT" | "LOG" | "MARKDOWN";
export type TextFormatAction =
  | "READ_METADATA"
  | "MATERIALIZE"
  | "EDIT"
  | "COMMIT"
  | "RETAIN"
  | "DELIVER";

export interface TextFormatDefinition {
  readonly code: TextFormatCode;
  readonly extension: string;
  readonly acceptedMediaTypes: ReadonlySet<string>;
  readonly canonicalMediaType: string;
  readonly actions: ReadonlySet<TextFormatAction>;
  readonly writable: boolean;
}

export class TextFormatPolicyError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "TextFormatPolicyError";
  }
}

const FULL_ACTIONS = new Set<TextFormatAction>([
  "READ_METADATA",
  "MATERIALIZE",
  "EDIT",
  "COMMIT",
  "RETAIN",
  "DELIVER"
]);
const READ_ONLY_ACTIONS = new Set<TextFormatAction>([
  "READ_METADATA",
  "MATERIALIZE",
  "RETAIN",
  "DELIVER"
]);

const DEFINITIONS: Readonly<Record<TextFormatCode, TextFormatDefinition>> = {
  TXT: {
    code: "TXT",
    extension: ".txt",
    acceptedMediaTypes: new Set(["text/plain"]),
    canonicalMediaType: "text/plain",
    actions: FULL_ACTIONS,
    writable: true
  },
  LOG: {
    code: "LOG",
    extension: ".log",
    acceptedMediaTypes: new Set(["text/plain", "application/octet-stream"]),
    canonicalMediaType: "text/plain",
    actions: READ_ONLY_ACTIONS,
    writable: false
  },
  MARKDOWN: {
    code: "MARKDOWN",
    extension: ".md",
    acceptedMediaTypes: new Set(["text/markdown", "text/plain"]),
    canonicalMediaType: "text/markdown",
    actions: FULL_ACTIONS,
    writable: true
  }
};

function definitions(policyVersion: FileFormatPolicyVersion): readonly TextFormatDefinition[] {
  return policyVersion === "text-v2"
    ? [DEFINITIONS.TXT, DEFINITIONS.LOG, DEFINITIONS.MARKDOWN]
    : [DEFINITIONS.TXT];
}

export function textFormatForName(
  displayName: string,
  policyVersion: FileFormatPolicyVersion
): TextFormatDefinition {
  if (
    displayName.length === 0 ||
    displayName.includes("/") ||
    displayName.includes("\\") ||
    displayName.includes("\0")
  ) {
    throw new TextFormatPolicyError("file_name_invalid", "file name is invalid");
  }
  const normalized = displayName.toLowerCase();
  const definition = definitions(policyVersion).find((item) =>
    normalized.endsWith(item.extension)
  );
  if (!definition) {
    throw new TextFormatPolicyError(
      "file_type_unsupported",
      "file format is not supported by this policy"
    );
  }
  return definition;
}

export function validateTextFormatMetadata(input: {
  readonly displayName: string;
  readonly mediaType: string;
  readonly policyVersion: FileFormatPolicyVersion;
  readonly expectedFormat?: TextFormatCode;
  readonly agentOutput?: boolean;
}): TextFormatDefinition {
  const definition = textFormatForName(input.displayName, input.policyVersion);
  const mediaType = input.mediaType.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  if (!definition.acceptedMediaTypes.has(mediaType)) {
    throw new TextFormatPolicyError(
      "file_mime_invalid",
      "file extension and media type do not match"
    );
  }
  if (input.expectedFormat !== undefined && definition.code !== input.expectedFormat) {
    throw new TextFormatPolicyError(
      "file_format_mismatch",
      "file format does not match frozen metadata"
    );
  }
  if (input.agentOutput && !definition.writable) {
    throw new TextFormatPolicyError("file_format_read_only", "file format is read-only");
  }
  return definition;
}

export function validateTextFormatAction(input: {
  readonly policyVersion: FileFormatPolicyVersion;
  readonly formatCode: TextFormatCode;
  readonly action: TextFormatAction;
}): TextFormatDefinition {
  const definition = definitions(input.policyVersion).find(
    (item) => item.code === input.formatCode
  );
  if (!definition) {
    throw new TextFormatPolicyError(
      "file_format_policy_denied",
      "file format is denied by this policy"
    );
  }
  if (!definition.actions.has(input.action)) {
    throw new TextFormatPolicyError("file_format_read_only", "file format is read-only");
  }
  return definition;
}

export function validateTextBytes(
  bytes: Uint8Array,
  options: { readonly agentOutput: boolean; readonly maxBytes?: number }
): { readonly sizeBytes: number; readonly hadUtf8Bom: boolean } {
  const maxBytes = options.maxBytes ?? MAX_TEXT_BYTES;
  if (bytes.byteLength > maxBytes) {
    throw new TextFormatPolicyError("file_too_large", "text file exceeds 15 MiB");
  }
  const hadUtf8Bom =
    bytes.byteLength >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf;
  if (options.agentOutput && hadUtf8Bom) {
    throw new TextFormatPolicyError(
      "file_output_bom_forbidden",
      "Agent output must use UTF-8 without BOM"
    );
  }
  if (
    bytes.byteLength >= 2 &&
    ((bytes[0] === 0xff && bytes[1] === 0xfe) ||
      (bytes[0] === 0xfe && bytes[1] === 0xff))
  ) {
    throw new TextFormatPolicyError("file_encoding_invalid", "file must use UTF-8");
  }
  let decoded: string;
  try {
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new TextFormatPolicyError("file_encoding_invalid", "file must use UTF-8");
  }
  if (decoded.includes("\0")) {
    throw new TextFormatPolicyError("file_type_invalid", "file contains binary content");
  }
  return { sizeBytes: bytes.byteLength, hadUtf8Bom };
}
