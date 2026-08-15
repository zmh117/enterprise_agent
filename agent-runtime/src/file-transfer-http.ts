import type {
  FileTransferPort,
  FileUploadReceipt
} from "./file-transfer.js";
import { FileTransferBoundaryError } from "./file-transfer.js";

const MAX_RECEIPT_BYTES = 64 * 1024;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SHA256 = /^[a-f0-9]{64}$/;

export type RuntimeFetch = typeof fetch;

function internalUrl(mcpServerUrl: string, path: string): URL {
  const endpoint = new URL(mcpServerUrl);
  if (
    !["http:", "https:"].includes(endpoint.protocol) ||
    endpoint.username ||
    endpoint.password ||
    endpoint.search ||
    endpoint.hash ||
    endpoint.pathname !== "/mcp"
  ) {
    throw new FileTransferBoundaryError(
      "file_transfer_endpoint_invalid",
      "File Service endpoint is outside the fixed deployment boundary"
    );
  }
  endpoint.pathname = path;
  return endpoint;
}

function safeIdentifier(value: string, field: string): string {
  if (!IDENTIFIER.test(value)) {
    throw new FileTransferBoundaryError(
      "file_transfer_control_invalid",
      `${field} must be an opaque identifier`
    );
  }
  return value;
}

function safeNetworkFailure(status?: number): FileTransferBoundaryError {
  return new FileTransferBoundaryError(
    "file_service_unavailable",
    status === undefined
      ? "File Service transfer failed"
      : `File Service transfer failed with status ${status}`
  );
}

async function boundedJson(response: Response): Promise<Record<string, unknown>> {
  const body = new Uint8Array(await response.arrayBuffer());
  if (body.byteLength > MAX_RECEIPT_BYTES) {
    throw new FileTransferBoundaryError(
      "file_transfer_receipt_invalid",
      "File Service upload receipt exceeded the safe limit"
    );
  }
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } catch {
    throw new FileTransferBoundaryError(
      "file_transfer_receipt_invalid",
      "File Service upload receipt was invalid"
    );
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new FileTransferBoundaryError(
      "file_transfer_receipt_invalid",
      "File Service upload receipt was invalid"
    );
  }
  return value as Record<string, unknown>;
}

export class HttpFileTransferPort implements FileTransferPort {
  constructor(
    private readonly mcpServerUrl: string,
    private readonly runtimeFetch: RuntimeFetch = fetch
  ) {
    internalUrl(mcpServerUrl, "/internal/v1/file-transfers/probe/content");
  }

  async *download(request: {
    readonly transferId: string;
    readonly jobId: string;
    readonly principalToken: string;
    readonly signal: AbortSignal;
  }): AsyncIterable<Uint8Array> {
    const transferId = safeIdentifier(request.transferId, "transfer_id");
    let response: Response;
    try {
      response = await this.runtimeFetch(
        internalUrl(
          this.mcpServerUrl,
          `/internal/v1/file-transfers/${encodeURIComponent(transferId)}/content`
        ),
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${request.principalToken}`,
            "X-Job-Id": safeIdentifier(request.jobId, "job_id")
          },
          signal: request.signal,
          redirect: "error"
        }
      );
    } catch {
      if (request.signal.aborted) throw request.signal.reason;
      throw safeNetworkFailure();
    }
    if (!response.ok || response.body === null) throw safeNetworkFailure(response.status);
    const mediaType = response.headers.get("content-type")?.split(";", 1)[0]?.trim();
    if (mediaType !== "application/octet-stream") {
      throw new FileTransferBoundaryError(
        "file_transfer_content_type_invalid",
        "File Service returned an unexpected transfer content type"
      );
    }
    try {
      for await (const chunk of response.body) {
        if (request.signal.aborted) throw request.signal.reason;
        yield chunk;
      }
    } catch {
      if (request.signal.aborted) throw request.signal.reason;
      throw safeNetworkFailure();
    }
  }

  async upload(request: {
    readonly commitId: string;
    readonly jobId: string;
    readonly principalToken: string;
    readonly content: AsyncIterable<Uint8Array>;
    readonly signal: AbortSignal;
  }): Promise<FileUploadReceipt> {
    const commitId = safeIdentifier(request.commitId, "commit_id");
    const init: RequestInit & { duplex: "half" } = {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${request.principalToken}`,
        "Content-Type": "application/octet-stream",
        "X-Job-Id": safeIdentifier(request.jobId, "job_id")
      },
      body: request.content as unknown as BodyInit,
      duplex: "half",
      signal: request.signal,
      redirect: "error"
    };
    let response: Response;
    try {
      response = await this.runtimeFetch(
        internalUrl(
          this.mcpServerUrl,
          `/internal/v1/file-commits/${encodeURIComponent(commitId)}/content`
        ),
        init
      );
    } catch {
      if (request.signal.aborted) throw request.signal.reason;
      throw safeNetworkFailure();
    }
    if (!response.ok) throw safeNetworkFailure(response.status);
    const value = await boundedJson(response);
    const versionId = value.version_id;
    const sizeBytes = value.size_bytes;
    const sha256 = value.sha256;
    if (
      typeof versionId !== "string" ||
      !IDENTIFIER.test(versionId) ||
      !Number.isSafeInteger(sizeBytes) ||
      Number(sizeBytes) < 0 ||
      typeof sha256 !== "string" ||
      !SHA256.test(sha256)
    ) {
      throw new FileTransferBoundaryError(
        "file_transfer_receipt_invalid",
        "File Service upload receipt was invalid"
      );
    }
    return {
      versionId,
      sizeBytes: Number(sizeBytes),
      sha256
    };
  }
}
