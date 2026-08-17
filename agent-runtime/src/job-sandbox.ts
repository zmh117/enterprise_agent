import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  readFile,
  readdir,
  rm,
  stat,
  writeFile
} from "node:fs/promises";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import {
  type FileFormatPolicyVersion,
  textFormatForName
} from "./text-format-policy.js";

export type { FileFormatPolicyVersion } from "./text-format-policy.js";

export const SANDBOX_MARKER = ".enterprise-agent-sandbox.json";
export const SANDBOX_CAPACITY_BYTES = 224 * 1024 * 1024;
export const SANDBOX_FILE_BYTES = 15 * 1024 * 1024;
export const SANDBOX_FILE_LIMIT = 40;
export const FILE_TOOL_NAMES = ["Read", "Glob", "Grep", "Edit", "Write"] as const;
export const FILE_TOOLS = new Set<string>(FILE_TOOL_NAMES);
const TOP_LEVEL = new Set(["inputs", "work", "outputs", "tmp"]);
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export class JobSandboxError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "JobSandboxError";
  }
}

export interface JobSandboxLimits {
  readonly capacityBytes: number;
  readonly maxFiles: number;
  readonly maxFileBytes: number;
}
const DEFAULT_LIMITS: JobSandboxLimits = {
  capacityBytes: SANDBOX_CAPACITY_BYTES,
  maxFiles: SANDBOX_FILE_LIMIT,
  maxFileBytes: SANDBOX_FILE_BYTES
};

export class JobSandbox {
  constructor(
    readonly jobId: string,
    readonly path: string,
    readonly limits: JobSandboxLimits,
    readonly fileFormatPolicyVersion: FileFormatPolicyVersion = "text-v1"
  ) {}

  async cleanup(): Promise<void> {
    await rm(this.path, { recursive: true, force: true });
  }

  async authorizeTool(
    toolName: string,
    rawInput: unknown
  ): Promise<Record<string, unknown>> {
    if (!FILE_TOOLS.has(toolName) || !record(rawInput)) {
      deny("sandbox_tool_denied", "tool is not allowed in the Job Sandbox");
    }
    const input = { ...rawInput };
    const expected: Record<string, Set<string>> = {
      Read: new Set(["file_path", "offset", "limit", "pages"]),
      Glob: new Set(["pattern", "path"]),
      Grep: new Set([
        "pattern", "path", "glob", "output_mode", "-B", "-A", "-C", "-n",
        "-i", "type", "head_limit", "offset", "multiline"
      ]),
      Write: new Set(["file_path", "content"]),
      Edit: new Set(["file_path", "old_string", "new_string", "replace_all"])
    };
    if (Object.keys(input).some((key) => !expected[toolName]?.has(key))) {
      deny("sandbox_tool_input_invalid", "tool input contains unknown fields");
    }
    const directoryTool = toolName === "Glob" || toolName === "Grep";
    const pathField = directoryTool ? "path" : "file_path";
    const rawPath = input[pathField] ?? (directoryTool ? "." : "");
    const relativePath = toolName === "Glob"
      ? safeDirectoryPath(rawPath, this.path)
      : safeRelativePath(
          rawPath,
          toolName === "Grep",
          this.path,
          this.fileFormatPolicyVersion,
          toolName === "Write" || toolName === "Edit"
        );
    const target = resolveSandboxPath(this.path, relativePath, directoryTool);
    await rejectSymlinks(this.path, target);
    const current = await optionalStat(target);
    if (toolName === "Read" || toolName === "Glob" || toolName === "Grep") {
      if (!current) deny("sandbox_entry_missing", "sandbox entry does not exist");
      if (toolName === "Read" && !current.isFile()) {
        deny("sandbox_entry_invalid", "Read requires a regular text file");
      }
      if (toolName === "Glob") {
        if (!current.isDirectory()) {
          deny("sandbox_entry_invalid", "Glob requires a regular directory");
        }
        authorizeGlobPattern(input.pattern, this.fileFormatPolicyVersion);
      }
      if (toolName === "Grep") {
        if (!current.isFile() && !current.isDirectory()) {
          deny("sandbox_entry_invalid", "Grep requires a regular path");
        }
        if (typeof input.pattern !== "string" || input.pattern.length < 1 || input.pattern.length > 1024) {
          deny("sandbox_tool_input_invalid", "Grep pattern is invalid");
        }
      }
    } else {
      await this.authorizeWrite(toolName, target, input, current);
    }
    input[pathField] = relativePath;
    return input;
  }

