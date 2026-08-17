import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, mkdir, open, rm } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import {
  type FileFormatPolicyVersion,
  MAX_TEXT_BYTES,
  type TextFormatCode,
  textFormatForName
} from "./text-format-policy.js";

const FILE_TRANSFER_META_KEY = "enterprise-agent/file-transfer";
const FILE_TRANSFER_PROTOCOL = "enterprise-agent.file-transfer/v1";
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SHA256 = /^[a-f0-9]{64}$/;

type MaterializeControl = {
  readonly protocol: typeof FILE_TRANSFER_PROTOCOL;
  readonly action: "MATERIALIZE";
  readonly transfer_id: string;
  readonly sandbox_entry_handle: string;
  readonly relative_path: string;
  readonly expected_size_bytes: number;
  readonly expected_sha256: string;
  readonly format_code: TextFormatCode;
};

type UploadCommitControl = {
  readonly protocol: typeof FILE_TRANSFER_PROTOCOL;
  readonly action: "UPLOAD_COMMIT";
  readonly commit_id: string;
  readonly sandbox_entry_handle: string;
  readonly format_code: "TXT" | "MARKDOWN";
};

export type FileTransferControl = MaterializeControl | UploadCommitControl;

export interface FileTransferContext {
  readonly jobId: string;
  readonly workspacePath: string;
  readonly principalToken: string;
  readonly signal: AbortSignal;
  readonly fileFormatPolicyVersion?: FileFormatPolicyVersion;
}

export interface FileUploadReceipt {
  readonly fileId: string;
  readonly versionId: string;
  readonly sizeBytes: number;
  readonly sha256: string;
  readonly status: "COMMITTED" | "CONFLICT";
  readonly deliveryId: string;
  readonly deliveryStatus:
    | "NOT_REQUESTED"
    | "PENDING"
    | "RUNNING"
    | "RETRY_WAIT"
    | "SUCCEEDED"
    | "FAILED"
    | "DEAD"
    | "SKIPPED";
}

export interface FileTransferPort {
  download(request: {
    readonly transferId: string;
    readonly jobId: string;
    readonly principalToken: string;
    readonly signal: AbortSignal;
  }): AsyncIterable<Uint8Array>;

  upload(request: {
    readonly commitId: string;
    readonly jobId: string;
    readonly principalToken: string;
    readonly content: AsyncIterable<Uint8Array>;
    readonly signal: AbortSignal;
  }): Promise<FileUploadReceipt>;
}

export type FileTransferResult =
  | {
      readonly action: "MATERIALIZED";
      readonly sandbox_entry_handle: string;
      readonly relative_path: string;
      readonly size_bytes: number;
      readonly sha256: string;
      readonly format_code: TextFormatCode;
    }
  | {
      readonly action: "COMMITTED";
      readonly sandbox_entry_handle: string;
      readonly commit_id: string;
      readonly file_id: string;
      readonly version_id: string;
      readonly size_bytes: number;
      readonly sha256: string;
      readonly status: "COMMITTED" | "CONFLICT";
      readonly delivery_id: string;
      readonly delivery_status: FileUploadReceipt["deliveryStatus"];
    };

export interface SelectedSandboxEntry {
  readonly action: "SELECTED";
  readonly sandbox_entry_handle: string;
  readonly relative_path: string;
  readonly size_bytes: number;
  readonly sha256: string;
  readonly format_code: "TXT" | "MARKDOWN";
}

export class FileTransferBoundaryError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "FileTransferBoundaryError";
  }
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      "file transfer control must be an object"
    );
  }
  return value as Record<string, unknown>;
}

function assertExactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((item, index) => item !== required[index])) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      "file transfer control contains unknown or missing fields"
    );
  }
}

function identifier(value: unknown, field: string): string {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      `${field} must be an opaque identifier`
    );
  }
  return value;
}

function safeRelativePath(
  value: unknown,
  policyVersion: FileFormatPolicyVersion,
  writable: boolean
): { path: string; formatCode: TextFormatCode } {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 240 ||
    value.includes("\\") ||
    value.includes("\0") ||
    value.startsWith("/")
  ) {
    throw new FileTransferBoundaryError(
      "file_transfer_path_invalid",
      "relative_path must be a bounded text path"
    );
  }
  const normalized = relative(".", value);
  const topLevel = value.split("/")[0];
  if (
    normalized === ".." ||
    normalized.startsWith(`..${sep}`) ||
    normalized !== value ||
    !["inputs", "work", "outputs", "tmp"].includes(topLevel ?? "")
  ) {
    throw new FileTransferBoundaryError(
      "file_transfer_path_invalid",
      "relative_path must remain inside the Job Sandbox"
    );
  }
  let definition: ReturnType<typeof textFormatForName>;
  try {
    definition = textFormatForName(value.slice(value.lastIndexOf("/") + 1), policyVersion);
  } catch {
    throw new FileTransferBoundaryError(
      "file_transfer_path_invalid",
      "relative_path format is not allowed"
    );
  }
  if (writable && !definition.writable) {
    throw new FileTransferBoundaryError(
      "file_format_read_only",
      "selected file format is read-only"
    );
  }
  return { path: value, formatCode: definition.code };
}

