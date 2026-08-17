import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  JobSandboxError,
  JobSandboxManager,
  SANDBOX_MARKER
} from "../src/job-sandbox.js";

async function root(): Promise<string> {
  return mkdtemp(join(tmpdir(), "job-sandbox-ts-"));
}

test("TypeScript Job Sandbox maps one Job and cleans every terminal path", async () => {
  const parent = await root();
  const manager = new JobSandboxManager(join(parent, "sandboxes"));
  const sandbox = await manager.create("job-1");
  try {
    assert.deepEqual(JSON.parse(await readFile(join(sandbox.path, SANDBOX_MARKER), "utf8")), {
      job_id: "job-1",
      schema_version: 1
    });
    assert.deepEqual(
      await sandbox.authorizeTool("Write", {
        file_path: "work/draft.txt",
        content: "draft"
      }),
      { file_path: "work/draft.txt", content: "draft" }
    );
    await writeFile(join(sandbox.path, "work/draft.txt"), "draft", "utf8");
    assert.equal((await sandbox.authorizeTool("Read", {
      file_path: "work/draft.txt"
    })).file_path, "work/draft.txt");
    assert.equal((await sandbox.authorizeTool("Grep", {
      pattern: "draft",
      path: "."
    })).path, ".");
    assert.deepEqual(await sandbox.authorizeTool("Glob", {
      pattern: "**/*.txt",
      path: "."
    }), { pattern: "**/*.txt", path: "." });
    assert.deepEqual(await sandbox.authorizeTool("Write", {
      file_path: join(sandbox.path, "outputs/sdk-normalized.txt"),
      content: "normalized"
    }), { file_path: "outputs/sdk-normalized.txt", content: "normalized" });
    assert.deepEqual(await sandbox.authorizeTool("Edit", {
      file_path: join(sandbox.path, "work/sdk-normalized.txt"),
      old_string: "before",
      new_string: "after"
    }), {
      file_path: "work/sdk-normalized.txt",
      old_string: "before",
      new_string: "after"
    });
    assert.deepEqual(await sandbox.authorizeTool("Glob", {
      pattern: "**/*.txt",
      path: sandbox.path
    }), { pattern: "**/*.txt", path: "." });
  } finally {
    await sandbox.cleanup();
    await assert.rejects(readFile(join(sandbox.path, SANDBOX_MARKER)));
    await rm(parent, { recursive: true, force: true });
  }
});

test("TypeScript Job Sandbox rejects tools, escapes, links, special files and limits", async () => {
  const parent = await root();
  const manager = new JobSandboxManager(join(parent, "sandboxes"), {
    capacityBytes: 8,
    maxFiles: 1,
    maxFileBytes: 8
  });
  const sandbox = await manager.create("job-1");
  const denied = async (tool: string, input: Record<string, unknown>, code: string) => {
    await assert.rejects(
      sandbox.authorizeTool(tool, input),
      (error: unknown) => error instanceof JobSandboxError && error.code === code
    );
  };
  try {
    await denied("Bash", { command: "pwd" }, "sandbox_tool_denied");
    await denied("Read", { file_path: "/etc/passwd" }, "sandbox_path_invalid");
    await denied(
      "Write",
      { file_path: join(parent, "other-sandbox/output.txt"), content: "x" },
      "sandbox_path_invalid"
    );
    await denied("Read", { file_path: "../escape.txt" }, "sandbox_path_invalid");
    await denied("Read", { file_path: "inputs/file.pdf" }, "sandbox_file_type_denied");
    await denied("Glob", { pattern: "../*.txt", path: "." }, "sandbox_tool_input_invalid");
    await denied("Glob", { pattern: "**/*", path: "." }, "sandbox_tool_input_invalid");
    await denied("Glob", { pattern: "**/*.txt", path: "/tmp" }, "sandbox_path_invalid");

    const outside = join(parent, "outside.txt");
    await writeFile(outside, "private", "utf8");
    const link = join(sandbox.path, "inputs/link.txt");
    await symlink(outside, link);
    await denied("Read", { file_path: "inputs/link.txt" }, "sandbox_symlink_denied");
    await rm(link);

    const nonFile = join(sandbox.path, "inputs/device.txt");
    await mkdir(nonFile);
    await denied("Read", { file_path: "inputs/device.txt" }, "sandbox_entry_invalid");
    await rm(nonFile, { recursive: true });

    await writeFile(join(sandbox.path, "work/one.txt"), "12345678", "utf8");
    await denied(
      "Write",
      { file_path: "work/two.txt", content: "x" },
      "sandbox_file_count_exceeded"
    );
    await denied(
      "Write",
      { file_path: "work/one.txt", content: "123456789" },
      "sandbox_file_limit_exceeded"
    );
  } finally {
    await sandbox.cleanup();
    await rm(parent, { recursive: true, force: true });
  }
});

test("TypeScript residual cleanup removes only marked terminal Job sandboxes", async () => {
  const parent = await root();
  const manager = new JobSandboxManager(join(parent, "sandboxes"));
  const running = await manager.create("job-running");
  const terminal = await manager.create("job-terminal");
  const unmarked = join(manager.root, "job-unmarked");
  const malformed = join(manager.root, "job-malformed");
  await Promise.all([mkdir(unmarked), mkdir(malformed)]);
  await writeFile(join(malformed, SANDBOX_MARKER), "{}", "utf8");
  try {
    assert.deepEqual(
      await manager.cleanupResiduals(async (jobId) => jobId === "job-running"),
      ["job-terminal"]
    );
    assert.equal(await readFile(join(running.path, SANDBOX_MARKER), "utf8").then(() => true), true);
    await assert.rejects(readFile(join(terminal.path, SANDBOX_MARKER)));
    assert.equal(await readFile(join(malformed, SANDBOX_MARKER), "utf8"), "{}");
  } finally {
    await running.cleanup();
    await rm(parent, { recursive: true, force: true });
  }
});

test("text-v2 sandbox allows Markdown writes and LOG reads but denies LOG mutation", async () => {
  const parent = await root();
  const manager = new JobSandboxManager(join(parent, "sandboxes"));
  const sandbox = await manager.create("job-text-v2", "text-v2");
  try {
    await writeFile(join(sandbox.path, "inputs/service.log"), "line\n", "utf8");
    assert.equal(
      (await sandbox.authorizeTool("Read", { file_path: "inputs/service.log" })).file_path,
      "inputs/service.log"
    );
    assert.equal(
      (await sandbox.authorizeTool("Write", {
        file_path: "outputs/report.md",
        content: "# report"
      })).file_path,
      "outputs/report.md"
    );
    await assert.rejects(
      sandbox.authorizeTool("Edit", {
        file_path: "inputs/service.log",
        old_string: "line",
        new_string: "changed"
      }),
      (error: unknown) =>
        error instanceof JobSandboxError && error.code === "sandbox_file_read_only"
    );
  } finally {
    await sandbox.cleanup();
    await rm(parent, { recursive: true, force: true });
  }
});
