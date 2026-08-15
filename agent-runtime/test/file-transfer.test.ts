import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  FileTransferBoundaryError,
  FileTransferCoordinator,
  parseFileTransferControl,
  type FileTransferPort
} from "../src/file-transfer.js";

const META_KEY = "enterprise-agent/file-transfer";
const PROTOCOL = "enterprise-agent.file-transfer/v1";
const CONTENT = Buffer.from("private file body that must stay out of MCP JSON", "utf8");
const CONTENT_SHA256 = createHash("sha256").update(CONTENT).digest("hex");

async function* unusedDownload(): AsyncGenerator<Uint8Array> {
  yield* [];
}

function materializeControl(relativePath = "inputs/evidence.txt"): Record<string, unknown> {
  return {
    content: [{ type: "text", text: "File version is ready for local materialization" }],
    _meta: {
      [META_KEY]: {
        protocol: PROTOCOL,
        action: "MATERIALIZE",
        transfer_id: "transfer-1",
        sandbox_entry_handle: "entry-1",
        relative_path: relativePath,
        expected_size_bytes: CONTENT.byteLength,
        expected_sha256: CONTENT_SHA256
      }
    }
  };
}

function uploadControl(): Record<string, unknown> {
  return {
    content: [{ type: "text", text: "Commit intent accepted" }],
    _meta: {
      [META_KEY]: {
        protocol: PROTOCOL,
        action: "UPLOAD_COMMIT",
        commit_id: "commit-1",
        sandbox_entry_handle: "entry-1"
      }
    }
  };
}