async function rejectSymlinks(workspacePath: string, target: string): Promise<void> {
  const root = resolve(workspacePath);
  let current = root;
  for (const part of relative(root, target).split(sep).filter(Boolean)) {
    current = resolve(current, part);
    try {
      const state = await lstat(current);
      if (state.isSymbolicLink()) {
        throw new FileTransferBoundaryError(
          "file_transfer_symlink_denied",
          "file transfer path contains a symbolic link"
        );
      }
      if (!state.isDirectory() && !state.isFile()) {
        throw new FileTransferBoundaryError(
          "file_transfer_entry_invalid",
          "file transfer path contains a special file"
        );
      }
    } catch (error) {
      if (
        error !== null &&
        typeof error === "object" &&
        "code" in error &&
        error.code === "ENOENT"
      ) return;
      throw error;
    }
  }
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      `${field} must be a non-negative integer`
    );
  }
  return Number(value);
}

function sha256(value: unknown, field: string): string {
  if (typeof value !== "string" || !SHA256.test(value)) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      `${field} must be a lowercase SHA-256 digest`
    );
  }
  return value;
}

export function parseFileTransferControl(result: unknown): FileTransferControl {
  const envelope = object(result);
  const meta = object(envelope._meta);
  const control = object(meta[FILE_TRANSFER_META_KEY]);
  if (control.protocol !== FILE_TRANSFER_PROTOCOL) {
    throw new FileTransferBoundaryError(
      "file_transfer_protocol_unsupported",
      "unsupported file transfer protocol"
    );
  }
  if (control.action === "MATERIALIZE") {
    const keys = [
      "protocol",
      "action",
      "transfer_id",
      "sandbox_entry_handle",
      "relative_path",
      "expected_size_bytes",
      "expected_sha256"
    ];
    if ("format_code" in control) keys.push("format_code");
    assertExactKeys(control, keys);
    const formatCode = control.format_code ?? "TXT";
    if (!(["TXT", "LOG", "MARKDOWN"] as unknown[]).includes(formatCode)) {
      throw new FileTransferBoundaryError(
        "file_transfer_control_invalid",
        "format_code is invalid"
      );
    }
    const relativePath = safeRelativePath(
      control.relative_path,
      "text-v2",
      false
    );
    if (relativePath.formatCode !== formatCode) {
      throw new FileTransferBoundaryError(
        "file_transfer_control_invalid",
        "format_code does not match relative_path"
      );
    }
    return {
      protocol: FILE_TRANSFER_PROTOCOL,
      action: "MATERIALIZE",
      transfer_id: identifier(control.transfer_id, "transfer_id"),
      sandbox_entry_handle: identifier(
        control.sandbox_entry_handle,
        "sandbox_entry_handle"
      ),
      relative_path: relativePath.path,
      format_code: formatCode as TextFormatCode,
      expected_size_bytes: (() => {
        const size = nonNegativeInteger(control.expected_size_bytes, "expected_size_bytes");
        if (size > MAX_TEXT_BYTES) {
          throw new FileTransferBoundaryError(
            "file_transfer_size_mismatch",
            "text file exceeds the transfer size limit"
          );
        }
        return size;
      })(),
      expected_sha256: sha256(control.expected_sha256, "expected_sha256")
    };
  }
  if (control.action === "UPLOAD_COMMIT") {
    const keys = [
      "protocol",
      "action",
      "commit_id",
      "sandbox_entry_handle"
    ];
    if ("format_code" in control) keys.push("format_code");
    assertExactKeys(control, keys);
    const formatCode = control.format_code ?? "TXT";
    if (formatCode !== "TXT" && formatCode !== "MARKDOWN") {
      throw new FileTransferBoundaryError(
        "file_transfer_control_invalid",
        "commit format_code is invalid"
      );
    }
    return {
      protocol: FILE_TRANSFER_PROTOCOL,
      action: "UPLOAD_COMMIT",
      commit_id: identifier(control.commit_id, "commit_id"),
      sandbox_entry_handle: identifier(
        control.sandbox_entry_handle,
        "sandbox_entry_handle"
      ),
      format_code: formatCode
    };
  }
  throw new FileTransferBoundaryError(
    "file_transfer_action_unsupported",
    "unsupported file transfer action"
  );
}

