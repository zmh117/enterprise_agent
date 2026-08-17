import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { JobSandboxError, JobSandboxManager } from "../src/job-sandbox.js";
import {
  type FileFormatPolicyVersion,
  type TextFormatAction,
  type TextFormatCode,
  TextFormatPolicyError,
  validateTextBytes,
  validateTextFormatAction,
  validateTextFormatMetadata
} from "../src/text-format-policy.js";

interface MetadataCase {
  readonly id: string;
  readonly policy_version: FileFormatPolicyVersion;
  readonly display_name: string;
  readonly media_type: string;
  readonly agent_output?: boolean;
  readonly expected_format?: TextFormatCode;
  readonly canonical_media_type?: string;
  readonly expected_error?: string;
}

interface ActionCase {
  readonly id: string;
  readonly policy_version: FileFormatPolicyVersion;
  readonly format_code: TextFormatCode;
  readonly action: TextFormatAction;
  readonly expected_format?: TextFormatCode;
  readonly expected_error?: string;
}

interface ContentCase {
  readonly id: string;
  readonly bytes_base64: string;
  readonly agent_output: boolean;
  readonly max_bytes?: number;
  readonly had_utf8_bom?: boolean;
  readonly expected_error?: string;
}

interface SandboxCase {
  readonly id: string;
  readonly policy_version: FileFormatPolicyVersion;
  readonly tool: "Read" | "Write";
  readonly path: string;
  readonly existing_file?: boolean;
  readonly symlink?: boolean;
  readonly content_size?: number;
  readonly max_file_bytes?: number;
  readonly expected_path?: string;
  readonly expected_error?: string;
}

interface Fixture {
  readonly schema_version: number;
  readonly metadata_cases: readonly MetadataCase[];
  readonly action_cases: readonly ActionCase[];
  readonly content_cases: readonly ContentCase[];
  readonly sandbox_cases: readonly SandboxCase[];
}

async function fixture(): Promise<Fixture> {
  return JSON.parse(
    await readFile(
      join(process.cwd(), "contracts", "text-format-policy-v2.fixture.json"),
      "utf8"
    )
  ) as Fixture;
}

function policyError(code: string): (error: unknown) => boolean {
  return (error) => error instanceof TextFormatPolicyError && error.code === code;
}

test("shared text-format fixture matches TypeScript metadata, MIME, action and byte policy", async () => {
  const value = await fixture();
  assert.equal(value.schema_version, 1);
  for (const item of value.metadata_cases) {
    const execute = () => validateTextFormatMetadata({
      displayName: item.display_name,
      mediaType: item.media_type,
      policyVersion: item.policy_version,
      ...(item.agent_output === undefined ? {} : { agentOutput: item.agent_output })
    });
    if (item.expected_error) {
      assert.throws(execute, policyError(item.expected_error), item.id);
      continue;
    }
    const result = execute();
    assert.equal(result.code, item.expected_format, item.id);
    assert.equal(result.canonicalMediaType, item.canonical_media_type, item.id);
  }
  for (const item of value.action_cases) {
    const execute = () => validateTextFormatAction({
      policyVersion: item.policy_version,
      formatCode: item.format_code,
      action: item.action
    });
    if (item.expected_error) {
      assert.throws(execute, policyError(item.expected_error), item.id);
      continue;
    }
    assert.equal(execute().code, item.expected_format, item.id);
  }
  for (const item of value.content_cases) {
    const bytes = Buffer.from(item.bytes_base64, "base64");
    const execute = () => validateTextBytes(bytes, {
      agentOutput: item.agent_output,
      ...(item.max_bytes === undefined ? {} : { maxBytes: item.max_bytes })
    });
    if (item.expected_error) {
      assert.throws(execute, policyError(item.expected_error), item.id);
      continue;
    }
    assert.equal(execute().hadUtf8Bom, item.had_utf8_bom, item.id);
  }
});

test("shared text-format fixture matches TypeScript sandbox path and symlink policy", async () => {
  const value = await fixture();
  for (const item of value.sandbox_cases) {
    const parent = await mkdtemp(join(tmpdir(), "text-policy-ts-"));
    const maxFileBytes = item.max_file_bytes ?? 15 * 1024 * 1024;
    const manager = new JobSandboxManager(join(parent, "sandboxes"), {
      capacityBytes: Math.max(maxFileBytes, 1024),
      maxFiles: 40,
      maxFileBytes
    });
    const sandbox = await manager.create(`fixture-${item.id}`, item.policy_version);
    try {
      if (item.existing_file) {
        await writeFile(join(sandbox.path, item.path), "existing", "utf8");
      }
      if (item.symlink) {
        const outside = join(parent, "outside.txt");
        await writeFile(outside, "outside", "utf8");
        await symlink(outside, join(sandbox.path, item.path));
      }
      const input = item.tool === "Write"
        ? { file_path: item.path, content: "x".repeat(item.content_size ?? 1) }
        : { file_path: item.path };
      const execute = () => sandbox.authorizeTool(item.tool, input);
      if (item.expected_error) {
        await assert.rejects(
          execute,
          (error: unknown) =>
            error instanceof JobSandboxError && error.code === item.expected_error,
          item.id
        );
      } else {
        assert.equal((await execute()).file_path, item.expected_path, item.id);
      }
    } finally {
      await sandbox.cleanup();
      await rm(parent, { recursive: true, force: true });
    }
  }
});
