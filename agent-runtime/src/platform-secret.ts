import {
  createDecipheriv,
  createHash,
  type DecipherGCM
} from "node:crypto";
import { readFile } from "node:fs/promises";

export interface EncryptedPlatformSecret {
  readonly secretId: string;
  readonly version: number;
  readonly ciphertext: string;
  readonly nonce: string;
  readonly keyId: string;
  readonly algorithm: string;
}

export class PlatformSecretError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "PlatformSecretError";
  }
}

function decodeBase64Url(value: string): Buffer {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new PlatformSecretError(
      "runtime_secret_encoding_invalid",
      "Platform Secret encoding is invalid"
    );
  }
  return Buffer.from(value, "base64url");
}

export class PlatformSecretDecryptor {
  private constructor(private readonly key: Buffer) {}

  static fromMaterial(material: string): PlatformSecretDecryptor {
    const normalized = material.trim();
    if (!normalized.startsWith("EA_MASTER_KEY_V1:")) {
      throw new PlatformSecretError(
        "runtime_master_key_format_invalid",
        "Master Key must use EA_MASTER_KEY_V1 format"
      );
    }
    const key = decodeBase64Url(normalized.slice("EA_MASTER_KEY_V1:".length));
    if (key.length !== 32) {
      key.fill(0);
      throw new PlatformSecretError(
        "runtime_master_key_length_invalid",
        "Master Key must contain exactly 32 bytes"
      );
    }
    return new PlatformSecretDecryptor(key);
  }

  static async fromFile(path: string): Promise<PlatformSecretDecryptor> {
    try {
      return PlatformSecretDecryptor.fromMaterial(await readFile(path, "ascii"));
    } catch (error) {
      if (error instanceof PlatformSecretError) throw error;
      throw new PlatformSecretError(
        "runtime_master_key_unavailable",
        "Master Key file cannot be read"
      );
    }
  }

  decrypt(secret: EncryptedPlatformSecret): string {
    if (!new Set(["AES-256-GCM-AAD-V1", "AES-256-GCM"]).has(secret.algorithm)) {
      throw new PlatformSecretError(
        "runtime_secret_algorithm_unsupported",
        "Platform Secret algorithm is unsupported"
      );
    }
    const keyId = createHash("sha256").update(this.key).digest("hex").slice(0, 16);
    if (secret.keyId && secret.keyId !== keyId) {
      throw new PlatformSecretError(
        "runtime_secret_key_mismatch",
        "Platform Secret is encrypted with another Master Key"
      );
    }
    let plaintext: Buffer | undefined;
    try {
      const nonce = decodeBase64Url(secret.nonce);
      const encryptedWithTag = decodeBase64Url(secret.ciphertext);
      if (nonce.length !== 12 || encryptedWithTag.length <= 16) {
        throw new Error("invalid AES-GCM payload length");
      }
      const ciphertext = encryptedWithTag.subarray(0, -16);
      const tag = encryptedWithTag.subarray(-16);
      const decipher: DecipherGCM = createDecipheriv("aes-256-gcm", this.key, nonce);
      if (secret.algorithm === "AES-256-GCM-AAD-V1") {
        decipher.setAAD(
          Buffer.from(`platform-secret|v1|${secret.secretId}|${secret.version}`, "utf8")
        );
      }
      decipher.setAuthTag(tag);
      plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
      return plaintext.toString("utf8");
    } catch (error) {
      if (error instanceof PlatformSecretError) throw error;
      throw new PlatformSecretError(
        "runtime_secret_decrypt_failed",
        "Platform Secret authentication failed"
      );
    } finally {
      plaintext?.fill(0);
    }
  }
}