function resolveSandboxPath(workspacePath: string, relativePath: string): string {
  const workspace = resolve(workspacePath);
  const target = resolve(workspace, relativePath);
  if (target === workspace || !target.startsWith(`${workspace}${sep}`)) {
    throw new FileTransferBoundaryError(
      "file_transfer_path_invalid",
      "file transfer target escaped the Job Sandbox"
    );
  }
  return target;
}

export class FileTransferCoordinator {
  private readonly entries = new Map<string, {
    relativePath: string;
    absolutePath: string;
    formatCode: TextFormatCode;
  }>();

  constructor(private readonly port: FileTransferPort) {}

  async selectSandboxOutput(
    relativePath: string,
    context: FileTransferContext,
    maximumSizeBytes = MAX_TEXT_BYTES
  ): Promise<SelectedSandboxEntry> {
    const selected = safeRelativePath(
      relativePath,
      context.fileFormatPolicyVersion ?? "text-v1",
      true
    );
    const safePath = selected.path;
    const topLevel = safePath.split("/")[0];
    if (topLevel !== "work" && topLevel !== "outputs") {
      throw new FileTransferBoundaryError(
        "file_transfer_path_invalid",
        "only work or outputs text files can be selected"
      );
    }
    const absolutePath = resolveSandboxPath(context.workspacePath, safePath);
    await rejectSymlinks(context.workspacePath, absolutePath);
    const state = await lstat(absolutePath);
    if (!state.isFile()) {
      throw new FileTransferBoundaryError(
        "file_transfer_entry_invalid",
        "sandbox entry must reference a regular file"
      );
    }
    if (state.size > maximumSizeBytes) {
      throw new FileTransferBoundaryError(
        "file_transfer_size_mismatch",
        "sandbox output exceeds the text size limit"
      );
    }
    const digest = createHash("sha256");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let sizeBytes = 0;
    const prefix: number[] = [];
    try {
      for await (const chunk of createReadStream(absolutePath)) {
        if (context.signal.aborted) throw context.signal.reason;
        const bytes = chunk as Buffer;
        sizeBytes += bytes.byteLength;
        if (sizeBytes > maximumSizeBytes) {
          throw new FileTransferBoundaryError(
            "file_transfer_size_mismatch",
            "sandbox output exceeds the text size limit"
          );
        }
        digest.update(bytes);
        for (const value of bytes.subarray(0, Math.max(0, 3 - prefix.length))) {
          prefix.push(value);
        }
        if (decoder.decode(bytes, { stream: true }).includes("\0")) {
          throw new FileTransferBoundaryError(
            "file_transfer_type_invalid",
            "sandbox output contains binary content"
          );
        }
      }
      if (decoder.decode().includes("\0")) {
        throw new FileTransferBoundaryError(
          "file_transfer_type_invalid",
          "sandbox output contains binary content"
        );
      }
    } catch (error) {
      if (error instanceof FileTransferBoundaryError) throw error;
      if (error instanceof TypeError) {
        throw new FileTransferBoundaryError(
          "file_transfer_encoding_invalid",
          "sandbox output must be valid UTF-8"
        );
      }
      throw error;
    }
    if (prefix[0] === 0xef && prefix[1] === 0xbb && prefix[2] === 0xbf) {
      throw new FileTransferBoundaryError(
        "file_output_bom_forbidden",
        "sandbox output must use UTF-8 without BOM"
      );
    }
    const handle = `sandbox-entry:${randomUUID()}`;
    this.entries.set(handle, {
      relativePath: safePath,
      absolutePath,
      formatCode: selected.formatCode
    });
    return {
      action: "SELECTED",
      sandbox_entry_handle: handle,
      relative_path: safePath,
      size_bytes: sizeBytes,
      sha256: digest.digest("hex"),
      format_code: selected.formatCode as "TXT" | "MARKDOWN"
    };
  }