test("File MCP materialize and commit controls trigger local streaming without JSON bytes", async () => {
  const root = await mkdtemp(join(tmpdir(), "file-transfer-ts-"));
  const uploads: Buffer[] = [];
  const port: FileTransferPort = {
    async *download(request) {
      assert.equal(request.transferId, "transfer-1");
      assert.equal(request.jobId, "job-1");
      assert.equal(request.principalToken, "principal-token-not-for-json");
      yield CONTENT.subarray(0, 12);
      yield CONTENT.subarray(12);
    },
    async upload(request) {
      assert.equal(request.commitId, "commit-1");
      assert.equal(request.jobId, "job-1");
      assert.equal(request.principalToken, "principal-token-not-for-json");
      for await (const chunk of request.content) uploads.push(Buffer.from(chunk));
      const value = Buffer.concat(uploads);
      return {
        versionId: "version-2",
        sizeBytes: value.byteLength,
        sha256: createHash("sha256").update(value).digest("hex")
      };
    }
  };
  const coordinator = new FileTransferCoordinator(port);
  const context = {
    jobId: "job-1",
    workspacePath: root,
    principalToken: "principal-token-not-for-json",
    signal: new AbortController().signal
  };
  try {
    const materialized = await coordinator.processMcpControlResult(
      materializeControl(),
      context
    );
    assert.equal(await readFile(join(root, "inputs/evidence.txt"), "utf8"), CONTENT.toString());
    assert.deepEqual(materialized, {
      action: "MATERIALIZED",
      sandbox_entry_handle: "entry-1",
      relative_path: "inputs/evidence.txt",
      size_bytes: CONTENT.byteLength,
      sha256: CONTENT_SHA256
    });

    await writeFile(join(root, "inputs/evidence.txt"), Buffer.from("edited result", "utf8"));
    uploads.length = 0;
    const committed = await coordinator.processMcpControlResult(uploadControl(), context);
    assert.equal(Buffer.concat(uploads).toString("utf8"), "edited result");
    assert.equal(committed.action, "COMMITTED");
    assert.equal(committed.version_id, "version-2");

    const serializedControlAndEvents = JSON.stringify({
      materialize: materializeControl(),
      upload: uploadControl(),
      materialized,
      committed
    });
    assert.equal(serializedControlAndEvents.includes(CONTENT.toString()), false);
    assert.equal(serializedControlAndEvents.includes("edited result"), false);
    assert.equal(serializedControlAndEvents.includes("principal-token-not-for-json"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("File transfer control rejects paths, URLs, object keys and unknown fields", () => {
  for (const invalid of [
    materializeControl("../escape.txt"),
    materializeControl("/absolute.txt"),
    {
      ...materializeControl(),
      _meta: {
        [META_KEY]: {
          ...(materializeControl()._meta as Record<string, any>)[META_KEY],
          url: "https://untrusted.example/file"
        }
      }
    },
    {
      ...materializeControl(),
      _meta: {
        [META_KEY]: {
          ...(materializeControl()._meta as Record<string, any>)[META_KEY],
          object_key: "tenant/private/object"
        }
      }
    }
  ]) {
    assert.throws(
      () => parseFileTransferControl(invalid),
      (error: unknown) => error instanceof FileTransferBoundaryError
    );
  }
});

test("File transfer removes a partial materialization on integrity failure", async () => {
  const root = await mkdtemp(join(tmpdir(), "file-transfer-integrity-"));
  const port: FileTransferPort = {
    async *download() {
      yield Buffer.from("wrong");
    },
    async upload() {
      throw new Error("not used");
    }
  };
  const coordinator = new FileTransferCoordinator(port);
  try {
    await assert.rejects(
      coordinator.processMcpControlResult(materializeControl(), {
        jobId: "job-1",
        workspacePath: root,
        principalToken: "token",
        signal: new AbortController().signal
      }),
      (error: unknown) =>
        error instanceof FileTransferBoundaryError &&
        ["file_transfer_size_mismatch", "file_transfer_integrity_mismatch"].includes(error.code)
    );
    await assert.rejects(readFile(join(root, "inputs/evidence.txt")));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("File transfer uploads only an explicitly registered sandbox entry", async () => {
  const root = await mkdtemp(join(tmpdir(), "file-transfer-explicit-"));
  const uploads: Buffer[] = [];
  const port: FileTransferPort = {
    download() {
      return unusedDownload();
    },
    async upload(request) {
      for await (const chunk of request.content) uploads.push(Buffer.from(chunk));
      const value = Buffer.concat(uploads);
      return {
        versionId: "version-2",
        sizeBytes: value.byteLength,
        sha256: createHash("sha256").update(value).digest("hex")
      };
    }
  };
  const coordinator = new FileTransferCoordinator(port);
  const context = {
    jobId: "job-1",
    workspacePath: root,
    principalToken: "principal-token-not-for-json",
    signal: new AbortController().signal
  };
  try {
    await import("node:fs/promises").then(({ mkdir }) => mkdir(join(root, "outputs")));
    await writeFile(join(root, "outputs/selected.txt"), "selected", "utf8");
    await writeFile(join(root, "outputs/not-selected.txt"), "private draft", "utf8");
    await coordinator.registerSandboxEntry("entry-1", "outputs/selected.txt", context);

    const result = await coordinator.processMcpControlResult(uploadControl(), context);

    assert.equal(result.action, "COMMITTED");
    assert.equal(Buffer.concat(uploads).toString("utf8"), "selected");
    assert.equal(Buffer.concat(uploads).includes(Buffer.from("private draft")), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("File transfer rejects an explicitly registered symbolic link", async () => {
  const root = await mkdtemp(join(tmpdir(), "file-transfer-link-"));
  const coordinator = new FileTransferCoordinator({
    download() {
      return unusedDownload();
    },
    async upload() {
      throw new Error("not used");
    }
  });
  try {
    const { mkdir, symlink } = await import("node:fs/promises");
    await mkdir(join(root, "outputs"));
    await writeFile(join(root, "outside.txt"), "private", "utf8");
    await symlink(join(root, "outside.txt"), join(root, "outputs/link.txt"));
    await assert.rejects(
      coordinator.registerSandboxEntry("entry-1", "outputs/link.txt", {
        jobId: "job-1",
        workspacePath: root,
        principalToken: "token",
        signal: new AbortController().signal
      }),
      (error: unknown) =>
        error instanceof FileTransferBoundaryError &&
        error.code === "file_transfer_symlink_denied"
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