  async usage(): Promise<{ fileCount: number; sizeBytes: number }> {
    let fileCount = 0;
    let sizeBytes = 0;
    const visit = async (directory: string): Promise<void> => {
      for (const entry of await readdir(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isSymbolicLink()) deny("sandbox_symlink_denied", "sandbox contains a symlink");
        if (entry.isDirectory()) {
          await visit(path);
        } else if (entry.name !== SANDBOX_MARKER) {
          const state = await lstat(path);
          if (!state.isFile()) deny("sandbox_special_file_denied", "sandbox contains a special file");
          fileCount += 1;
          sizeBytes += state.size;
        }
      }
    };
    await visit(this.path);
    return { fileCount, sizeBytes };
  }

  private async authorizeWrite(
    toolName: string,
    target: string,
    input: Record<string, unknown>,
    current: Awaited<ReturnType<typeof optionalStat>>
  ): Promise<void> {
    if (current && !current.isFile()) deny("sandbox_entry_invalid", "write target is invalid");
    const content = toolName === "Write" ? input.content : input.new_string;
    if (typeof content !== "string") {
      deny("sandbox_tool_input_invalid", "write content must be text");
    }
    const incoming = Buffer.byteLength(content, "utf8");
    if (incoming > this.limits.maxFileBytes) {
      deny("sandbox_file_limit_exceeded", "text file exceeds the sandbox limit");
    }
    const usage = await this.usage();
    const previous = Number(current?.size ?? 0);
    if (!current && usage.fileCount >= this.limits.maxFiles) {
      deny("sandbox_file_count_exceeded", "sandbox file count is exhausted");
    }
    if (usage.sizeBytes - previous + Math.max(previous, incoming) > this.limits.capacityBytes) {
      deny("sandbox_capacity_exceeded", "sandbox capacity is exhausted");
    }
    await mkdir(dirname(target), { recursive: true, mode: 0o700 });
  }
}

export class JobSandboxManager {
  constructor(
    readonly root: string,
    readonly limits: JobSandboxLimits = DEFAULT_LIMITS
  ) {
    if (
      limits.capacityBytes < limits.maxFileBytes ||
      limits.maxFiles < 1 ||
      limits.maxFileBytes < 1
    ) {
      throw new Error("Job Sandbox limits are invalid");
    }
  }

  async create(
    jobId: string,
    fileFormatPolicyVersion: FileFormatPolicyVersion = "text-v1"
  ): Promise<JobSandbox> {
    assertIdentifier(jobId);
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    const digest = createHash("sha256").update(jobId).digest("hex").slice(0, 24);
    const path = join(this.root, `job-${digest}-${randomUUID().replaceAll("-", "")}`);
    await mkdir(path, { mode: 0o700 });
    await Promise.all([...TOP_LEVEL].map((name) => mkdir(join(path, name), { mode: 0o700 })));
    await writeFile(
      join(path, SANDBOX_MARKER),
      JSON.stringify({ job_id: jobId, schema_version: 1 }),
      { encoding: "utf8", mode: 0o600, flag: "wx" }
    );
    return new JobSandbox(jobId, path, this.limits, fileFormatPolicyVersion);
  }