  async registerSandboxEntry(
    sandboxEntryHandle: string,
    relativePath: string,
    context: FileTransferContext
  ): Promise<void> {
    if (!IDENTIFIER.test(sandboxEntryHandle) || this.entries.has(sandboxEntryHandle)) {
      throw new FileTransferBoundaryError(
        "file_transfer_handle_conflict",
        "sandbox entry handle is invalid or already bound"
      );
    }
    const selected = safeRelativePath(
      relativePath,
      context.fileFormatPolicyVersion ?? "text-v1",
      false
    );
    const safePath = selected.path;
    const absolutePath = resolveSandboxPath(context.workspacePath, safePath);
    await rejectSymlinks(context.workspacePath, absolutePath);
    const state = await lstat(absolutePath);
    if (!state.isFile()) {
      throw new FileTransferBoundaryError(
        "file_transfer_entry_invalid",
        "sandbox entry must reference a regular file"
      );
    }
    this.entries.set(sandboxEntryHandle, {
      relativePath: safePath,
      absolutePath,
      formatCode: selected.formatCode
    });
  }

  async processMcpControlResult(
    result: unknown,
    context: FileTransferContext
  ): Promise<FileTransferResult> {
    const control = parseFileTransferControl(result);
    return control.action === "MATERIALIZE"
      ? this.materialize(control, context)
      : this.upload(control, context);
  }

  private async materialize(
    control: MaterializeControl,
    context: FileTransferContext
  ): Promise<FileTransferResult> {
    const selected = safeRelativePath(
      control.relative_path,
      context.fileFormatPolicyVersion ?? "text-v1",
      false
    );
    if (selected.formatCode !== control.format_code) {
      throw new FileTransferBoundaryError(
        "file_transfer_control_invalid",
        "materialization format does not match the Job policy"
      );
    }
    const absolutePath = resolveSandboxPath(context.workspacePath, control.relative_path);
    if (this.entries.has(control.sandbox_entry_handle)) {
      throw new FileTransferBoundaryError(
        "file_transfer_handle_conflict",
        "sandbox entry handle is already bound"
      );
    }
    await rejectSymlinks(context.workspacePath, absolutePath);
    await mkdir(dirname(absolutePath), { recursive: true, mode: 0o700 });
    const file = await open(absolutePath, "wx", 0o600);
    const digest = createHash("sha256");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let sizeBytes = 0;
    try {
      for await (const chunk of this.port.download({
        transferId: control.transfer_id,
        jobId: context.jobId,
        principalToken: context.principalToken,
        signal: context.signal
      })) {
        if (context.signal.aborted) throw context.signal.reason;
        sizeBytes += chunk.byteLength;
        if (sizeBytes > control.expected_size_bytes) {
          throw new FileTransferBoundaryError(
            "file_transfer_size_mismatch",
            "download exceeded the expected size"
          );
        }
        digest.update(chunk);
        if (decoder.decode(chunk, { stream: true }).includes("\0")) {
          throw new FileTransferBoundaryError(
            "file_transfer_type_invalid",
            "download contains binary content"
          );
        }
        await file.write(chunk);
      }
      if (decoder.decode().includes("\0")) {
        throw new FileTransferBoundaryError(
          "file_transfer_type_invalid",
          "download contains binary content"
        );
      }
    } catch (error) {
      await file.close();
      await rm(absolutePath, { force: true });
      if (error instanceof TypeError) {
        throw new FileTransferBoundaryError(
          "file_transfer_encoding_invalid",
          "download must be valid UTF-8"
        );
      }
      throw error;
    }
    await file.close();
    const actualSha256 = digest.digest("hex");
    if (
      sizeBytes !== control.expected_size_bytes ||
      actualSha256 !== control.expected_sha256
    ) {
      await rm(absolutePath, { force: true });
      throw new FileTransferBoundaryError(
        "file_transfer_integrity_mismatch",
        "download did not match the frozen file version"
      );
    }
    this.entries.set(control.sandbox_entry_handle, {
      relativePath: control.relative_path,
      absolutePath,
      formatCode: control.format_code
    });
    return {
      action: "MATERIALIZED",
      sandbox_entry_handle: control.sandbox_entry_handle,
      relative_path: control.relative_path,
      size_bytes: sizeBytes,
      sha256: actualSha256,
      format_code: control.format_code
    };
  }

