import {
  createDecipheriv,
  createHmac,
  type DecipherGCM
} from "node:crypto";
import { readFile } from "node:fs/promises";

import type { DraftModelProbeRequest } from "./generated/contracts.js";

const MASTER_KEY_PREFIX = "EA_MASTER_KEY_V1:";
const DERIVATION_LABEL = "enterprise-agent:model-probe-envelope:v1";
const ALGORITHM = "AES-256-GCM-DERIVED-PROBE-V1";
const MAX_LIFETIME_SECONDS = 90;
const MAX_CIPHERTEXT_BYTES = 12_288;
const MAX_CONSUMED_PROBES = 4096;

export interface DecryptedDraftModelProbe {
  readonly config: Record<string, unknown>;
  readonly apiKey: string;
}

export class ModelProbeEnvelopeError extends Error {
  readonly code = "model_connection_probe_envelope_invalid";

  constructor(message: string) {
    super(message);
    this.name = "ModelProbeEnvelopeError";
  }
}

function decodeBase64Url(value: string, maximumBytes: number): Buffer {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new ModelProbeEnvelopeError("Draft probe envelope encoding is invalid");
  }
  const decoded = Buffer.from(value, "base64url");
  if (decoded.length > maximumBytes || decoded.toString("base64url") !== value) {
    decoded.fill(0);
    throw new ModelProbeEnvelopeError("Draft probe envelope encoding is not canonical");
  }
  return decoded;
}

function aad(request: DraftModelProbeRequest): Buffer {
  return Buffer.from(
    `model-probe-envelope|v1|${request.probe_id}|${request.runtime_kind}|${request.config_hash}|${request.credential_envelope.expires_at}`,
    "utf8"
  );
}

export class ModelProbeEnvelopeDecryptor {
  private readonly consumed = new Map<string, number>();

  private constructor(
    private readonly key: Buffer,
    private readonly now: () => number = () => Math.floor(Date.now() / 1000)
  ) {}

  static fromMaterial(
    material: string,
    now?: () => number
  ): ModelProbeEnvelopeDecryptor {
    const normalized = material.trim();
    if (!normalized.startsWith(MASTER_KEY_PREFIX)) {
      throw new ModelProbeEnvelopeError("Master Key format is invalid for draft probes");
    }
    const masterKey = decodeBase64Url(
      normalized.slice(MASTER_KEY_PREFIX.length),
      32
    );
    if (masterKey.length !== 32) {
      masterKey.fill(0);
      throw new ModelProbeEnvelopeError("Master Key length is invalid for draft probes");
    }
    try {
      const key = createHmac("sha256", masterKey).update(DERIVATION_LABEL, "utf8").digest();
      return new ModelProbeEnvelopeDecryptor(key, now);
    } finally {
      masterKey.fill(0);
    }
  }

  static async fromFile(path: string): Promise<ModelProbeEnvelopeDecryptor> {
    try {
      return ModelProbeEnvelopeDecryptor.fromMaterial(await readFile(path, "ascii"));
    } catch (error) {
      if (error instanceof ModelProbeEnvelopeError) throw error;
      throw new ModelProbeEnvelopeError("Master Key file cannot be read for draft probes");
    }
  }

  decrypt(request: DraftModelProbeRequest): DecryptedDraftModelProbe {
    const envelope = request.credential_envelope;
    const now = this.now();
    if (
      envelope.algorithm !== ALGORITHM ||
      envelope.expires_at <= now ||
      envelope.expires_at > now + MAX_LIFETIME_SECONDS
    ) {
      throw new ModelProbeEnvelopeError("Draft probe envelope is expired or unsupported");
    }
    const nonce = decodeBase64Url(envelope.nonce, 12);
    const encryptedWithTag = decodeBase64Url(envelope.ciphertext, MAX_CIPHERTEXT_BYTES);
    if (nonce.length !== 12 || encryptedWithTag.length <= 16) {
      nonce.fill(0);
      encryptedWithTag.fill(0);
      throw new ModelProbeEnvelopeError("Draft probe envelope payload length is invalid");
    }
    const ciphertext = encryptedWithTag.subarray(0, -16);
    const tag = encryptedWithTag.subarray(-16);
    let plaintext: Buffer | undefined;
    try {
      const decipher: DecipherGCM = createDecipheriv("aes-256-gcm", this.key, nonce);
      decipher.setAAD(aad(request));
      decipher.setAuthTag(tag);
      plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
      const parsed = JSON.parse(plaintext.toString("utf8")) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("draft probe plaintext is not an object");
      }
      const payload = parsed as Record<string, unknown>;
      if (
        Object.keys(payload).sort().join(",") !== "api_key,config,schema_version" ||
        payload.schema_version !== 1 ||
        !payload.config ||
        typeof payload.config !== "object" ||
        Array.isArray(payload.config) ||
        typeof payload.api_key !== "string" ||
        payload.api_key.length === 0 ||
        Buffer.byteLength(payload.api_key, "utf8") > 4000
      ) {
        throw new Error("draft probe plaintext shape is invalid");
      }
      this.consumeOnce(request.probe_id, envelope.expires_at, now);
      return {
        config: payload.config as Record<string, unknown>,
        apiKey: payload.api_key
      };
    } catch (error) {
      if (error instanceof ModelProbeEnvelopeError) throw error;
      throw new ModelProbeEnvelopeError("Draft probe envelope authentication failed");
    } finally {
      plaintext?.fill(0);
      nonce.fill(0);
      encryptedWithTag.fill(0);
    }
  }

  private consumeOnce(probeId: string, expiresAt: number, now: number): void {
    for (const [id, expiry] of this.consumed) {
      if (expiry <= now) this.consumed.delete(id);
    }
    if (this.consumed.has(probeId)) {
      throw new ModelProbeEnvelopeError("Draft probe envelope was already consumed");
    }
    if (this.consumed.size >= MAX_CONSUMED_PROBES) {
      throw new ModelProbeEnvelopeError("Draft probe replay ledger is full");
    }
    this.consumed.set(probeId, expiresAt);
  }
}