  async cleanupResiduals(isJobRunning: (jobId: string) => Promise<boolean>): Promise<string[]> {
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    const cleaned: string[] = [];
    for (const entry of await readdir(this.root, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || !entry.name.startsWith("job-")) continue;
      const path = join(this.root, entry.name);
      let marker: unknown;
      try {
        marker = JSON.parse(await readFile(join(path, SANDBOX_MARKER), "utf8"));
      } catch {
        continue;
      }
      if (
        !record(marker) ||
        Object.keys(marker).sort().join(",") !== "job_id,schema_version" ||
        marker.schema_version !== 1 ||
        typeof marker.job_id !== "string" ||
        !IDENTIFIER.test(marker.job_id)
      ) continue;
      if (await isJobRunning(marker.job_id)) continue;
      await rm(path, { recursive: true, force: true });
      cleaned.push(marker.job_id);
    }
    return cleaned;
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertIdentifier(value: string): void {
  if (!IDENTIFIER.test(value)) deny("sandbox_job_id_invalid", "Job id is invalid");
}

function safeRelativePath(
  value: unknown,
  allowRoot: boolean,
  rootValue: string,
  policyVersion: FileFormatPolicyVersion,
  write: boolean
): string {
  value = sdkRelativePath(value, allowRoot, rootValue);
  if (typeof value !== "string" || value.length < 1 || value.length > 240 || value.includes("\\") || value.includes("\0")) {
    deny("sandbox_path_invalid", "sandbox path is invalid");
  }
  if (value === "." && allowRoot) return value;
  if (
    posix.isAbsolute(value) ||
    posix.normalize(value) !== value ||
    value.split("/").some((part) => part === "." || part === "..") ||
    !TOP_LEVEL.has(value.split("/")[0] ?? "")
  ) deny("sandbox_path_invalid", "sandbox path escaped its Job boundary");
  let definition: ReturnType<typeof textFormatForName>;
  try {
    definition = textFormatForName(posix.basename(value), policyVersion);
  } catch {
    deny("sandbox_file_type_denied", "file format is not allowed");
  }
  if (write && !definition.writable) {
    deny("sandbox_file_read_only", "this file format is read-only");
  }
  return value;
}

function safeDirectoryPath(value: unknown, rootValue: string): string {
  value = sdkRelativePath(value, true, rootValue);
  if (typeof value !== "string" || value.length < 1 || value.length > 240 || value.includes("\\") || value.includes("\0")) {
    deny("sandbox_path_invalid", "sandbox path is invalid");
  }
  if (value === ".") return value;
  if (
    posix.isAbsolute(value) ||
    posix.normalize(value) !== value ||
    value.split("/").some((part) => part === "." || part === "..") ||
    !TOP_LEVEL.has(value.split("/")[0] ?? "")
  ) deny("sandbox_path_invalid", "sandbox path escaped its Job boundary");
  return value;
}

function sdkRelativePath(
  value: unknown,
  allowRoot: boolean,
  rootValue: string
): unknown {
  if (typeof value !== "string" || !posix.isAbsolute(value)) return value;
  if (
    value.length < 1 ||
    value.length > 4096 ||
    value.includes("\\") ||
    value.includes("\0") ||
    posix.normalize(value) !== value ||
    value.split("/").some((part) => part === "." || part === "..")
  ) deny("sandbox_path_invalid", "sandbox path is invalid");
  const root = resolve(rootValue).split(sep).join("/");
  const relativePath = posix.relative(root, value);
  if (relativePath === "") {
    if (allowRoot) return ".";
    deny("sandbox_path_invalid", "sandbox path escaped its Job boundary");
  }
  if (posix.isAbsolute(relativePath) || relativePath === ".." || relativePath.startsWith("../")) {
    deny("sandbox_path_invalid", "sandbox path escaped its Job boundary");
  }
  return relativePath;
}

function authorizeGlobPattern(
  value: unknown,
  policyVersion: FileFormatPolicyVersion
): void {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > 1024 ||
    value.includes("\\") ||
    value.includes("\0") ||
    posix.isAbsolute(value) ||
    value.split("/").some((part) => part === "." || part === "..")
  ) {
    deny("sandbox_tool_input_invalid", "Glob pattern must be a safe relative pattern");
  }
  const allowed = policyVersion === "text-v2" ? [".txt", ".log", ".md"] : [".txt"];
  const lowered = value.toLowerCase();
  if (
    !allowed.some((extension) => lowered.endsWith(extension)) &&
    !allowed.some((extension) => lowered.includes(`${extension.slice(1)}}`))
  ) {
    deny("sandbox_tool_input_invalid", "Glob pattern must target an allowed text format");
  }
}

function resolveSandboxPath(rootValue: string, pathValue: string, allowRoot: boolean): string {
  const root = resolve(rootValue);
  if (pathValue === "." && allowRoot) return root;
  const target = resolve(root, pathValue);
  if (target === root || !target.startsWith(`${root}${sep}`)) {
    deny("sandbox_path_invalid", "sandbox path escaped its Job boundary");
  }
  return target;
}

async function rejectSymlinks(root: string, target: string): Promise<void> {
  let current = resolve(root);
  for (const part of relative(current, target).split(sep).filter(Boolean)) {
    current = join(current, part);
    try {
      const state = await lstat(current);
      if (state.isSymbolicLink()) deny("sandbox_symlink_denied", "symbolic links are not allowed");
      if (!state.isDirectory() && !state.isFile()) {
        deny("sandbox_special_file_denied", "special files are not allowed");
      }
    } catch (error) {
      if (isMissing(error)) return;
      throw error;
    }
  }
}

async function optionalStat(path: string): Promise<Awaited<ReturnType<typeof stat>> | null> {
  try {
    return await stat(path);
  } catch (error) {
    if (isMissing(error)) return null;
    throw error;
  }
}

function isMissing(error: unknown): boolean {
  return record(error) && error.code === "ENOENT";
}

function deny(code: string, message: string): never {
  throw new JobSandboxError(code, message);
}