  private async upload(
    control: UploadCommitControl,
    context: FileTransferContext
  ): Promise<FileTransferResult> {
    const entry = this.entries.get(control.sandbox_entry_handle);
    if (!entry) {
      throw new FileTransferBoundaryError(
        "file_transfer_handle_unknown",
        "sandbox entry handle is not materialized"
      );
    }
    if (entry.formatCode !== control.format_code) {
      throw new FileTransferBoundaryError(
        "file_transfer_handle_conflict",
        "sandbox entry handle format does not match commit intent"
      );
    }
    await rejectSymlinks(context.workspacePath, entry.absolutePath);
    const fileState = await lstat(entry.absolutePath);
    if (!fileState.isFile()) {
      throw new FileTransferBoundaryError(
        "file_transfer_entry_invalid",
        "sandbox entry must reference a regular file"
      );
    }
    const validatedDigest = createHash("sha256");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let validatedSizeBytes = 0;
    const prefix: number[] = [];
    try {
      for await (const chunk of createReadStream(entry.absolutePath)) {
        if (context.signal.aborted) throw context.signal.reason;
        const bytes = chunk as Buffer;
        validatedSizeBytes += bytes.byteLength;
        if (validatedSizeBytes > MAX_TEXT_BYTES) {
          throw new FileTransferBoundaryError(
            "file_transfer_size_mismatch",
            "sandbox output exceeds the text size limit"
          );
        }
        for (const value of bytes.subarray(0, Math.max(0, 3 - prefix.length))) {
          prefix.push(value);
        }
        if (decoder.decode(bytes, { stream: true }).includes("\0")) {
          throw new FileTransferBoundaryError(
            "file_transfer_type_invalid",
            "sandbox output contains binary content"
          );
        }
        validatedDigest.update(bytes);
      }
      if (decoder.decode().includes("\0")) {
        throw new FileTransferBoundaryError(
          "file_transfer_type_invalid",
          "sandbox output contains binary content"
        );
      }
      if (prefix[0] === 0xef && prefix[1] === 0xbb && prefix[2] === 0xbf) {
        throw new FileTransferBoundaryError(
          "file_output_bom_forbidden",
          "sandbox output must use UTF-8 without BOM"
        );
      }
    } catch (error) {
      if (error instanceof FileTransferBoundaryError) throw error;
      if (error instanceof TypeError) {
        throw new FileTransferBoundaryError(
          "file_transfer_encoding_invalid",
          "sandbox output must be valid UTF-8"
        );
      }
      throw error;
    }
    const expectedSha256 = validatedDigest.digest("hex");
    const uploadDigest = createHash("sha256");
    let sizeBytes = 0;
    const content = (async function* (): AsyncGenerator<Uint8Array> {
      for await (const chunk of createReadStream(entry.absolutePath)) {
        if (context.signal.aborted) throw context.signal.reason;
        const bytes = chunk as Buffer;
        sizeBytes += bytes.byteLength;
        uploadDigest.update(bytes);
        yield bytes;
      }
    })();
    let receipt: FileUploadReceipt;
    try {
      receipt = await this.port.upload({
        commitId: control.commit_id,
        jobId: context.jobId,
        principalToken: context.principalToken,
        content,
        signal: context.signal
      });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new FileTransferBoundaryError(
          "file_transfer_encoding_invalid",
          "sandbox output must be valid UTF-8"
        );
      }
      throw error;
    }
    const actualSha256 = uploadDigest.digest("hex");
    if (
      validatedSizeBytes !== fileState.size ||
      sizeBytes !== validatedSizeBytes ||
      actualSha256 !== expectedSha256 ||
      receipt.sizeBytes !== sizeBytes ||
      receipt.sha256 !== actualSha256 ||
      !SHA256.test(receipt.sha256) ||
      !IDENTIFIER.test(receipt.fileId) ||
      !IDENTIFIER.test(receipt.versionId) ||
      !["COMMITTED", "CONFLICT"].includes(receipt.status) ||
      ![
        "NOT_REQUESTED",
        "PENDING",
        "RUNNING",
        "RETRY_WAIT",
        "SUCCEEDED",
        "FAILED",
        "DEAD",
        "SKIPPED"
      ].includes(receipt.deliveryStatus) ||
      Boolean(receipt.deliveryId) === (receipt.deliveryStatus === "NOT_REQUESTED") ||
      (receipt.deliveryId !== "" && !IDENTIFIER.test(receipt.deliveryId))
    ) {
      throw new FileTransferBoundaryError(
        "file_transfer_receipt_mismatch",
        "upload receipt did not match the local sandbox entry"
      );
    }
    return {
      action: "COMMITTED",
      sandbox_entry_handle: control.sandbox_entry_handle,
      commit_id: control.commit_id,
      file_id: receipt.fileId,
      version_id: receipt.versionId,
      size_bytes: sizeBytes,
      sha256: actualSha256,
      status: receipt.status,
      delivery_id: receipt.deliveryId,
      delivery_status: receipt.deliveryStatus
    };
  }
}
